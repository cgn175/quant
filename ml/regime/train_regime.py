#!/usr/bin/env python3
"""Train Regime Classifier (Traffic Light) per symbol.

A Random Forest that learns WHEN to trade, not WHAT direction.
Replaces the simple ADX > 20 rule with a smarter gate.

Key anti-overfit design:
    - Random Forest (not XGBoost) with shallow trees (max_depth=4)
    - Only 6 features (vs 19 in failed v1)
    - Target = "was this entry profitable?" (1R outcome)
    - class_weight="balanced" (no fragile scale_pos_weight)
    - min_samples_leaf=50 (prevents memorization)

Usage:
    python3 ml/regime/train_regime.py                   # train all symbols
    python3 ml/regime/train_regime.py --symbol BTCUSDT  # train one symbol
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
MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "regime_v1"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

# Rolling window train/test split (last 7 months as test)
def get_train_cutoff():
    """Returns train cutoff as (now - 7 months)."""
    now = pd.Timestamp.now(tz="UTC")
    cutoff = now - pd.DateOffset(months=7)
    return cutoff.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


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


def train_symbol(conn: sqlite3.Connection, symbol: str, model_dir: Path) -> dict:
    print(f"\n{'='*60}")
    print(f"  REGIME CLASSIFIER: {symbol}")
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
        return {}

    entries = entries.dropna(subset=FEATURE_NAMES + ["label"])
    print(f"Total breakout entries: {len(entries):,}")
    print(f"  SAFE_TO_TRADE (1): {int(entries['label'].sum()):,} "
          f"({entries['label'].mean()*100:.1f}%)")
    print(f"  DANGER_ZONE   (0): {int((1 - entries['label']).sum()):,} "
          f"({(1 - entries['label']).mean()*100:.1f}%)")

    # --- Train/test split by time ---
    X = entries[FEATURE_NAMES]
    y = entries["label"]

    train_cutoff = get_train_cutoff()
    print(f"Train cutoff: {train_cutoff.strftime('%Y-%m-%d')}")

    train_mask = entries.index < train_cutoff
    X_train, y_train = X[train_mask], y[train_mask]
    X_test, y_test = X[~train_mask], y[~train_mask]

    if len(X_train) < 30 or len(X_test) < 10:
        print(f"  WARNING: Not enough data for {symbol} "
              f"(train={len(X_train)}, test={len(X_test)})")
        return {}

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

    # Train predictions for overfitting check
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

    # --- Threshold analysis ---
    print(f"\n--- Threshold Analysis (OOS) ---")
    print(f"  {'Thresh':>7s}  {'Prec':>7s}  {'Recall':>7s}  {'F1':>7s}  "
          f"{'Passed':>7s}  {'Pass%':>7s}")
    print(f"  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*7}")

    best_f1 = 0
    best_thresh = 0.5

    for t in [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]:
        yp = (y_proba >= t).astype(int)
        tp = int(((yp == 1) & (y_test == 1)).sum())
        fp = int(((yp == 1) & (y_test == 0)).sum())
        fn = int(((yp == 0) & (y_test == 1)).sum())
        p = tp / max(tp + fp, 1)
        r = tp / max(tp + fn, 1)
        f = 2 * p * r / max(p + r, 1e-9)
        passed = int(yp.sum())
        pass_pct = passed / len(yp) * 100

        if f > best_f1:
            best_f1 = f
            best_thresh = t

        print(f"  {t:>7.2f}  {p:>7.3f}  {r:>7.3f}  {f:>7.3f}  "
              f"{passed:>7d}  {pass_pct:>6.1f}%")

    print(f"\n  Best F1 threshold: {best_thresh:.2f} (F1={best_f1:.3f})")

    # --- Economic analysis ---
    print(f"\n--- Economic Analysis (OOS) ---")
    test_entries = entries[~train_mask].copy()
    test_entries["proba"] = y_proba

    for t in [0.40, 0.50, best_thresh]:
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

        if len(yf_val.unique()) < 2:
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
    model_dir.mkdir(parents=True, exist_ok=True)

    model_path = model_dir / f"{symbol}.pkl"
    joblib.dump(model, str(model_path))

    train_start = entries.index[train_mask].min().strftime("%Y-%m-%d")
    train_end = entries.index[train_mask].max().strftime("%Y-%m-%d")
    test_start = entries.index[~train_mask].min().strftime("%Y-%m-%d")
    test_end = entries.index[~train_mask].max().strftime("%Y-%m-%d")

    meta = {
        "symbol": symbol,
        "feature_version": FEATURE_VERSION,
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
        "suggested_threshold": round(best_thresh, 2),
        "cv_aucs": [round(a, 4) for a in cv_aucs],
        "n_train_entries": int(len(X_train)),
        "n_test_entries": int(len(X_test)),
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }

    meta_path = model_dir / f"{symbol}_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))

    print(f"\nSaved: {model_path}")
    print(f"Saved: {meta_path}")

    return meta


def main():
    parser = argparse.ArgumentParser(
        description="Train Regime Classifier (Traffic Light) models"
    )
    parser.add_argument("--symbol", type=str, default=None, help="Train single symbol")
    parser.add_argument("--model-dir", type=str, default=None, help="Model output directory (default: ml/models/regime_v1)")
    args = parser.parse_args()

    model_dir = Path(args.model_dir) if args.model_dir else MODEL_DIR
    model_dir.mkdir(parents=True, exist_ok=True)

    symbols = [args.symbol] if args.symbol else SYMBOLS

    conn = sqlite3.connect(str(DB_PATH))
    try:
        results = {}
        for sym in symbols:
            meta = train_symbol(conn, sym, model_dir)
            if meta:
                results[sym] = meta

        if results:
            print(f"\n{'='*60}")
            print(f"  SUMMARY — REGIME CLASSIFIER")
            print(f"{'='*60}")
            print(f"  {'Symbol':10s}  {'Train AUC':>10s}  {'Test AUC':>10s}  "
                  f"{'Gap':>8s}  {'Thresh':>7s}  {'F1':>7s}")
            print(f"  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*8}  {'-'*7}  {'-'*7}")
            for sym, meta in results.items():
                m = meta["metrics"]
                print(f"  {sym:10s}  {m['train_auc']:>10.4f}  {m['test_auc']:>10.4f}  "
                      f"{m['auc_gap']:>+8.4f}  {meta['suggested_threshold']:>7.2f}  "
                      f"{m['f1']:>7.3f}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
