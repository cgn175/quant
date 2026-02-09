#!/usr/bin/env python3
"""Train and save directional (LONG-only / SHORT-only) Regime Classifier models.

Based on the ML_V2 improvements report finding that SOL LONG-only model
reaches 0.809 AUC (vs 0.757 combined), this script trains direction-specific
regime models and saves them for deployment.

Key design decisions:
    - Uses v1 features (6 features) — v2 hurts SOL per report
    - Only trains for symbols with sufficient directional data
    - Saves to regime_v1_long/ or regime_v1_short/ subdirectories

Usage:
    python3 ml/regime/train_regime_directional_save.py                          # SOL LONG (default)
    python3 ml/regime/train_regime_directional_save.py --symbol SOLUSDT --direction LONG
    python3 ml/regime/train_regime_directional_save.py --symbol ETHUSDT --direction SHORT
    python3 ml/regime/train_regime_directional_save.py --all                    # train all viable combos
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
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    classification_report,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import TimeSeriesSplit

# Allow imports from parent ml/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from regime.features_regime_v1 import FEATURE_NAMES, FEATURE_VERSION, build_regime_features
from regime.label_regime import label_entries

try:
    import joblib
except ImportError:
    from sklearn.externals import joblib  # type: ignore

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "training.db"
MODELS_BASE = Path(__file__).resolve().parent.parent / "models"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
TRAIN_CUTOFF = pd.Timestamp("2025-07-01", tz="UTC")

# Minimum samples required for training/testing
MIN_TRAIN = 30
MIN_TEST = 10


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


def train_directional(conn: sqlite3.Connection, symbol: str, direction: str) -> dict | None:
    """Train a directional regime model and save it."""
    direction = direction.upper()
    assert direction in ("LONG", "SHORT"), f"Invalid direction: {direction}"

    print(f"\n{'='*60}")
    print(f"  DIRECTIONAL REGIME: {symbol} {direction}-only")
    print(f"{'='*60}")

    # --- Load & prepare data ---
    candles = load_candles(conn, symbol)
    funding = load_funding(conn, symbol)
    df = merge_funding(candles, funding)
    df = build_regime_features(df)

    print(f"Total candles: {len(df):,}")

    # --- Label entries ---
    entries = label_entries(df)
    if entries.empty:
        print(f"  WARNING: No breakout entries found for {symbol}")
        return None

    entries = entries.dropna(subset=FEATURE_NAMES + ["label"])

    # --- Filter to direction ---
    dir_entries = entries[entries["side"] == direction]
    print(f"Total {direction} entries: {len(dir_entries):,} "
          f"(out of {len(entries):,} total)")
    print(f"  SAFE_TO_TRADE (1): {int(dir_entries['label'].sum()):,} "
          f"({dir_entries['label'].mean()*100:.1f}%)")
    print(f"  DANGER_ZONE   (0): {int((1 - dir_entries['label']).sum()):,} "
          f"({(1 - dir_entries['label']).mean()*100:.1f}%)")

    # --- Train/test split by time ---
    X = dir_entries[FEATURE_NAMES]
    y = dir_entries["label"]

    train_mask = dir_entries.index < TRAIN_CUTOFF
    X_train, y_train = X[train_mask], y[train_mask]
    X_test, y_test = X[~train_mask], y[~train_mask]

    if len(X_train) < MIN_TRAIN:
        print(f"  SKIPPED: Not enough training data ({len(X_train)} < {MIN_TRAIN})")
        return None
    if len(X_test) < MIN_TEST:
        print(f"  SKIPPED: Not enough test data ({len(X_test)} < {MIN_TEST})")
        return None
    if len(y_train.unique()) < 2:
        print(f"  SKIPPED: Only one class in training data")
        return None

    print(f"\nTrain: {len(X_train):,} entries  "
          f"({y_train.sum():.0f} SAFE, {len(y_train)-y_train.sum():.0f} DANGER)")
    print(f"Test:  {len(X_test):,} entries  "
          f"({y_test.sum():.0f} SAFE, {len(y_test)-y_test.sum():.0f} DANGER)")

    # --- Train Random Forest ---
    model = RandomForestClassifier(
        max_depth=4,
        min_samples_leaf=50,
        n_estimators=200,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    # --- Evaluate ---
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]
    y_train_proba = model.predict_proba(X_train)[:, 1]

    try:
        train_auc = roc_auc_score(y_train, y_train_proba)
    except ValueError:
        train_auc = 0.0
    try:
        test_auc = roc_auc_score(y_test, y_proba)
    except ValueError:
        test_auc = 0.0

    auc_gap = train_auc - test_auc
    prec = precision_score(y_test, y_pred, zero_division=0)
    rec = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)

    print(f"\n--- Overfitting Check ---")
    print(f"  Train AUC: {train_auc:.4f}")
    print(f"  Test AUC:  {test_auc:.4f}")
    print(f"  AUC Gap:   {auc_gap:+.4f}  "
          f"{'⚠️ OVERFIT' if auc_gap > 0.15 else '🟡 Mild' if auc_gap > 0.08 else '✅ OK'}")

    print(f"\n--- Classification Report (OOS) ---")
    print(classification_report(y_test, y_pred, zero_division=0,
                                target_names=["DANGER", "SAFE"]))
    print(f"Test AUC: {test_auc:.4f}")

    # --- Feature importance ---
    importances = model.feature_importances_
    sorted_idx = np.argsort(importances)[::-1]
    print(f"\n--- Feature Importance ---")
    for i in sorted_idx:
        bar = "█" * int(importances[i] * 50)
        print(f"  {FEATURE_NAMES[i]:20s}  {importances[i]:.4f}  {bar}")

    # --- Economic analysis ---
    print(f"\n--- Economic Analysis (OOS) ---")
    test_entries = dir_entries[~train_mask].copy()
    test_entries["proba"] = y_proba

    for t in [0.40, 0.50, 0.55]:
        safe_mask = test_entries["proba"] >= t
        danger_mask = test_entries["proba"] < t

        safe_entries = test_entries[safe_mask]
        danger_entries = test_entries[danger_mask]

        safe_win_rate = safe_entries["label"].mean() * 100 if len(safe_entries) > 0 else 0
        danger_win_rate = danger_entries["label"].mean() * 100 if len(danger_entries) > 0 else 0

        print(f"  Threshold {t:.2f}:")
        print(f"    SAFE trades:   {len(safe_entries):>4d}  "
              f"win rate: {safe_win_rate:.1f}%")
        print(f"    DANGER trades: {len(danger_entries):>4d}  "
              f"win rate: {danger_win_rate:.1f}%")
        if safe_win_rate > 0 and danger_win_rate > 0:
            print(f"    Edge: +{safe_win_rate - danger_win_rate:.1f}pp")

    # --- Cross-validation (TimeSeriesSplit) ---
    print(f"\n--- Time-Series Cross-Validation ---")
    tscv = TimeSeriesSplit(n_splits=5)
    cv_aucs = []

    for fold, (train_idx, val_idx) in enumerate(tscv.split(X_train), 1):
        Xf_tr, Xf_val = X_train.iloc[train_idx], X_train.iloc[val_idx]
        yf_tr, yf_val = y_train.iloc[train_idx], y_train.iloc[val_idx]

        if len(yf_val.unique()) < 2 or len(yf_tr.unique()) < 2:
            continue

        cv_model = RandomForestClassifier(
            max_depth=4,
            min_samples_leaf=50,
            n_estimators=200,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )
        cv_model.fit(Xf_tr, yf_tr)
        cv_proba = cv_model.predict_proba(Xf_val)[:, 1]

        try:
            cv_auc = roc_auc_score(yf_val, cv_proba)
            cv_aucs.append(cv_auc)
            print(f"  Fold {fold}: AUC = {cv_auc:.4f}")
        except ValueError:
            print(f"  Fold {fold}: AUC = N/A (single class)")

    if cv_aucs:
        print(f"  Mean CV AUC: {np.mean(cv_aucs):.4f} ± {np.std(cv_aucs):.4f}")

    # --- Save model ---
    dir_suffix = direction.lower()
    feature_ver = f"{FEATURE_VERSION}_{dir_suffix}"
    model_dir = MODELS_BASE / f"regime_v1_{dir_suffix}"
    model_dir.mkdir(parents=True, exist_ok=True)

    model_path = model_dir / f"{symbol}.pkl"
    joblib.dump(model, str(model_path))

    train_start = dir_entries.index[train_mask].min().strftime("%Y-%m-%d")
    train_end = dir_entries.index[train_mask].max().strftime("%Y-%m-%d")
    test_start = dir_entries.index[~train_mask].min().strftime("%Y-%m-%d")
    test_end = dir_entries.index[~train_mask].max().strftime("%Y-%m-%d")

    meta = {
        "symbol": symbol,
        "direction": direction,
        "feature_version": feature_ver,
        "feature_names": FEATURE_NAMES,
        "model_type": "RandomForestClassifier",
        "model_params": {
            "max_depth": 4,
            "min_samples_leaf": 50,
            "n_estimators": 200,
            "class_weight": "balanced",
        },
        "training_window": {"start": train_start, "end": train_end},
        "test_window": {"start": test_start, "end": test_end},
        "metrics": {
            "train_auc": round(train_auc, 4),
            "test_auc": round(test_auc, 4),
            "auc_gap": round(auc_gap, 4),
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
        },
        "suggested_threshold": 0.50,
        "cv_aucs": [round(a, 4) for a in cv_aucs],
        "n_train_entries": int(len(X_train)),
        "n_test_entries": int(len(X_test)),
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }

    meta_path = model_dir / f"{symbol}_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))

    print(f"\n✅ Saved: {model_path}")
    print(f"✅ Saved: {meta_path}")

    return meta


def main():
    parser = argparse.ArgumentParser(
        description="Train and save directional Regime Classifier models"
    )
    parser.add_argument("--symbol", type=str, default="SOLUSDT",
                        help="Symbol to train (default: SOLUSDT)")
    parser.add_argument("--direction", type=str, default="LONG",
                        help="Direction: LONG or SHORT (default: LONG)")
    parser.add_argument("--all", action="store_true",
                        help="Train all viable symbol+direction combos")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    try:
        if args.all:
            # Train all viable combinations
            results = {}
            for sym in SYMBOLS:
                for direction in ["LONG", "SHORT"]:
                    meta = train_directional(conn, sym, direction)
                    if meta:
                        results[f"{sym}_{direction}"] = meta

            if results:
                print(f"\n{'='*60}")
                print(f"  SUMMARY — DIRECTIONAL REGIME MODELS")
                print(f"{'='*60}")
                print(f"  {'Symbol':10s}  {'Dir':>5s}  {'Train AUC':>10s}  "
                      f"{'Test AUC':>10s}  {'Gap':>8s}")
                print(f"  {'-'*10}  {'-'*5}  {'-'*10}  {'-'*10}  {'-'*8}")
                for key, meta in results.items():
                    m = meta["metrics"]
                    print(f"  {meta['symbol']:10s}  {meta['direction']:>5s}  "
                          f"{m['train_auc']:>10.4f}  {m['test_auc']:>10.4f}  "
                          f"{m['auc_gap']:>+8.4f}")
        else:
            # Train single symbol+direction
            meta = train_directional(conn, args.symbol, args.direction)
            if meta is None:
                print(f"\n❌ Failed to train {args.symbol} {args.direction}")
                sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
