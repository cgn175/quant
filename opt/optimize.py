#!/usr/bin/env python3
"""Optuna parameter optimization for trend-following strategy.

Searches for per-symbol optimal parameters maximizing annualized Sortino ratio.

Usage:
    python3 opt/optimize.py --symbol BTCUSDT --n-trials 100
    python3 opt/optimize.py                               # all symbols, 50 trials each
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import optuna
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from backtest_trend import TrendFollowingBacktester
from trend_signals import generate_signals

ROOT = Path(__file__).resolve().parent.parent
OPTUNA_DB = ROOT / "opt" / "optuna_studies.db"
RESULTS_DIR = ROOT / "opt" / "results"


def load_ohlcv_from_sqlite(db_path: Path, symbol: str) -> pd.DataFrame:
    """Load OHLCV data from training.db candles table."""
    conn = sqlite3.connect(str(db_path))
    query = """
        SELECT open_time, open, high, low, close, volume
        FROM candles
        WHERE symbol = ?
        ORDER BY open_time
    """
    df = pd.read_sql_query(query, conn, params=(symbol,))
    conn.close()

    if df.empty:
        raise ValueError(f"No candle data for {symbol} in {db_path}")

    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    df = df[["open", "high", "low", "close", "volume"]]
    return df


def load_funding_from_sqlite(db_path: Path, symbol: str) -> pd.DataFrame | None:
    """Load funding rate data from training.db funding table."""
    conn = sqlite3.connect(str(db_path))
    query = """
        SELECT timestamp as ts, funding_rate as fundingRate
        FROM funding
        WHERE symbol = ?
        ORDER BY timestamp
    """
    df = pd.read_sql_query(query, conn, params=(symbol,))
    conn.close()

    if df.empty:
        return None

    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    df = df[["fundingRate"]]
    return df


def get_symbols(db_path: Path) -> list[str]:
    """Get distinct symbols from the database."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.execute("SELECT DISTINCT symbol FROM candles ORDER BY symbol")
    symbols = [row[0] for row in cur.fetchall()]
    conn.close()
    return symbols



def make_objective(ohlcv: pd.DataFrame, funding: pd.DataFrame | None, symbol: str):
    """Return an Optuna objective function using Walk-Forward Validation."""

    sym_key = symbol.replace("USDT", "/USDT")
    
    # 1. Split Train (Optimization) vs Test (Final Validation)
    # Matching XGBoost trainer split
    TRAIN_CUTOFF = pd.Timestamp("2025-07-01", tz="UTC")
    
    train_mask = ohlcv.index < TRAIN_CUTOFF
    df_train = ohlcv[train_mask].copy()
    
    # Funding split
    funding_train = None
    if funding is not None:
        funding_train = funding[funding.index < TRAIN_CUTOFF].copy()

    # 2. Define Walk-Forward Windows (5 folds)
    # We use expanding window or rolling window? Let's use rolling 6-month windows 
    # with 1-month steps to test robustness, or simple K-Fold.
    # Given financial time series, simple TimeSeriesSplit is best.
    # Let's do 5 splits.
    from sklearn.model_selection import TimeSeriesSplit
    tscv = TimeSeriesSplit(n_splits=5)
    
    # Pre-calculate splits indices to avoid re-calculating inside trial
    splits = list(tscv.split(df_train))

    def objective(trial: optuna.Trial) -> float:
        donchian_period = trial.suggest_int("donchian_period", 12, 30)
        ema_fast = trial.suggest_int("ema_fast", 5, 14)
        ema_slow = trial.suggest_int("ema_slow", 16, 30)
        atr_stop_mult = trial.suggest_float("atr_stop_mult", 2.0, 5.0, step=0.5)
        adx_threshold = trial.suggest_int("adx_threshold", 15, 30)
        chandelier_lookback = trial.suggest_int("chandelier_lookback", 5, 20)

        params = {
            "donchian_period": donchian_period,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "atr_stop_mult": atr_stop_mult,
            "adx_threshold": float(adx_threshold),
        }

        scores = []
        
        # Walk-Forward Validation Loop
        for fold_i, (train_idx, val_idx) in enumerate(splits):
            # For time series, standard CV trains on past, tests on future.
            # But here we want to find stable params across different regimes.
            # We treat the "validation" part of the split as the backtest period for this fold.
            # Actually, standard TimeSeriesSplit trains on [0..k] and tests on [k+1..n].
            # We want to maximize performance on the "test" fold using params.
            
            # Slice data for this fold (the "validation" segment of the split)
            # We backtest on the validation segment to see how params perform on unseen future
            # relative to the training part.
            # WAIT: In param optimization, we usually want to maximize performance on the 
            # *segment being tested*.
            
            # Let's verify robustness: Run backtest on the validation slice.
            # If params are robust, they should perform well on these future slices.
            
            fold_df = df_train.iloc[val_idx]
            if len(fold_df) < 500: # skip tiny folds
                continue
                
            start_dt = fold_df.index[0]
            end_dt = fold_df.index[-1]
            
            # Slice funding
            fold_funding = None
            if funding_train is not None:
                fold_funding = funding_train[(funding_train.index >= start_dt) & (funding_train.index <= end_dt)]

            try:
                signals = generate_signals(fold_df, fold_funding, params=params)
                
                signals_dict = {sym_key: signals}
                ohlcv_dict = {sym_key: fold_df}

                bt = TrendFollowingBacktester(
                    initial_equity=10_000,
                    risk_per_trade=0.01,
                    atr_stop_mult=atr_stop_mult,
                    max_leverage=2.0,
                    max_daily_loss=0.03,
                    fee_rate=0.0004,
                    slippage_bps=5.0,
                    chandelier_lookback=chandelier_lookback,
                )
                result = bt.run(signals_dict, ohlcv_dict)
                metrics = result.metrics

                if "error" in metrics or metrics.get("num_trades", 0) < 3:
                    scores.append(0.0)
                    continue

                # Use Sortino
                s = metrics.get("sortino", 0.0)
                if np.isnan(s) or np.isinf(s):
                    s = 0.0
                scores.append(s)

            except Exception:
                scores.append(0.0)

        # Objective is average Sortino across all folds
        if not scores:
            return float("-inf")
            
        return np.mean(scores)

    return objective


def run_oos_validation(
    ohlcv: pd.DataFrame, 
    funding: pd.DataFrame | None, 
    symbol: str, 
    best_params: dict
) -> dict:
    """Run one final backtest on the held-out test set (post-2025-07-01)."""
    sym_key = symbol.replace("USDT", "/USDT")
    TRAIN_CUTOFF = pd.Timestamp("2025-07-01", tz="UTC")
    
    # Test set only
    test_mask = ohlcv.index >= TRAIN_CUTOFF
    df_test = ohlcv[test_mask].copy()
    
    if df_test.empty:
        return {"error": "No test data"}
        
    funding_test = None
    if funding is not None:
        funding_test = funding[funding.index >= TRAIN_CUTOFF].copy()
        
    # Extract strategy params (exclude non-strategy keys if any)
    strat_params = {
        "donchian_period": best_params["donchian_period"],
        "ema_fast": best_params["ema_fast"],
        "ema_slow": best_params["ema_slow"],
        "atr_stop_mult": best_params["atr_stop_multiplier"], # check key name mapping
        "adx_threshold": float(best_params["adx_threshold"]),
    }
    
    # Config params
    chandelier = best_params["chandelier_lookback"]
    
    try:
        signals = generate_signals(df_test, funding_test, params=strat_params)
        
        bt = TrendFollowingBacktester(
            initial_equity=10_000,
            risk_per_trade=0.01,
            atr_stop_mult=strat_params["atr_stop_mult"],
            max_leverage=2.0,
            max_daily_loss=0.03,
            fee_rate=0.0004,
            slippage_bps=5.0,
            chandelier_lookback=chandelier,
        )
        result = bt.run({sym_key: signals}, {sym_key: df_test})
        return result.metrics
    except Exception as e:
        return {"error": str(e)}


def _to_native(val):
    """Convert numpy types to native Python for clean YAML serialization."""
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, np.ndarray):
        return val.tolist()
    return val


def save_best_params(symbol: str, study: optuna.Study, oos_metrics: dict) -> Path:
    """Write best params to YAML."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    best = study.best_trial

    data = {
        "symbol": symbol,
        "optimized_at": datetime.now(timezone.utc).isoformat(),
        "train_score_cv_sortino": round(float(best.value), 4),
        "test_score_oos_sortino": round(float(oos_metrics.get("sortino", 0.0)), 4),
        "test_metrics": {
             k: round(float(v), 4) if isinstance(v, (float, np.floating)) else _to_native(v)
             for k, v in oos_metrics.items() 
             if k in ["total_return", "sharpe", "max_drawdown", "win_rate", "num_trades"]
        },
        "params": {
            "donchian_period": int(best.params["donchian_period"]),
            "ema_fast": int(best.params["ema_fast"]),
            "ema_slow": int(best.params["ema_slow"]),
            "atr_stop_multiplier": float(best.params["atr_stop_mult"]),
            "adx_threshold": int(best.params["adx_threshold"]),
            "chandelier_lookback": int(best.params["chandelier_lookback"]),
        },
    }

    out = RESULTS_DIR / f"best_params_{symbol}.yaml"
    with open(out, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return out


def optimize_symbol(
    symbol: str,
    db_path: Path,
    n_trials: int,
) -> optuna.Study:
    """Run Optuna optimization for a single symbol."""
    print(f"\n{'='*60}")
    print(f"Optimizing {symbol}  ({n_trials} trials)")
    print(f"{'='*60}")

    ohlcv = load_ohlcv_from_sqlite(db_path, symbol)
    funding = load_funding_from_sqlite(db_path, symbol)
    print(f"  Loaded {len(ohlcv):,} candles total")

    storage = f"sqlite:///{OPTUNA_DB}"
    study_name = f"trend_{symbol}_wf"  # changed name to avoid conflict with previous runs

    study = optuna.create_study(
        study_name=study_name,
        storage=storage,
        direction="maximize",
        load_if_exists=True,
    )

    objective = make_objective(ohlcv, funding, symbol)
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    # Run OOS Validation
    print("\n  Running Out-of-Sample (OOS) Validation...")
    best_params_dict = {
        "donchian_period": study.best_params["donchian_period"],
        "ema_fast": study.best_params["ema_fast"],
        "ema_slow": study.best_params["ema_slow"],
        "atr_stop_multiplier": study.best_params["atr_stop_mult"],
        "adx_threshold": study.best_params["adx_threshold"],
        "chandelier_lookback": study.best_params["chandelier_lookback"],
    }
    oos_metrics = run_oos_validation(ohlcv, funding, symbol, best_params_dict)

    out_path = save_best_params(symbol, study, oos_metrics)

    print(f"\n  Best CV Sortino:  {study.best_value:.4f}")
    print(f"  OOS Sortino:      {oos_metrics.get('sortino', 0.0):.4f}")
    print(f"  OOS Return:       {oos_metrics.get('total_return', 0.0):.2f}%")
    print(f"  Best params:      {study.best_params}")
    print(f"  Saved to:         {out_path}")

    return study


def main():
    parser = argparse.ArgumentParser(description="Optuna param optimization")
    parser.add_argument("--symbol", type=str, default=None,
                        help="Symbol to optimize (default: all symbols)")
    parser.add_argument("--n-trials", type=int, default=50,
                        help="Number of Optuna trials per symbol")
    parser.add_argument("--db-path", type=str,
                        default=str(ROOT / "data" / "training.db"),
                        help="Path to training SQLite database")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"ERROR: database not found: {db_path}")
        sys.exit(1)

    if args.symbol:
        symbols = [args.symbol]
    else:
        symbols = get_symbols(db_path)

    print(f"Symbols: {symbols}")
    print(f"Trials:  {args.n_trials}")

    for sym in symbols:
        optimize_symbol(sym, db_path, args.n_trials)

    print("\nOptimization complete.")


if __name__ == "__main__":
    main()
