#!/usr/bin/env python3
"""Walk-forward validation for the regime-aware meta-labeling strategy.

Retrains the meta-model monthly on a rolling window and tests on
out-of-sample data.  Produces per-window metrics, aggregate statistics,
a cumulative equity curve, and a profitability gate check.

Usage:
    python scripts/walk_forward.py \
        --data-dir data_4h \
        --symbols BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT \
        --train-days 180 --test-days 30 --step-days 30 \
        --threshold 0.60
"""

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import ta
import xgboost as xgb

# ---------------------------------------------------------------------------
# Import sibling modules
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))
from build_features_v2 import FEATURE_COLUMNS_V2, add_features_v2  # noqa: E402
from labeling import label_signals  # noqa: E402
from primary_signals import combined_signals  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

XGBOOST_PARAMS: dict = {
    "objective": "binary:logistic",
    "eval_metric": "auc",
    "max_depth": 4,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.7,
    "min_child_weight": 10,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "gamma": 0.1,
    "random_state": 42,
    "tree_method": "hist",
}

NUM_BOOST_ROUNDS = 200
EARLY_STOPPING_ROUNDS = 20

TP_ATR_MULT = 2.0
SL_ATR_MULT = 1.0
MAX_HOLDING_BARS = 20  # 20 × 4h = 80h ≈ 3.3 days
FEE_BPS = 5  # 0.05% per side → 0.10% round-trip


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_symbol_data(data_dir: Path, symbol: str) -> pd.DataFrame:
    """Load all parquet files for *symbol* from *data_dir* and return a
    de-duplicated, sorted DataFrame with a DatetimeIndex."""
    pattern = f"{symbol.replace('/', '_')}_*.parquet"
    files = sorted(data_dir.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No data for {symbol} in {data_dir}")
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


# ---------------------------------------------------------------------------
# Feature / label pipeline for one symbol slice
# ---------------------------------------------------------------------------


def _build_meta_features(
    df: pd.DataFrame,
    signals_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build meta-features: V2 features + one-hot signal_type at signal bars.

    Returns a DataFrame aligned on signal-bar timestamps only, with columns
    = FEATURE_COLUMNS_V2 + ['signal_type_trend', 'signal_type_breakout',
      'signal_type_both'].
    """
    signal_mask = signals_df["signal"]
    sig_idx = df.index[signal_mask]
    if sig_idx.empty:
        return pd.DataFrame()

    meta = df.loc[sig_idx, FEATURE_COLUMNS_V2].copy()

    # One-hot encode signal_type
    for stype in ("trend", "breakout", "both"):
        meta[f"signal_type_{stype}"] = (
            signals_df.loc[sig_idx, "signal_type"] == stype
        ).astype(int)

    return meta


def _meta_feature_cols() -> list[str]:
    return FEATURE_COLUMNS_V2 + [
        "signal_type_trend",
        "signal_type_breakout",
        "signal_type_both",
    ]


def prepare_window(
    df_raw: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    cross_asset_dfs: dict[str, pd.DataFrame] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Prepare features, signals, and labels for a time window.

    Returns:
        meta_features: DataFrame of meta-features at signal bars.
        labels_df: DataFrame from label_signals (entry_idx, label, return, …).
        df_featured: Full featured DataFrame (for reference).
    """
    # Slice — include a warm-up buffer so TA indicators are valid at `start`
    warmup_bars = 60  # ~10 days of 4h bars
    earliest = df_raw.index.searchsorted(start)
    buf_start = max(0, earliest - warmup_bars)
    df_slice = df_raw.iloc[buf_start:].copy()
    df_slice = df_slice[df_slice.index < end]

    if len(df_slice) < warmup_bars:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # Features (v2)
    df_feat = add_features_v2(df_slice, cross_asset_dfs=cross_asset_dfs)

    # Restrict to the actual window (drop warm-up)
    df_window = df_feat[df_feat.index >= start].copy()
    if df_window.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # Primary signals
    signals_df = combined_signals(df_window)

    # Meta-features
    meta = _build_meta_features(df_window, signals_df)
    if meta.empty:
        return pd.DataFrame(), pd.DataFrame(), df_window

    # ATR for labeling
    atr = ta.volatility.average_true_range(
        df_window["high"], df_window["low"], df_window["close"], window=14
    )

    signal_indices = meta.index
    labels_df = label_signals(
        close=df_window["close"],
        high=df_window["high"],
        low=df_window["low"],
        atr=atr,
        signal_indices=signal_indices,
        side=1,
        tp_atr_mult=TP_ATR_MULT,
        sl_atr_mult=SL_ATR_MULT,
        max_holding_bars=MAX_HOLDING_BARS,
    )

    return meta, labels_df, df_window


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def train_meta_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
) -> xgb.XGBClassifier | None:
    """Train an XGBoost meta-model. Returns None if insufficient data."""
    if len(X_train) < 30:
        return None

    # Use 15% of train as internal eval set for early stopping
    split = int(len(X_train) * 0.85)
    X_tr, X_ev = X_train.iloc[:split], X_train.iloc[split:]
    y_tr, y_ev = y_train.iloc[:split], y_train.iloc[split:]

    model = xgb.XGBClassifier(
        n_estimators=NUM_BOOST_ROUNDS,
        early_stopping_rounds=EARLY_STOPPING_ROUNDS,
        **XGBOOST_PARAMS,
    )
    model.fit(
        X_tr,
        y_tr,
        eval_set=[(X_ev, y_ev)],
        verbose=False,
    )
    return model


# ---------------------------------------------------------------------------
# Walk-forward engine
# ---------------------------------------------------------------------------


def run_walk_forward(
    data_dir: Path,
    symbols: list[str],
    train_days: int = 180,
    test_days: int = 30,
    step_days: int = 30,
    threshold: float = 0.60,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Execute the full walk-forward validation.

    Returns:
        all_trades: DataFrame with every OOS trade and its outcome.
        window_metrics: DataFrame with per-window summary statistics.
    """
    # --- Load raw data for all symbols ---
    raw_data: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        try:
            raw_data[sym] = load_symbol_data(data_dir, sym)
            print(
                f"Loaded {sym}: {len(raw_data[sym])} bars "
                f"({raw_data[sym].index[0]} → {raw_data[sym].index[-1]})"
            )
        except FileNotFoundError as e:
            print(f"Warning: {e}")
    if not raw_data:
        raise ValueError("No data loaded — check --data-dir and --symbols")

    # Determine date range across all symbols
    global_start = max(df.index[0] for df in raw_data.values())
    global_end = min(df.index[-1] for df in raw_data.values())
    print(f"\nCommon date range: {global_start} → {global_end}")

    # Generate windows
    train_delta = timedelta(days=train_days)
    test_delta = timedelta(days=test_days)
    step_delta = timedelta(days=step_days)

    windows: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]] = []
    cursor = global_start + train_delta
    while cursor + test_delta <= global_end:
        train_start = cursor - train_delta
        test_start = cursor
        test_end = cursor + test_delta
        windows.append((train_start, test_start, test_end))
        cursor += step_delta

    if not windows:
        raise ValueError(
            f"Not enough data for even one window "
            f"(need {train_days + test_days} days, have "
            f"{(global_end - global_start).days} days)"
        )

    print(f"Generated {len(windows)} walk-forward windows\n")

    # --- Iterate over windows ---
    all_trades: list[pd.DataFrame] = []
    window_records: list[dict] = []
    fee_rate = FEE_BPS / 10_000  # per side

    for i, (train_start, test_start, test_end) in enumerate(windows):
        print(f"{'─' * 60}")
        print(
            f"Window {i + 1}/{len(windows)}  "
            f"Train: {train_start.date()} → {test_start.date()}  "
            f"Test: {test_start.date()} → {test_end.date()}"
        )

        # ---- Aggregate training data across symbols ----
        train_metas: list[pd.DataFrame] = []
        train_labels: list[pd.DataFrame] = []

        for sym, df_raw in raw_data.items():
            meta, labels, _ = prepare_window(
                df_raw, train_start, test_start, cross_asset_dfs=raw_data
            )
            if meta.empty or labels.empty:
                continue

            # Align meta-features and labels on entry_idx
            labels = labels.set_index("entry_idx")
            common = meta.index.intersection(labels.index)
            if common.empty:
                continue

            meta_aligned = meta.loc[common].copy()
            labels_aligned = labels.loc[common].copy()
            meta_aligned["symbol"] = sym
            labels_aligned["symbol"] = sym
            train_metas.append(meta_aligned)
            train_labels.append(labels_aligned)

        if not train_metas:
            print("  ⚠ No training signals — skipping window")
            window_records.append(
                _empty_window_record(i + 1, train_start, test_start, test_end)
            )
            continue

        train_meta = pd.concat(train_metas).sort_index()
        train_lbl = pd.concat(train_labels).sort_index()

        feat_cols = _meta_feature_cols()
        X_train = train_meta[feat_cols].copy()
        y_train = train_lbl["label"].astype(int)

        # Handle NaN features
        X_train = X_train.fillna(0)

        print(
            f"  Train samples: {len(X_train)}  "
            f"(pos={int(y_train.sum())}, neg={int((y_train == 0).sum())})"
        )

        # ---- Train model ----
        model = train_meta_model(X_train, y_train)
        if model is None:
            print("  ⚠ Insufficient data for training — skipping window")
            window_records.append(
                _empty_window_record(i + 1, train_start, test_start, test_end)
            )
            continue

        # ---- Evaluate on test period ----
        test_trades_list: list[pd.DataFrame] = []

        for sym, df_raw in raw_data.items():
            meta_test, labels_test, _ = prepare_window(
                df_raw, test_start, test_end, cross_asset_dfs=raw_data
            )
            if meta_test.empty or labels_test.empty:
                continue

            labels_test = labels_test.set_index("entry_idx")
            common = meta_test.index.intersection(labels_test.index)
            if common.empty:
                continue

            meta_test = meta_test.loc[common]
            labels_test = labels_test.loc[common]

            X_test = meta_test[feat_cols].fillna(0)
            proba = model.predict_proba(X_test)[:, 1]

            # Apply confidence threshold
            pass_mask = proba >= threshold
            if not pass_mask.any():
                continue

            trades = labels_test[pass_mask].copy()
            trades["meta_prob"] = proba[pass_mask]
            trades["symbol"] = sym
            trades["window"] = i + 1
            trades["train_start"] = train_start
            trades["test_start"] = test_start
            trades["test_end"] = test_end
            # Adjust return for fees (round-trip)
            trades["net_return"] = trades["return"] - 2 * fee_rate
            test_trades_list.append(trades)

        if not test_trades_list:
            print("  ⚠ No test trades above threshold")
            window_records.append(
                _empty_window_record(i + 1, train_start, test_start, test_end)
            )
            continue

        test_trades = pd.concat(test_trades_list).sort_index()
        all_trades.append(test_trades)

        # ---- Per-window metrics ----
        rec = _compute_window_metrics(
            test_trades, i + 1, train_start, test_start, test_end
        )
        window_records.append(rec)

        print(
            f"  Trades: {rec['n_trades']}  "
            f"WR: {rec['win_rate']:.1f}%  "
            f"Avg: {rec['avg_return'] * 100:+.3f}%  "
            f"Total: {rec['total_return'] * 100:+.2f}%  "
            f"PF: {rec['profit_factor']:.2f}"
        )

    # --- Assemble results ---
    window_metrics = pd.DataFrame(window_records)

    if all_trades:
        trades_df = pd.concat(all_trades).sort_index()
    else:
        trades_df = pd.DataFrame()

    return trades_df, window_metrics


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------


def _compute_window_metrics(
    trades: pd.DataFrame,
    window_num: int,
    train_start: pd.Timestamp,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
) -> dict:
    """Compute summary metrics for one walk-forward window."""
    n = len(trades)
    wins = (trades["net_return"] > 0).sum()
    win_rate = wins / n * 100 if n > 0 else 0.0
    avg_ret = trades["net_return"].mean()
    total_ret = trades["net_return"].sum()

    gross_profit = trades.loc[trades["net_return"] > 0, "net_return"].sum()
    gross_loss = abs(trades.loc[trades["net_return"] < 0, "net_return"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    return {
        "window": window_num,
        "train_start": train_start,
        "test_start": test_start,
        "test_end": test_end,
        "n_trades": n,
        "win_rate": win_rate,
        "avg_return": avg_ret,
        "total_return": total_ret,
        "profit_factor": profit_factor,
    }


def _empty_window_record(
    window_num: int,
    train_start: pd.Timestamp,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
) -> dict:
    return {
        "window": window_num,
        "train_start": train_start,
        "test_start": test_start,
        "test_end": test_end,
        "n_trades": 0,
        "win_rate": 0.0,
        "avg_return": 0.0,
        "total_return": 0.0,
        "profit_factor": 0.0,
    }


# ---------------------------------------------------------------------------
# Aggregate reporting
# ---------------------------------------------------------------------------


def print_window_table(wm: pd.DataFrame) -> None:
    """Pretty-print the per-window metrics table."""
    print(f"\n{'=' * 90}")
    print("PER-WINDOW METRICS")
    print(f"{'=' * 90}")
    header = (
        f"{'Win':>4}  {'Train Start':>12}  {'Test Start':>12}  {'Test End':>12}  "
        f"{'Trades':>6}  {'WR%':>6}  {'Avg%':>8}  {'Total%':>8}  {'PF':>6}"
    )
    print(header)
    print("─" * 90)
    for _, row in wm.iterrows():
        ts = row["train_start"]
        te_s = row["test_start"]
        te_e = row["test_end"]
        print(
            f"{int(row['window']):4d}  "
            f"{str(ts.date()):>12}  "
            f"{str(te_s.date()):>12}  "
            f"{str(te_e.date()):>12}  "
            f"{int(row['n_trades']):6d}  "
            f"{row['win_rate']:6.1f}  "
            f"{row['avg_return'] * 100:+8.3f}  "
            f"{row['total_return'] * 100:+8.2f}  "
            f"{row['profit_factor']:6.2f}"
        )
    print("─" * 90)


def compute_aggregate_metrics(
    trades: pd.DataFrame,
    wm: pd.DataFrame,
) -> dict:
    """Compute aggregate metrics across all walk-forward windows."""
    if trades.empty:
        return {
            "total_trades": 0,
            "overall_win_rate": 0.0,
            "overall_avg_return": 0.0,
            "overall_total_return": 0.0,
            "overall_sharpe": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "trades_per_day": 0.0,
            "profitable_months_pct": 0.0,
        }

    n_trades = len(trades)
    wins = (trades["net_return"] > 0).sum()
    overall_wr = wins / n_trades * 100

    avg_ret = trades["net_return"].mean()
    total_ret = trades["net_return"].sum()

    # Sharpe: annualized from per-trade returns
    # Assume ~6 bars/day on 4h, average holding ~10 bars → ~1.7 days per trade
    # Use a simpler approach: compute daily returns from equity curve
    equity = (1 + trades["net_return"]).cumprod()
    # Group by date to get daily returns
    trades_sorted = trades.sort_index().copy()
    trades_sorted["equity"] = (1 + trades_sorted["net_return"]).cumprod()
    trades_sorted["date"] = trades_sorted.index.date
    daily_equity = trades_sorted.groupby("date")["equity"].last()
    daily_returns = daily_equity.pct_change().dropna()
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        sharpe = daily_returns.mean() / daily_returns.std() * np.sqrt(365)
    else:
        sharpe = 0.0

    # Max drawdown from cumulative equity
    cum_equity = (1 + trades.sort_index()["net_return"]).cumprod()
    running_max = cum_equity.cummax()
    drawdown = (cum_equity - running_max) / running_max
    max_dd = abs(drawdown.min()) if len(drawdown) > 0 else 0.0

    # Profit factor
    gross_profit = trades.loc[trades["net_return"] > 0, "net_return"].sum()
    gross_loss = abs(trades.loc[trades["net_return"] < 0, "net_return"].sum())
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Expectancy (avg return per trade as %)
    expectancy = avg_ret * 100

    # Trades per day
    if len(trades) > 0:
        date_range_days = (trades.index.max() - trades.index.min()).days
        trades_per_day = n_trades / max(date_range_days, 1)
    else:
        trades_per_day = 0.0

    # Profitable months percentage
    trades_monthly = trades.sort_index().copy()
    trades_monthly["month"] = trades_monthly.index.to_period("M")
    monthly_pnl = trades_monthly.groupby("month")["net_return"].sum()
    n_months = len(monthly_pnl)
    profitable_months = (monthly_pnl > 0).sum()
    profitable_months_pct = profitable_months / n_months * 100 if n_months > 0 else 0.0

    return {
        "total_trades": n_trades,
        "overall_win_rate": overall_wr,
        "overall_avg_return": avg_ret,
        "overall_total_return": total_ret,
        "overall_sharpe": sharpe,
        "max_drawdown": max_dd,
        "profit_factor": pf,
        "expectancy": expectancy,
        "trades_per_day": trades_per_day,
        "profitable_months_pct": profitable_months_pct,
    }


def print_aggregate_metrics(agg: dict) -> None:
    """Print aggregate metrics and profitability gate."""
    print(f"\n{'=' * 60}")
    print("AGGREGATE WALK-FORWARD METRICS")
    print(f"{'=' * 60}")
    print(f"Total trades:          {agg['total_trades']}")
    print(f"Overall win rate:      {agg['overall_win_rate']:.1f}%")
    print(f"Average return/trade:  {agg['overall_avg_return'] * 100:+.3f}%")
    print(f"Total return:          {agg['overall_total_return'] * 100:+.2f}%")
    print(f"Sharpe ratio:          {agg['overall_sharpe']:.2f}")
    print(f"Max drawdown:          {agg['max_drawdown'] * 100:.1f}%")
    print(f"Profit factor:         {agg['profit_factor']:.2f}")
    print(f"Expectancy:            {agg['expectancy']:+.3f}%")
    print(f"Trades/day:            {agg['trades_per_day']:.2f}")
    print(f"Profitable months:     {agg['profitable_months_pct']:.0f}%")


def print_profitability_gate(agg: dict) -> None:
    """Print the pass/fail profitability gate check."""
    checks = [
        ("Win rate > 45%", agg["overall_win_rate"] > 45),
        ("Expectancy > 0.3%", agg["expectancy"] > 0.3),
        ("Profit factor > 1.3", agg["profit_factor"] > 1.3),
        ("Sharpe > 1.0", agg["overall_sharpe"] > 1.0),
        ("Max drawdown < 25%", agg["max_drawdown"] < 0.25),
        ("Trades/day < 3", agg["trades_per_day"] < 3),
        ("Profitable months > 60%", agg["profitable_months_pct"] > 60),
    ]

    all_pass = all(passed for _, passed in checks)

    print(f"\n{'=' * 60}")
    print("PROFITABILITY GATE")
    print(f"{'=' * 60}")
    for name, passed in checks:
        status = "PASS" if passed else "FAIL"
        marker = "✓" if passed else "✗"
        print(f"  {marker} {name:30s} [{status}]")
    print(f"{'─' * 60}")
    overall = "PASS" if all_pass else "FAIL"
    marker = "✓" if all_pass else "✗"
    print(f"  {marker} {'OVERALL':30s} [{overall}]")
    print(f"{'=' * 60}")


def print_equity_curve(trades: pd.DataFrame) -> None:
    """Print a simple text-based cumulative equity curve."""
    if trades.empty:
        print("\nNo trades — cannot print equity curve.")
        return

    sorted_trades = trades.sort_index()
    cum_equity = (1 + sorted_trades["net_return"]).cumprod()

    print(f"\n{'=' * 60}")
    print("CUMULATIVE EQUITY CURVE (1+r compounded)")
    print(f"{'=' * 60}")

    # Sample at most 30 points for display
    n = len(cum_equity)
    step = max(1, n // 30)
    sampled = cum_equity.iloc[::step]
    if sampled.index[-1] != cum_equity.index[-1]:
        sampled = pd.concat([sampled, cum_equity.iloc[[-1]]])

    max_eq = sampled.max()
    min_eq = sampled.min()
    bar_width = 40

    for ts, eq in sampled.items():
        if max_eq > min_eq:
            filled = int((eq - min_eq) / (max_eq - min_eq) * bar_width)
        else:
            filled = bar_width // 2
        bar = "█" * filled + "░" * (bar_width - filled)
        date_str = str(ts.date()) if hasattr(ts, "date") else str(ts)[:10]
        print(f"  {date_str}  {bar}  {eq:.4f}")

    print(f"\n  Start:  1.0000")
    print(f"  End:    {cum_equity.iloc[-1]:.4f}")
    print(f"  Peak:   {cum_equity.cummax().iloc[-1]:.4f}")


# ---------------------------------------------------------------------------
# Save results
# ---------------------------------------------------------------------------


def save_results(
    trades: pd.DataFrame,
    agg: dict,
    wm: pd.DataFrame,
    output_dir: Path,
) -> None:
    """Save trade log and summary to disk."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Trade log
    trade_path = output_dir / "walk_forward_results.parquet"
    if not trades.empty:
        # Convert Timestamp columns for clean parquet serialization
        save_df = trades.copy()
        for col in ("train_start", "test_start", "test_end", "exit_idx"):
            if col in save_df.columns:
                save_df[col] = pd.to_datetime(save_df[col])
        save_df.to_parquet(trade_path)
        print(f"\nSaved {len(trades)} trades → {trade_path}")
    else:
        print("\nNo trades to save.")

    # Summary JSON
    summary = {
        "aggregate": _serialize_dict(agg),
        "per_window": wm.to_dict(orient="records"),
    }
    summary_path = output_dir / "walk_forward_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"Saved summary → {summary_path}")


def _serialize_dict(d: dict) -> dict:
    """Make dict JSON-serializable (handle numpy types, inf, etc.)."""
    out = {}
    for k, v in d.items():
        if isinstance(v, (np.integer,)):
            out[k] = int(v)
        elif isinstance(v, (np.floating,)):
            out[k] = float(v) if np.isfinite(v) else str(v)
        elif isinstance(v, float) and not np.isfinite(v):
            out[k] = str(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Walk-forward validation for regime-aware meta-labeling strategy"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data_4h",
        help="Directory with 4h OHLCV parquet files",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT",
        help="Comma-separated symbols",
    )
    parser.add_argument(
        "--train-days",
        type=int,
        default=180,
        help="Training window in days (default: 180)",
    )
    parser.add_argument(
        "--test-days",
        type=int,
        default=30,
        help="Test window in days (default: 30)",
    )
    parser.add_argument(
        "--step-days",
        type=int,
        default=30,
        help="Step between windows in days (default: 30)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.60,
        help="Meta-model confidence threshold (default: 0.60)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="results",
        help="Output directory for results (default: results)",
    )

    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")]
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)

    print("=" * 60)
    print("WALK-FORWARD VALIDATION")
    print("=" * 60)
    print(f"Data dir:      {data_dir}")
    print(f"Symbols:       {', '.join(symbols)}")
    print(f"Train window:  {args.train_days} days")
    print(f"Test window:   {args.test_days} days")
    print(f"Step:          {args.step_days} days")
    print(f"Threshold:     {args.threshold}")
    print(f"Output:        {output_dir}")
    print()

    trades, window_metrics = run_walk_forward(
        data_dir=data_dir,
        symbols=symbols,
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        threshold=args.threshold,
    )

    # --- Report ---
    print_window_table(window_metrics)

    agg = compute_aggregate_metrics(trades, window_metrics)
    print_aggregate_metrics(agg)
    print_equity_curve(trades)
    print_profitability_gate(agg)

    # --- Save ---
    save_results(trades, agg, window_metrics, output_dir)


if __name__ == "__main__":
    main()
