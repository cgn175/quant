#!/usr/bin/env python3
"""Train Volatility Predictor (Dynamic Stop-Loss) per symbol.

Predicts the next 4H candle's high-low range as a percentage of current close.
The bot uses this to set dynamic stop-losses:
    - High predicted volatility → wider stops (e.g., 4%)
    - Low predicted volatility → tighter stops (e.g., 1%)

Key anti-overfit design:
    - HuberRegressor (robust to outliers, linear, won't overfit)
    - Ridge as comparison baseline
    - Only 6 features
    - Trains on log(range) to handle right-skewed distribution

Usage:
    python3 ml/volatility/train_volatility.py
    python3 ml/volatility/train_volatility.py --symbol BTCUSDT
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

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "training.db"
MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "vol_v1"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
TRAIN_CUTOFF = pd.Timestamp("2025-07-01", tz="UTC")

# Small constant to avoid log(0)
LOG_EPS = 1e-8


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


def make_target(df: pd.DataFrame) -> pd.Series:
    """Target: next candle's range as % of current close.

    y = (high[t+1] - low[t+1]) / close[t]
    No lookahead in denominator (uses close[t]).
    """
    next_range = df["high"].shift(-1) - df["low"].shift(-1)
    return next_range / df["close"]


def predict_range(model, features: np.ndarray) -> np.ndarray:
    """Predict range, handling the log transform back.

    The model was trained on log(y + eps), so we exponentiate.
    """
    log_pred = model.predict(features)
    return np.exp(log_pred) - LOG_EPS


def train_symbol(conn: sqlite3.Connection, symbol: str) -> dict:
    print(f"\n{'='*60}")
    print(f"  VOLATILITY PREDICTOR: {symbol}")
    print(f"{'='*60}")

    # --- Load & prepare data ---
    candles = load_candles(conn, symbol)
    df = build_vol_features(candles)

    # Create target
    df["target_range_pct"] = make_target(df)

    # Drop rows with NaN features or target
    df = df.dropna(subset=FEATURE_NAMES + ["target_range_pct"])

    # Remove any rows where target is zero or negative (shouldn't happen but safety)
    df = df[df["target_range_pct"] > 0]

    print(f"Total rows: {len(df):,}")

    # --- Train/test split by time ---
    X = df[FEATURE_NAMES]
    y_raw = df["target_range_pct"]

    # Train on log(y) to handle right-skewed distribution
    y_log = np.log(y_raw + LOG_EPS)

    train_mask = df.index < TRAIN_CUTOFF
    X_train, y_train_log = X[train_mask], y_log[train_mask]
    X_test, y_test_log = X[~train_mask], y_log[~train_mask]
    y_train_raw, y_test_raw = y_raw[train_mask], y_raw[~train_mask]

    print(f"Train: {len(X_train):,} rows")
    print(f"Test:  {len(X_test):,} rows")

    # --- Target distribution ---
    print(f"\n--- Target Distribution (range %) ---")
    print(f"  Train: mean={y_train_raw.mean()*100:.3f}%  "
          f"median={y_train_raw.median()*100:.3f}%  "
          f"std={y_train_raw.std()*100:.3f}%")
    print(f"  Test:  mean={y_test_raw.mean()*100:.3f}%  "
          f"median={y_test_raw.median()*100:.3f}%  "
          f"std={y_test_raw.std()*100:.3f}%")
    print(f"  Train P95: {np.percentile(y_train_raw, 95)*100:.3f}%")
    print(f"  Test  P95: {np.percentile(y_test_raw, 95)*100:.3f}%")

    # --- Train both models ---
    models = {}

    # Huber Regressor (robust to outliers)
    huber = HuberRegressor(max_iter=500)
    huber.fit(X_train, y_train_log)
    models["huber"] = huber

    # Ridge (L2 regularization)
    ridge = Ridge(alpha=1.0)
    ridge.fit(X_train, y_train_log)
    models["ridge"] = ridge

    # --- Evaluate both ---
    best_model_name = None
    best_mae = float("inf")
    model_metrics = {}

    for name, model in models.items():
        # Predictions (transform back from log space)
        train_pred = predict_range(model, X_train)
        test_pred = predict_range(model, X_test)

        # Metrics
        train_mae = mean_absolute_error(y_train_raw, train_pred)
        test_mae = mean_absolute_error(y_test_raw, test_pred)
        test_rmse = np.sqrt(mean_squared_error(y_test_raw, test_pred))
        test_r2 = r2_score(y_test_raw, test_pred)
        test_med_ae = median_absolute_error(y_test_raw, test_pred)

        print(f"\n--- {name.upper()} Results ---")
        print(f"  Train MAE: {train_mae*100:.4f}%")
        print(f"  Test  MAE: {test_mae*100:.4f}%")
        print(f"  Test RMSE: {test_rmse*100:.4f}%")
        print(f"  Test  R²:  {test_r2:.4f}")
        print(f"  Test MedAE: {test_med_ae*100:.4f}%")
        print(f"  Overfit gap (MAE): {(test_mae - train_mae)*100:+.4f}%  "
              f"{'⚠️' if (test_mae - train_mae) / max(train_mae, 1e-8) > 0.5 else '✅'}")

        model_metrics[name] = {
            "train_mae": round(train_mae, 6),
            "test_mae": round(test_mae, 6),
            "test_rmse": round(test_rmse, 6),
            "test_r2": round(test_r2, 4),
            "test_med_ae": round(test_med_ae, 6),
        }

        if test_mae < best_mae:
            best_mae = test_mae
            best_model_name = name

    print(f"\n  → Best model: {best_model_name.upper()} (Test MAE: {best_mae*100:.4f}%)")

    best_model = models[best_model_name]

    # --- Calibration: predicted vs actual by quintile ---
    print(f"\n--- Calibration (Quintile Bins, OOS) ---")
    test_pred = predict_range(best_model, X_test)

    # Create quintile bins
    try:
        bins = pd.qcut(test_pred, q=5, duplicates="drop")
        cal_df = pd.DataFrame({
            "predicted": test_pred,
            "actual": y_test_raw.values,
            "bin": bins,
        })
        cal_summary = cal_df.groupby("bin", observed=False).agg(
            pred_mean=("predicted", "mean"),
            actual_mean=("actual", "mean"),
            count=("predicted", "count"),
        )
        print(f"  {'Bin':>30s}  {'Pred Mean':>10s}  {'Actual Mean':>12s}  {'Count':>6s}")
        print(f"  {'-'*30}  {'-'*10}  {'-'*12}  {'-'*6}")
        for idx, row in cal_summary.iterrows():
            print(f"  {str(idx):>30s}  {row['pred_mean']*100:>9.3f}%  "
                  f"{row['actual_mean']*100:>11.3f}%  {int(row['count']):>6d}")
    except ValueError as e:
        print(f"  (Could not create quintile bins: {e})")

    # --- Prediction distribution ---
    print(f"\n--- Prediction Distribution (OOS) ---")
    print(f"  Predicted: mean={np.mean(test_pred)*100:.3f}%  "
          f"std={np.std(test_pred)*100:.3f}%  "
          f"min={np.min(test_pred)*100:.3f}%  "
          f"max={np.max(test_pred)*100:.3f}%")
    print(f"  Actual:    mean={y_test_raw.mean()*100:.3f}%  "
          f"std={y_test_raw.std()*100:.3f}%  "
          f"min={y_test_raw.min()*100:.3f}%  "
          f"max={y_test_raw.max()*100:.3f}%")

    # --- Feature coefficients ---
    if best_model_name == "ridge":
        coefs = best_model.coef_
    else:
        coefs = best_model.coef_

    print(f"\n--- Feature Coefficients ({best_model_name.upper()}) ---")
    for name_f, coef in zip(FEATURE_NAMES, coefs):
        bar = "█" * int(abs(coef) * 20)
        sign = "+" if coef >= 0 else "-"
        print(f"  {name_f:20s}  {sign}{abs(coef):.4f}  {bar}")

    # --- Save best model ---
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    model_path = MODEL_DIR / f"{symbol}.pkl"
    joblib.dump(best_model, str(model_path))

    train_start = df.index[train_mask].min().strftime("%Y-%m-%d")
    train_end = df.index[train_mask].max().strftime("%Y-%m-%d")
    test_start = df.index[~train_mask].min().strftime("%Y-%m-%d")
    test_end = df.index[~train_mask].max().strftime("%Y-%m-%d")

    meta = {
        "symbol": symbol,
        "feature_version": FEATURE_VERSION,
        "feature_names": FEATURE_NAMES,
        "model_type": best_model_name,
        "log_transform": True,
        "log_eps": LOG_EPS,
        "training_window": {"start": train_start, "end": train_end},
        "test_window": {"start": test_start, "end": test_end},
        "metrics": model_metrics[best_model_name],
        "all_model_metrics": model_metrics,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }

    meta_path = MODEL_DIR / f"{symbol}_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))

    print(f"\nSaved: {model_path}")
    print(f"Saved: {meta_path}")

    return meta


def main():
    parser = argparse.ArgumentParser(
        description="Train Volatility Predictor (Dynamic Stop-Loss) models"
    )
    parser.add_argument("--symbol", type=str, default=None, help="Train single symbol")
    args = parser.parse_args()

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    symbols = [args.symbol] if args.symbol else SYMBOLS

    conn = sqlite3.connect(str(DB_PATH))
    try:
        results = {}
        for sym in symbols:
            meta = train_symbol(conn, sym)
            if meta:
                results[sym] = meta

        if results:
            print(f"\n{'='*60}")
            print(f"  SUMMARY — VOLATILITY PREDICTOR")
            print(f"{'='*60}")
            print(f"  {'Symbol':10s}  {'Model':>8s}  {'Train MAE':>10s}  "
                  f"{'Test MAE':>10s}  {'R²':>7s}")
            print(f"  {'-'*10}  {'-'*8}  {'-'*10}  {'-'*10}  {'-'*7}")
            for sym, meta in results.items():
                m = meta["metrics"]
                print(f"  {sym:10s}  {meta['model_type']:>8s}  "
                      f"{m['train_mae']*100:>9.4f}%  "
                      f"{m['test_mae']*100:>9.4f}%  "
                      f"{m['test_r2']:>7.4f}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
