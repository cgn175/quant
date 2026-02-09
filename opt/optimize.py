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
    """Return an Optuna objective function closed over the data."""

    sym_key = symbol.replace("USDT", "/USDT")

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

        try:
            signals = generate_signals(ohlcv, funding, params=params)

            signals_dict = {sym_key: signals}
            ohlcv_dict = {sym_key: ohlcv}

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

            if "error" in metrics or metrics.get("num_trades", 0) < 5:
                return float("-inf")

            sortino = metrics.get("sortino", 0.0)
            if np.isnan(sortino) or np.isinf(sortino):
                return 0.0
            return sortino

        except Exception:
            return float("-inf")

    return objective


def save_best_params(symbol: str, study: optuna.Study) -> Path:
    """Write best params to YAML."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    best = study.best_trial

    data = {
        "symbol": symbol,
        "optimized_at": datetime.now(timezone.utc).isoformat(),
        "sortino_ratio": round(best.value, 4),
        "params": {
            "donchian_period": best.params["donchian_period"],
            "ema_fast": best.params["ema_fast"],
            "ema_slow": best.params["ema_slow"],
            "atr_stop_multiplier": best.params["atr_stop_mult"],
            "adx_threshold": best.params["adx_threshold"],
            "chandelier_lookback": best.params["chandelier_lookback"],
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
    print(f"  Loaded {len(ohlcv):,} candles", end="")
    if funding is not None:
        print(f", {len(funding):,} funding records")
    else:
        print(", no funding data")

    storage = f"sqlite:///{OPTUNA_DB}"
    study_name = f"trend_{symbol}"

    study = optuna.create_study(
        study_name=study_name,
        storage=storage,
        direction="maximize",
        load_if_exists=True,
    )

    objective = make_objective(ohlcv, funding, symbol)
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    out_path = save_best_params(symbol, study)

    print(f"\n  Best Sortino: {study.best_value:.4f}")
    print(f"  Best params:  {study.best_params}")
    print(f"  Saved to:     {out_path}")

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
