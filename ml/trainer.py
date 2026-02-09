#!/usr/bin/env python3
"""Train XGBoost trend-filter models per symbol.

Usage:
    python3 ml/trainer.py                   # train all symbols
    python3 ml/trainer.py --symbol BTCUSDT  # train one symbol
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    classification_report,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from xgboost import XGBClassifier

from features import FEATURE_NAMES, FEATURE_VERSION, build_features

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "training.db"
MODEL_DIR = Path(__file__).resolve().parent / "models"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
TRAIN_CUTOFF = pd.Timestamp("2025-07-01", tz="UTC")
TARGET_HORIZON = 4
TARGET_THRESHOLD = 0.015


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


def load_funding(conn: sqlite3.Connection, symbol: str) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT timestamp, funding_rate FROM funding "
        "WHERE symbol = ? ORDER BY timestamp",
        conn,
        params=(symbol,),
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    return df


def merge_funding(candles: pd.DataFrame, funding: pd.DataFrame) -> pd.DataFrame:
    df = candles.copy()
    funding_reindexed = funding["funding_rate"].reindex(df.index, method="ffill")
    df["funding_rate"] = funding_reindexed
    return df


def make_target(df: pd.DataFrame) -> pd.Series:
    future_ret = df["close"].shift(-TARGET_HORIZON) / df["close"] - 1
    return (future_ret > TARGET_THRESHOLD).astype(int)


def train_symbol(conn: sqlite3.Connection, symbol: str) -> dict:
    print(f"\n{'='*60}")
    print(f"  {symbol}")
    print(f"{'='*60}")

    candles = load_candles(conn, symbol)
    funding = load_funding(conn, symbol)
    df = merge_funding(candles, funding)
    df = build_features(df)

    df["target"] = make_target(df)

    df = df.dropna(subset=FEATURE_NAMES + ["target"])

    X = df[FEATURE_NAMES]
    y = df["target"]

    train_mask = df.index < TRAIN_CUTOFF
    X_train, y_train = X[train_mask], y[train_mask]
    X_test, y_test = X[~train_mask], y[~train_mask]

    print(f"Train: {len(X_train):,} rows  ({y_train.sum():,} positives, "
          f"{y_train.sum()/len(y_train)*100:.1f}%)")
    print(f"Test:  {len(X_test):,} rows  ({y_test.sum():,} positives, "
          f"{y_test.sum()/len(y_test)*100:.1f}%)")

    pos_weight = (len(y_train) - y_train.sum()) / max(y_train.sum(), 1)

    model = XGBClassifier(
        max_depth=6,
        n_estimators=200,
        learning_rate=0.05,
        scale_pos_weight=pos_weight,
        eval_metric="logloss",
        use_label_encoder=False,
        verbosity=0,
        random_state=42,
    )

    model.fit(
        X_train,
        y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    prec = precision_score(y_test, y_pred, zero_division=0)
    rec = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)
    try:
        auc = roc_auc_score(y_test, y_proba)
    except ValueError:
        auc = 0.0

    print(f"\n--- Classification Report ({symbol}) ---")
    print(classification_report(y_test, y_pred, zero_division=0))
    print(f"AUC: {auc:.4f}")

    importances = model.feature_importances_
    sorted_idx = np.argsort(importances)[::-1]
    print(f"\n--- Top 10 Features ({symbol}) ---")
    for i in sorted_idx[:10]:
        print(f"  {FEATURE_NAMES[i]:25s} {importances[i]:.4f}")

    model_path = MODEL_DIR / f"{symbol}.json"
    model.save_model(str(model_path))

    train_start = df.index[train_mask].min().strftime("%Y-%m-%d")
    train_end = df.index[train_mask].max().strftime("%Y-%m-%d")
    test_start = df.index[~train_mask].min().strftime("%Y-%m-%d")
    test_end = df.index[~train_mask].max().strftime("%Y-%m-%d")

    meta = {
        "symbol": symbol,
        "feature_version": FEATURE_VERSION,
        "feature_names": FEATURE_NAMES,
        "training_window": {"start": train_start, "end": train_end},
        "test_window": {"start": test_start, "end": test_end},
        "metrics": {
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "auc": round(auc, 4),
        },
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "threshold": 0.5,
    }

    meta_path = MODEL_DIR / f"{symbol}_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))

    print(f"\nSaved: {model_path}")
    print(f"Saved: {meta_path}")

    return meta


def main():
    parser = argparse.ArgumentParser(description="Train XGBoost trend-filter models")
    parser.add_argument("--symbol", type=str, default=None, help="Train single symbol")
    args = parser.parse_args()

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    symbols = [args.symbol] if args.symbol else SYMBOLS

    conn = sqlite3.connect(str(DB_PATH))
    try:
        results = {}
        for sym in symbols:
            results[sym] = train_symbol(conn, sym)

        print(f"\n{'='*60}")
        print("  SUMMARY")
        print(f"{'='*60}")
        for sym, meta in results.items():
            m = meta["metrics"]
            print(f"  {sym:10s}  P={m['precision']:.3f}  R={m['recall']:.3f}  "
                  f"F1={m['f1']:.3f}  AUC={m['auc']:.3f}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
