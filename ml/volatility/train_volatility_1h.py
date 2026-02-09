#!/usr/bin/env python3
"""Train Volatility Predictor with 1H-derived targets + pooled multi-symbol model.

Improvements over train_volatility.py:
  1. Uses 1H candles to construct more accurate next-4H-range targets
     (max/min of 4 constituent 1H candles vs single 4H candle high/low)
  2. Trains a pooled model across all symbols with symbol one-hot encoding

Usage:
    python3 ml/volatility/train_volatility_1h.py
    python3 ml/volatility/train_volatility_1h.py --symbol BTCUSDT
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import HuberRegressor, Ridge
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    median_absolute_error,
    r2_score,
)

# Allow imports from parent ml/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from volatility.features_vol_v1 import FEATURE_NAMES, FEATURE_VERSION, build_vol_features

try:
    import joblib
except ImportError:
    from sklearn.externals import joblib  # type: ignore

DB_4H_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "training.db"
DB_1H_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "training_1h.db"
MODEL_DIR_PERSYM = Path(__file__).resolve().parent.parent / "models" / "vol_v1_1h"
MODEL_DIR_POOLED = Path(__file__).resolve().parent.parent / "models" / "vol_v1_pooled"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
TRAIN_CUTOFF = pd.Timestamp("2025-07-01", tz="UTC")

LOG_EPS = 1e-8

SYMBOL_FEATURES = [f"is_{s}" for s in SYMBOLS]
POOLED_FEATURE_NAMES = FEATURE_NAMES + SYMBOL_FEATURES


def load_candles(conn: sqlite3.Connection, symbol: str) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT open_time, open, high, low, close, volume FROM candles "
        "WHERE symbol = ? AND is_closed = 1 ORDER BY open_time",
        conn,
        params=(symbol,),
    )
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("timestamp").drop(columns=["open_time"])
    return df


def make_target_from_1h(df_4h: pd.DataFrame, df_1h: pd.DataFrame) -> pd.Series:
    """Compute next-4H-bar range using 1H candles for accuracy.

    For each 4H bar at time T, find the 4 one-hour candles in [T+4h, T+8h)
    and compute: range = (max(highs) - min(lows)) / close[T]
    """
    targets = pd.Series(index=df_4h.index, dtype=float)
    h1_sorted = df_1h.sort_index()

    for i in range(len(df_4h) - 1):
        t = df_4h.index[i]
        close_t = df_4h["close"].iloc[i]
        if close_t <= 0:
            continue

        # Next 4H window: [T+4h, T+8h)
        start = t + pd.Timedelta(hours=4)
        end = t + pd.Timedelta(hours=8)
        mask = (h1_sorted.index >= start) & (h1_sorted.index < end)
        window = h1_sorted[mask]

        if len(window) >= 2:  # need at least 2 of 4 expected 1H candles
            next_high = window["high"].max()
            next_low = window["low"].min()
            targets.iloc[i] = (next_high - next_low) / close_t

    return targets


def make_target_4h(df: pd.DataFrame) -> pd.Series:
    """Original 4H target for comparison."""
    next_range = df["high"].shift(-1) - df["low"].shift(-1)
    return next_range / df["close"]


def add_symbol_onehot(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    for s in SYMBOLS:
        df[f"is_{s}"] = 1.0 if s == symbol else 0.0
    return df


def predict_range(model, features: np.ndarray) -> np.ndarray:
    log_pred = model.predict(features)
    return np.exp(log_pred) - LOG_EPS


def train_persymbol(conn_4h, conn_1h, symbol):
    """Train per-symbol vol model with 1H-derived targets."""
    print(f"\n{'='*60}")
    print(f"  VOL PREDICTOR (1H targets): {symbol}")
    print(f"{'='*60}")

    candles_4h = load_candles(conn_4h, symbol)
    candles_1h = load_candles(conn_1h, symbol)
    df = build_vol_features(candles_4h)

    print(f"4H candles: {len(df):,}  |  1H candles: {len(candles_1h):,}")

    # Build targets
    df["target_1h"] = make_target_from_1h(df, candles_1h)
    df["target_4h"] = make_target_4h(candles_4h.reindex(df.index))

    # Compare targets
    valid_both = df.dropna(subset=["target_1h", "target_4h"])
    if len(valid_both) > 0:
        corr = valid_both["target_1h"].corr(valid_both["target_4h"])
        diff = (valid_both["target_1h"] - valid_both["target_4h"]).abs()
        print(f"\n  Target comparison ({len(valid_both):,} rows):")
        print(f"    Correlation: {corr:.4f}")
        print(f"    Mean abs diff: {diff.mean()*100:.4f}%")
        print(f"    1H mean: {valid_both['target_1h'].mean()*100:.4f}%  "
              f"4H mean: {valid_both['target_4h'].mean()*100:.4f}%")

    # Use 1H target
    df["target_range_pct"] = df["target_1h"]
    df = df.dropna(subset=FEATURE_NAMES + ["target_range_pct"])
    df = df[df["target_range_pct"] > 0]

    # Train/test split
    X = df[FEATURE_NAMES]
    y_raw = df["target_range_pct"]
    y_log = np.log(y_raw + LOG_EPS)

    train_mask = df.index < TRAIN_CUTOFF
    X_train, y_train_log = X[train_mask], y_log[train_mask]
    X_test, y_test_log = X[~train_mask], y_log[~train_mask]
    y_train_raw, y_test_raw = y_raw[train_mask], y_raw[~train_mask]

    print(f"Train: {len(X_train):,}  |  Test: {len(X_test):,}")

    # Train Huber
    model = HuberRegressor(max_iter=500)
    model.fit(X_train, y_train_log)

    # Evaluate
    train_pred = predict_range(model, X_train)
    test_pred = predict_range(model, X_test)

    train_mae = mean_absolute_error(y_train_raw, train_pred)
    test_mae = mean_absolute_error(y_test_raw, test_pred)
    test_r2 = r2_score(y_test_raw, test_pred)

    print(f"\n  Train MAE: {train_mae*100:.4f}%")
    print(f"  Test  MAE: {test_mae*100:.4f}%")
    print(f"  Test  R²:  {test_r2:.4f}")
    print(f"  MAE Ratio: {test_mae/max(train_mae, 1e-8):.2f}x  "
          f"{'✅ No overfit' if test_mae <= train_mae * 1.2 else '⚠️'}")

    # Save
    MODEL_DIR_PERSYM.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_DIR_PERSYM / f"{symbol}.pkl"
    joblib.dump(model, str(model_path))

    meta = {
        "symbol": symbol,
        "feature_version": FEATURE_VERSION,
        "feature_names": FEATURE_NAMES,
        "model_type": "huber",
        "log_transform": True,
        "log_eps": LOG_EPS,
        "target_source": "1h_intrabar",
        "metrics": {
            "train_mae": round(train_mae, 6),
            "test_mae": round(test_mae, 6),
            "test_r2": round(test_r2, 4),
        },
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = MODEL_DIR_PERSYM / f"{symbol}_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"  Saved: {model_path}")

    return df, meta


def train_pooled(all_data: dict[str, pd.DataFrame]):
    """Train pooled volatility model across all symbols."""
    print(f"\n{'='*60}")
    print(f"  POOLED VOL MODEL (all symbols)")
    print(f"{'='*60}")

    dfs = []
    for symbol, df in all_data.items():
        d = df.copy()
        d = add_symbol_onehot(d, symbol)
        d["_symbol"] = symbol
        dfs.append(d)

    pooled = pd.concat(dfs, axis=0).sort_index()
    pooled = pooled.dropna(subset=POOLED_FEATURE_NAMES + ["target_range_pct"])
    pooled = pooled[pooled["target_range_pct"] > 0]

    print(f"\nTotal pooled rows: {len(pooled):,}")

    X = pooled[POOLED_FEATURE_NAMES]
    y_raw = pooled["target_range_pct"]
    y_log = np.log(y_raw + LOG_EPS)

    train_mask = pooled.index < TRAIN_CUTOFF
    X_train, y_train_log = X[train_mask], y_log[train_mask]
    X_test, y_test_log = X[~train_mask], y_log[~train_mask]
    y_train_raw, y_test_raw = y_raw[train_mask], y_raw[~train_mask]

    print(f"Train: {len(X_train):,}  |  Test: {len(X_test):,}")

    # Train Huber
    model = HuberRegressor(max_iter=500)
    model.fit(X_train, y_train_log)

    # Overall metrics
    train_pred = predict_range(model, X_train)
    test_pred = predict_range(model, X_test)

    train_mae = mean_absolute_error(y_train_raw, train_pred)
    test_mae = mean_absolute_error(y_test_raw, test_pred)
    test_r2 = r2_score(y_test_raw, test_pred)

    print(f"\n--- Overall Pooled Results ---")
    print(f"  Train MAE: {train_mae*100:.4f}%")
    print(f"  Test  MAE: {test_mae*100:.4f}%")
    print(f"  Test  R²:  {test_r2:.4f}")

    # Per-symbol metrics
    print(f"\n--- Per-Symbol MAE (Pooled Model) ---")
    print(f"  {'Symbol':10s}  {'Test MAE':>10s}  {'Test R²':>8s}  {'N':>6s}")
    print(f"  {'-'*10}  {'-'*10}  {'-'*8}  {'-'*6}")

    per_symbol_metrics = {}
    test_pooled = pooled[~train_mask]
    for sym in SYMBOLS:
        sym_mask = test_pooled["_symbol"] == sym
        if sym_mask.sum() < 5:
            continue
        sym_y = y_test_raw[sym_mask.values]
        sym_pred = test_pred[sym_mask.values]
        sym_mae = mean_absolute_error(sym_y, sym_pred)
        sym_r2 = r2_score(sym_y, sym_pred)
        per_symbol_metrics[sym] = {"test_mae": round(sym_mae, 6), "test_r2": round(sym_r2, 4)}
        print(f"  {sym:10s}  {sym_mae*100:>9.4f}%  {sym_r2:>8.4f}  {int(sym_mask.sum()):>6d}")

    # Feature coefficients
    print(f"\n--- Feature Coefficients (Pooled Huber) ---")
    for name_f, coef in zip(POOLED_FEATURE_NAMES, model.coef_):
        bar = "█" * int(abs(coef) * 20)
        sign = "+" if coef >= 0 else "-"
        print(f"  {name_f:20s}  {sign}{abs(coef):.4f}  {bar}")

    # Save
    MODEL_DIR_POOLED.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_DIR_POOLED / "pooled.pkl"
    joblib.dump(model, str(model_path))

    meta = {
        "model_type": "pooled_huber",
        "symbols": SYMBOLS,
        "feature_version": FEATURE_VERSION,
        "feature_names": POOLED_FEATURE_NAMES,
        "pooled_feature_names": FEATURE_NAMES,
        "symbol_features": SYMBOL_FEATURES,
        "log_transform": True,
        "log_eps": LOG_EPS,
        "target_source": "1h_intrabar",
        "metrics": {
            "train_mae": round(train_mae, 6),
            "test_mae": round(test_mae, 6),
            "test_r2": round(test_r2, 4),
        },
        "per_symbol_metrics": per_symbol_metrics,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = MODEL_DIR_POOLED / "pooled_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"\nSaved: {model_path}")
    print(f"Saved: {meta_path}")

    return meta


def main():
    parser = argparse.ArgumentParser(
        description="Train Volatility Predictor with 1H targets + pooled model"
    )
    parser.add_argument("--symbol", type=str, default=None,
                        help="Train single symbol (per-symbol only, no pooled)")
    args = parser.parse_args()

    symbols = [args.symbol] if args.symbol else SYMBOLS

    conn_4h = sqlite3.connect(str(DB_4H_PATH))
    conn_1h = sqlite3.connect(str(DB_1H_PATH))

    try:
        all_data = {}
        per_symbol_results = {}

        for sym in symbols:
            df, meta = train_persymbol(conn_4h, conn_1h, sym)
            if df is not None and meta is not None:
                all_data[sym] = df
                per_symbol_results[sym] = meta

        pooled_meta = None
        if len(all_data) >= 2 and args.symbol is None:
            pooled_meta = train_pooled(all_data)

        # Summary
        print(f"\n{'='*60}")
        print(f"  FINAL SUMMARY")
        print(f"{'='*60}")

        if per_symbol_results:
            print(f"\n  Per-Symbol (1H targets):")
            print(f"  {'Symbol':10s}  {'Train MAE':>10s}  {'Test MAE':>10s}  {'R²':>7s}")
            print(f"  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*7}")
            for sym, meta in per_symbol_results.items():
                m = meta["metrics"]
                print(f"  {sym:10s}  {m['train_mae']*100:>9.4f}%  "
                      f"{m['test_mae']*100:>9.4f}%  {m['test_r2']:>7.4f}")

        if pooled_meta:
            pm = pooled_meta["metrics"]
            print(f"\n  Pooled Model:")
            print(f"    Overall — Train MAE: {pm['train_mae']*100:.4f}%  "
                  f"Test MAE: {pm['test_mae']*100:.4f}%  R²: {pm['test_r2']:.4f}")

    finally:
        conn_4h.close()
        conn_1h.close()


if __name__ == "__main__":
    main()
