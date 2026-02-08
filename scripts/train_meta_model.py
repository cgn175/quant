#!/usr/bin/env python3
"""Meta-label XGBoost training pipeline.

Workflow:
  1. Load 4h OHLCV data for all symbols from data_4h/
  2. Compute features via build_features_v2.add_features_v2()
  3. Generate primary signals via primary_signals.combined_signals()
  4. Apply triple barrier labels to signal bars via labeling.label_signals()
  5. Build meta-features = V2 features + signal_type one-hot
  6. Time-split: train before --split-date, validate after
  7. Train ONE XGBoost binary classifier (conservative fixed params)
  8. Evaluate with detailed metrics

The idea: primary signals generate many candidates, triple barrier labels
which were profitable, and XGBoost learns to predict which signals to take.

Usage:
  python scripts/train_meta_model.py \\
      --data-dir data_4h \\
      --symbols BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT \\
      --split-date 2025-02-08 \\
      --output models_meta
"""

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import ta
import xgboost as xgb
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

# ---------- Sibling imports ----------
sys.path.insert(0, str(Path(__file__).parent))
from build_features_v2 import FEATURE_COLUMNS_V2, add_features_v2
from labeling import label_signals
from primary_signals import combined_signals

# ---------- Meta-feature columns ----------

SIGNAL_TYPE_COLUMNS = [
    "signal_type_trend",
    "signal_type_breakout",
]

META_FEATURE_COLUMNS = FEATURE_COLUMNS_V2 + SIGNAL_TYPE_COLUMNS

# ---------- Conservative XGBoost params ----------

XGBOOST_PARAMS = {
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

N_ESTIMATORS = 500
EARLY_STOPPING_ROUNDS = 30


# ---------- Data loading ----------


def load_symbol_data(data_dir: Path, symbol: str) -> pd.DataFrame:
    """Load all 4h OHLCV parquet files for a symbol."""
    pattern = f"{symbol.replace('/', '_')}_*.parquet"
    files = list(data_dir.glob(pattern))
    if not files:
        raise ValueError(f"No data for {symbol} in {data_dir}")

    dfs = []
    for f in sorted(files):
        print(f"  Loading {f}")
        dfs.append(pd.read_parquet(f))

    df = pd.concat(dfs).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


# ---------- Pipeline ----------


def build_meta_dataset(
    data_dir: Path,
    symbols: list[str],
    tp_atr_mult: float = 2.0,
    sl_atr_mult: float = 1.0,
    max_holding_bars: int = 20,
) -> pd.DataFrame:
    """Build meta-labeling dataset for all symbols.

    Steps per symbol:
      1. Load 4h OHLCV
      2. Compute v2 features (cross-asset needs all symbols loaded first)
      3. Generate primary signals
      4. Label signal bars with triple barrier
      5. Attach features + one-hot signal type

    Returns:
        DataFrame indexed by entry timestamp with meta-features + label.
    """
    # --- Load all raw 4h data ---
    raw_4h: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        print(f"\nLoading {symbol}...")
        raw_4h[symbol] = load_symbol_data(data_dir, symbol)

    # --- Load funding + daily data if available ---
    funding_dir = data_dir / "funding"
    daily_dir = Path("data_daily")

    funding_data: dict[str, pd.DataFrame] = {}
    if funding_dir.exists():
        for symbol in symbols:
            pattern = f"{symbol.replace('/', '_')}_funding_*.parquet"
            files = list(funding_dir.glob(pattern))
            if files:
                print(f"  Loading funding: {files[0]}")
                funding_data[symbol] = pd.read_parquet(files[0])

    daily_data: dict[str, pd.DataFrame] = {}
    if daily_dir.exists():
        for symbol in symbols:
            pattern = f"{symbol.replace('/', '_')}_1d_*.parquet"
            files = list(daily_dir.glob(pattern))
            if files:
                print(f"  Loading daily: {files[0]}")
                daily_data[symbol] = pd.read_parquet(files[0])

    # --- Build features + signals + labels per symbol ---
    all_meta: list[pd.DataFrame] = []

    for symbol in symbols:
        df_4h = raw_4h[symbol]
        print(f"\n{'=' * 60}")
        print(f"Processing {symbol}")
        print(f"{'=' * 60}")
        print(f"  Bars: {len(df_4h)} | {df_4h.index[0]} to {df_4h.index[-1]}")

        # 1. Compute v2 features
        print("  Computing v2 features...")
        featured = add_features_v2(
            df_4h,
            funding_df=funding_data.get(symbol),
            daily_df=daily_data.get(symbol),
            cross_asset_dfs=raw_4h,
        )

        # 2. Generate primary signals
        print("  Generating primary signals...")
        signals = combined_signals(featured)
        signal_mask = signals["signal"]
        n_signals = signal_mask.sum()
        print(f"  Primary signals: {int(n_signals)}")

        if n_signals == 0:
            print(f"  No signals for {symbol}, skipping.")
            continue

        # Signal type breakdown
        type_counts = signals.loc[signal_mask, "signal_type"].value_counts()
        for stype, cnt in type_counts.items():
            print(f"    {stype}: {cnt}")

        # 3. Triple barrier labeling on signal bars
        print("  Applying triple barrier labels...")
        signal_indices = featured.index[signal_mask]

        atr_14 = ta.volatility.average_true_range(
            featured["high"], featured["low"], featured["close"], window=14
        )

        labels_df = label_signals(
            close=featured["close"],
            high=featured["high"],
            low=featured["low"],
            atr=atr_14,
            signal_indices=signal_indices,
            side=1,  # long only for primary signals
            tp_atr_mult=tp_atr_mult,
            sl_atr_mult=sl_atr_mult,
            max_holding_bars=max_holding_bars,
        )

        if labels_df.empty:
            print(f"  No valid labels for {symbol}, skipping.")
            continue

        n_labels = len(labels_df)
        win_rate = labels_df["label"].mean() * 100
        avg_ret = labels_df["return"].mean() * 100
        print(
            f"  Labels: {n_labels} | Win rate: {win_rate:.1f}% | Avg ret: {avg_ret:+.3f}%"
        )

        # Exit reason breakdown
        for reason in ["tp", "sl", "time"]:
            cnt = (labels_df["exit_reason"] == reason).sum()
            pct = cnt / n_labels * 100
            print(f"    {reason}: {cnt} ({pct:.1f}%)")

        # 4. Build meta-features for labeled bars
        labels_df = labels_df.set_index("entry_idx")

        # Get features at signal entry bars
        meta_rows = featured.loc[labels_df.index, FEATURE_COLUMNS_V2].copy()

        # One-hot signal type
        signal_types_at_entry = signals.loc[labels_df.index, "signal_type"]
        meta_rows["signal_type_trend"] = (
            signal_types_at_entry.isin(["trend", "both"])
        ).astype(int)
        meta_rows["signal_type_breakout"] = (
            signal_types_at_entry.isin(["breakout", "both"])
        ).astype(int)

        # Attach label and metadata
        meta_rows["label"] = labels_df["label"].values
        meta_rows["meta_return"] = labels_df["return"].values
        meta_rows["exit_reason"] = labels_df["exit_reason"].values
        meta_rows["holding_bars"] = labels_df["holding_bars"].values
        meta_rows["symbol"] = symbol

        all_meta.append(meta_rows)

    if not all_meta:
        raise ValueError("No meta-labeling data generated for any symbol!")

    combined = pd.concat(all_meta, axis=0).sort_index()

    # Drop rows with NaN in feature columns
    n_before = len(combined)
    combined = combined.dropna(subset=META_FEATURE_COLUMNS)
    n_after = len(combined)
    if n_before > n_after:
        print(f"\nDropped {n_before - n_after} rows with NaN features")

    print(f"\n{'=' * 60}")
    print("META-LABELING DATASET SUMMARY")
    print(f"{'=' * 60}")
    print(f"Total samples:  {len(combined)}")
    print(
        f"Win (label=1):  {(combined['label'] == 1).sum()} ({(combined['label'] == 1).mean() * 100:.1f}%)"
    )
    print(
        f"Loss (label=0): {(combined['label'] == 0).sum()} ({(combined['label'] == 0).mean() * 100:.1f}%)"
    )
    print(f"Date range:     {combined.index[0]} to {combined.index[-1]}")

    # Per-symbol breakdown
    print(f"\nPer-symbol breakdown:")
    for sym, grp in combined.groupby("symbol"):
        wr = grp["label"].mean() * 100
        print(f"  {sym}: {len(grp):5d} samples | WR={wr:.1f}%")

    return combined


# ---------- Training ----------


def train_meta_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
) -> tuple[xgb.XGBClassifier, dict]:
    """Train binary XGBoost meta-model with conservative fixed params.

    Args:
        X_train: Training features.
        y_train: Training labels (0/1).
        X_val: Validation features.
        y_val: Validation labels (0/1).

    Returns:
        Tuple of (trained model, metrics dict).
    """
    print(f"\n{'=' * 60}")
    print("TRAINING META-MODEL")
    print(f"{'=' * 60}")
    print(
        f"Train: {len(X_train)} samples (Win={int((y_train == 1).sum())}, Loss={int((y_train == 0).sum())})"
    )
    print(
        f"Val:   {len(X_val)} samples (Win={int((y_val == 1).sum())}, Loss={int((y_val == 0).sum())})"
    )
    print(f"\nParams (fixed, conservative):")
    for k, v in XGBOOST_PARAMS.items():
        print(f"  {k}: {v}")
    print(f"  n_estimators: {N_ESTIMATORS}")
    print(f"  early_stopping_rounds: {EARLY_STOPPING_ROUNDS}")

    model = xgb.XGBClassifier(
        **XGBOOST_PARAMS,
        n_estimators=N_ESTIMATORS,
        early_stopping_rounds=EARLY_STOPPING_ROUNDS,
    )

    model.fit(
        X_train,
        y_train,
        eval_set=[(X_train, y_train), (X_val, y_val)],
        verbose=50,
    )

    # --- Predictions ---
    y_pred_train = model.predict(X_train)
    y_pred_val = model.predict(X_val)
    y_proba_val = model.predict_proba(X_val)[:, 1]

    # --- Metrics ---
    val_accuracy = accuracy_score(y_val, y_pred_val)
    val_precision = precision_score(y_val, y_pred_val, zero_division=0)
    val_recall = recall_score(y_val, y_pred_val, zero_division=0)
    val_f1 = f1_score(y_val, y_pred_val, average="binary")
    val_auc = roc_auc_score(y_val, y_proba_val)

    print(f"\n{'=' * 60}")
    print("OUT-OF-SAMPLE VALIDATION RESULTS")
    print(f"{'=' * 60}")
    print(f"Accuracy:  {val_accuracy:.4f}")
    print(f"Precision: {val_precision:.4f}")
    print(f"Recall:    {val_recall:.4f}")
    print(f"F1:        {val_f1:.4f}")
    print(f"AUC:       {val_auc:.4f}")
    print()
    print(classification_report(y_val, y_pred_val, target_names=["Loss", "Win"]))

    # --- Win rate by confidence threshold ---
    print("Win rate by confidence threshold:")
    threshold_stats = {}
    for t in [0.50, 0.55, 0.60, 0.65, 0.70]:
        mask = y_proba_val > t
        n_trades = int(mask.sum())
        if n_trades > 0:
            wr = float((y_val[mask] == 1).mean() * 100)
            print(f"  P(win)>{t:.2f}: {n_trades:4d} trades, WR={wr:.1f}%")
            threshold_stats[f"threshold_{t:.2f}"] = {
                "n_trades": n_trades,
                "win_rate": round(wr, 2),
            }
        else:
            print(f"  P(win)>{t:.2f}:    0 trades")

    # --- Feature importance ---
    importances = model.feature_importances_
    fi = sorted(zip(META_FEATURE_COLUMNS, importances), key=lambda x: -x[1])
    print(f"\nTop 15 features:")
    for name, imp in fi[:15]:
        print(f"  {name:25s}: {imp:.4f}")

    # --- Overfit check ---
    train_accuracy = accuracy_score(y_train, y_pred_train)
    train_f1 = f1_score(y_train, y_pred_train, average="binary")
    print(f"\nOverfit check:")
    print(
        f"  Train accuracy: {train_accuracy:.4f} | Val accuracy: {val_accuracy:.4f} | Gap: {train_accuracy - val_accuracy:.4f}"
    )
    print(
        f"  Train F1:       {train_f1:.4f} | Val F1:       {val_f1:.4f} | Gap: {train_f1 - val_f1:.4f}"
    )

    metrics = {
        "train_accuracy": float(train_accuracy),
        "train_f1": float(train_f1),
        "val_accuracy": float(val_accuracy),
        "val_precision": float(val_precision),
        "val_recall": float(val_recall),
        "val_f1": float(val_f1),
        "val_auc": float(val_auc),
        "train_size": len(X_train),
        "val_size": len(X_val),
        "n_features": len(META_FEATURE_COLUMNS),
        "best_iteration": int(model.best_iteration)
        if hasattr(model, "best_iteration")
        else N_ESTIMATORS,
        "params": XGBOOST_PARAMS,
        "n_estimators": N_ESTIMATORS,
        "early_stopping_rounds": EARLY_STOPPING_ROUNDS,
        "threshold_analysis": threshold_stats,
        "feature_importance_top15": {name: float(imp) for name, imp in fi[:15]},
    }

    return model, metrics


# ---------- Main ----------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train meta-label XGBoost model for signal filtering"
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
        "--split-date",
        type=str,
        default="2025-02-08",
        help="Train/val split date (default: 2025-02-08)",
    )
    parser.add_argument(
        "--tp-mult",
        type=float,
        default=2.0,
        help="Take-profit ATR multiplier (default: 2.0)",
    )
    parser.add_argument(
        "--sl-mult",
        type=float,
        default=1.0,
        help="Stop-loss ATR multiplier (default: 1.0)",
    )
    parser.add_argument(
        "--max-bars",
        type=int,
        default=20,
        help="Max holding period in bars (default: 20)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="models_meta",
        help="Output directory (default: models_meta)",
    )

    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")]
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output)
    split_date = pd.Timestamp(args.split_date)

    print(f"Meta-label training pipeline")
    print(f"  Symbols:    {symbols}")
    print(f"  Data dir:   {data_dir}")
    print(f"  Split date: {split_date}")
    print(f"  Output:     {output_dir}")
    print(f"  TP mult:    {args.tp_mult}")
    print(f"  SL mult:    {args.sl_mult}")
    print(f"  Max bars:   {args.max_bars}")

    # --- Build meta-labeling dataset ---
    meta_df = build_meta_dataset(
        data_dir=data_dir,
        symbols=symbols,
        tp_atr_mult=args.tp_mult,
        sl_atr_mult=args.sl_mult,
        max_holding_bars=args.max_bars,
    )

    # --- Time split ---
    X = meta_df[META_FEATURE_COLUMNS]
    y = meta_df["label"].astype(int)

    train_mask = X.index < split_date
    val_mask = X.index >= split_date

    X_train, y_train = X[train_mask], y[train_mask]
    X_val, y_val = X[val_mask], y[val_mask]

    if len(X_train) == 0:
        raise ValueError(f"No training data before {split_date}")
    if len(X_val) == 0:
        raise ValueError(f"No validation data after {split_date}")

    print(f"\nTime split at {args.split_date}:")
    print(
        f"  Train: {X_train.index[0]} to {X_train.index[-1]} ({len(X_train)} samples)"
    )
    print(f"  Val:   {X_val.index[0]} to {X_val.index[-1]} ({len(X_val)} samples)")

    # --- Train ---
    model, metrics = train_meta_model(X_train, y_train, X_val, y_val)

    # --- Save ---
    output_dir.mkdir(parents=True, exist_ok=True)

    # Model files
    model.save_model(output_dir / "xgboost_meta.json")
    joblib.dump(model, output_dir / "xgboost_meta.joblib")

    # Metrics
    metrics["symbols"] = symbols
    metrics["split_date"] = args.split_date
    metrics["tp_atr_mult"] = args.tp_mult
    metrics["sl_atr_mult"] = args.sl_mult
    metrics["max_holding_bars"] = args.max_bars
    with open(output_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    # Feature list
    with open(output_dir / "features.json", "w") as f:
        json.dump(META_FEATURE_COLUMNS, f, indent=2)

    print(f"\n{'=' * 60}")
    print("SAVED")
    print(f"{'=' * 60}")
    print(f"  Model:    {output_dir / 'xgboost_meta.json'}")
    print(f"  Joblib:   {output_dir / 'xgboost_meta.joblib'}")
    print(f"  Metrics:  {output_dir / 'metrics.json'}")
    print(f"  Features: {output_dir / 'features.json'}")


if __name__ == "__main__":
    main()
