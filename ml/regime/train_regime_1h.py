#!/usr/bin/env python3
"""Train Regime Classifier with 1H intrabar labels + pooled multi-symbol model.

Two improvements over train_regime.py:
  1. Uses 1H candles for more accurate stop/target hit evaluation (label_regime_1h)
  2. Trains a pooled model across all symbols (4x more entries) with symbol one-hot

Usage:
    python3 ml/regime/train_regime_1h.py
    python3 ml/regime/train_regime_1h.py --symbol BTCUSDT  # per-symbol only
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

# Allow imports from parent ml/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from regime.features_regime_v1 import FEATURE_NAMES, FEATURE_VERSION, build_regime_features
from regime.label_regime import label_entries
from regime.label_regime_1h import label_entries_1h

try:
    import joblib
except ImportError:
    from sklearn.externals import joblib  # type: ignore

DB_4H_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "training.db"
DB_1H_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "training_1h.db"
MODEL_DIR_PERSYM = Path(__file__).resolve().parent.parent / "models" / "regime_v1_1h"
MODEL_DIR_POOLED = Path(__file__).resolve().parent.parent / "models" / "regime_v1_pooled"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
TRAIN_CUTOFF = pd.Timestamp("2025-07-01", tz="UTC")

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


def add_symbol_onehot(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Add one-hot symbol indicator columns."""
    for s in SYMBOLS:
        df[f"is_{s}"] = 1.0 if s == symbol else 0.0
    return df


def evaluate_model(model, X_test, y_test, feature_names, label=""):
    """Run standard evaluation and return metrics dict."""
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    try:
        test_auc = roc_auc_score(y_test, y_proba)
    except ValueError:
        test_auc = 0.0

    prec = precision_score(y_test, y_pred, zero_division=0)
    rec = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)

    return {
        "test_auc": round(test_auc, 4),
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "f1": round(f1, 4),
        "y_proba": y_proba,
    }


def print_economic_edge(entries_df, y_proba, label=""):
    """Print SAFE vs DANGER win rates at various thresholds."""
    df = entries_df.copy()
    df["proba"] = y_proba

    print(f"\n--- Economic Edge ({label}) ---")
    for t in [0.40, 0.45, 0.50, 0.55]:
        safe = df[df["proba"] >= t]
        danger = df[df["proba"] < t]
        safe_wr = safe["label"].mean() * 100 if len(safe) > 0 else 0
        danger_wr = danger["label"].mean() * 100 if len(danger) > 0 else 0
        edge = safe_wr - danger_wr
        pass_pct = len(safe) / len(df) * 100 if len(df) > 0 else 0
        print(f"  Thresh {t:.2f}: SAFE {len(safe):>4d} ({safe_wr:.1f}%) | "
              f"DANGER {len(danger):>4d} ({danger_wr:.1f}%) | "
              f"Edge: {edge:+.1f}pp | Pass: {pass_pct:.0f}%")


def train_persymbol(conn_4h, conn_1h, symbol):
    """Train per-symbol model with 1H intrabar labels."""
    print(f"\n{'='*60}")
    print(f"  PER-SYMBOL (1H labels): {symbol}")
    print(f"{'='*60}")

    # Load 4H data + features
    candles_4h = load_candles(conn_4h, symbol)
    funding = load_funding(conn_4h, symbol)
    df_4h = merge_funding(candles_4h, funding)
    df_4h = build_regime_features(df_4h)

    # Load 1H data
    candles_1h = load_candles(conn_1h, symbol)

    print(f"4H candles: {len(df_4h):,}  |  1H candles: {len(candles_1h):,}")

    # Label with 1H intrabar simulation
    entries_1h = label_entries_1h(df_4h, candles_1h)
    if entries_1h.empty:
        print(f"  WARNING: No breakout entries found for {symbol}")
        return None, None

    # Also label with original 4H method for comparison
    entries_4h = label_entries(df_4h)

    # Compare labels
    if not entries_4h.empty and not entries_1h.empty:
        common_idx = entries_4h.index.intersection(entries_1h.index)
        if len(common_idx) > 0:
            labels_4h = entries_4h.loc[common_idx, "label"]
            labels_1h = entries_1h.loc[common_idx, "label"]
            diff = (labels_4h != labels_1h).sum()
            print(f"\n  Label comparison (common entries: {len(common_idx)}):")
            print(f"    4H labels: {labels_4h.sum():.0f} SAFE / {(1-labels_4h).sum():.0f} DANGER")
            print(f"    1H labels: {labels_1h.sum():.0f} SAFE / {(1-labels_1h).sum():.0f} DANGER")
            print(f"    Disagreements: {diff} ({diff/len(common_idx)*100:.1f}%)")

    entries = entries_1h.dropna(subset=FEATURE_NAMES + ["label"])
    print(f"\nTotal breakout entries: {len(entries):,}")
    print(f"  SAFE_TO_TRADE (1): {int(entries['label'].sum()):,} "
          f"({entries['label'].mean()*100:.1f}%)")
    print(f"  DANGER_ZONE   (0): {int((1 - entries['label']).sum()):,} "
          f"({(1 - entries['label']).mean()*100:.1f}%)")

    # Train/test split
    X = entries[FEATURE_NAMES]
    y = entries["label"]
    train_mask = entries.index < TRAIN_CUTOFF
    X_train, y_train = X[train_mask], y[train_mask]
    X_test, y_test = X[~train_mask], y[~train_mask]

    if len(X_train) < 30 or len(X_test) < 10:
        print(f"  WARNING: Not enough data ({len(X_train)} train, {len(X_test)} test)")
        return None, None

    print(f"Train: {len(X_train):,}  |  Test: {len(X_test):,}")

    # Train
    model = RandomForestClassifier(
        max_depth=4, min_samples_leaf=50, n_estimators=200,
        class_weight="balanced", random_state=42, n_jobs=-1,
    )
    model.fit(X_train, y_train)

    # Evaluate
    y_train_proba = model.predict_proba(X_train)[:, 1]
    try:
        train_auc = roc_auc_score(y_train, y_train_proba)
    except ValueError:
        train_auc = 0.0

    metrics = evaluate_model(model, X_test, y_test, FEATURE_NAMES)
    auc_gap = train_auc - metrics["test_auc"]

    print(f"\n  Train AUC: {train_auc:.4f}")
    print(f"  Test AUC:  {metrics['test_auc']:.4f}")
    print(f"  AUC Gap:   {auc_gap:+.4f}  "
          f"{'⚠️ OVERFIT' if auc_gap > 0.15 else '🟡 Mild' if auc_gap > 0.08 else '✅ OK'}")

    # Feature importance
    print(f"\n--- Feature Importance ---")
    importances = model.feature_importances_
    sorted_idx = np.argsort(importances)[::-1]
    for i in sorted_idx:
        bar = "█" * int(importances[i] * 50)
        print(f"  {FEATURE_NAMES[i]:20s}  {importances[i]:.4f}  {bar}")

    # Economic edge
    test_entries = entries[~train_mask].copy()
    print_economic_edge(test_entries, metrics["y_proba"], label=f"{symbol} per-symbol")

    # Save
    MODEL_DIR_PERSYM.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_DIR_PERSYM / f"{symbol}.pkl"
    joblib.dump(model, str(model_path))

    meta = {
        "symbol": symbol,
        "feature_version": FEATURE_VERSION,
        "feature_names": FEATURE_NAMES,
        "model_type": "RandomForestClassifier",
        "labeling": "1h_intrabar",
        "metrics": {
            "train_auc": round(train_auc, 4),
            "test_auc": metrics["test_auc"],
            "auc_gap": round(auc_gap, 4),
            "precision": metrics["precision"],
            "recall": metrics["recall"],
            "f1": metrics["f1"],
        },
        "n_train_entries": int(len(X_train)),
        "n_test_entries": int(len(X_test)),
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = MODEL_DIR_PERSYM / f"{symbol}_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"\nSaved: {model_path}")

    return entries, meta


def train_pooled(all_entries: dict[str, pd.DataFrame]):
    """Train pooled model across all symbols."""
    print(f"\n{'='*60}")
    print(f"  POOLED MODEL (all symbols)")
    print(f"{'='*60}")

    # Combine all entries with symbol one-hot
    dfs = []
    for symbol, entries in all_entries.items():
        df = entries.copy()
        df = add_symbol_onehot(df, symbol)
        df["_symbol"] = symbol
        dfs.append(df)

    pooled = pd.concat(dfs, axis=0).sort_index()
    pooled = pooled.dropna(subset=POOLED_FEATURE_NAMES + ["label"])

    print(f"\nTotal pooled entries: {len(pooled):,}")
    for sym in SYMBOLS:
        sym_entries = pooled[pooled["_symbol"] == sym]
        print(f"  {sym}: {len(sym_entries):,} entries "
              f"({sym_entries['label'].mean()*100:.1f}% SAFE)")

    # Train/test split by time
    X = pooled[POOLED_FEATURE_NAMES]
    y = pooled["label"]
    train_mask = pooled.index < TRAIN_CUTOFF
    X_train, y_train = X[train_mask], y[train_mask]
    X_test, y_test = X[~train_mask], y[~train_mask]

    print(f"\nTrain: {len(X_train):,}  |  Test: {len(X_test):,}")

    # Train
    model = RandomForestClassifier(
        max_depth=4, min_samples_leaf=50, n_estimators=200,
        class_weight="balanced", random_state=42, n_jobs=-1,
    )
    model.fit(X_train, y_train)

    # --- Overall evaluation ---
    y_train_proba = model.predict_proba(X_train)[:, 1]
    try:
        train_auc = roc_auc_score(y_train, y_train_proba)
    except ValueError:
        train_auc = 0.0

    y_test_proba = model.predict_proba(X_test)[:, 1]
    try:
        test_auc = roc_auc_score(y_test, y_test_proba)
    except ValueError:
        test_auc = 0.0

    auc_gap = train_auc - test_auc
    print(f"\n--- Overall Pooled Results ---")
    print(f"  Train AUC: {train_auc:.4f}")
    print(f"  Test AUC:  {test_auc:.4f}")
    print(f"  AUC Gap:   {auc_gap:+.4f}  "
          f"{'⚠️ OVERFIT' if auc_gap > 0.15 else '🟡 Mild' if auc_gap > 0.08 else '✅ OK'}")

    # --- Per-symbol evaluation ---
    print(f"\n--- Per-Symbol AUC (Pooled Model) ---")
    print(f"  {'Symbol':10s}  {'Test AUC':>10s}  {'Test N':>7s}  {'Verdict':>10s}")
    print(f"  {'-'*10}  {'-'*10}  {'-'*7}  {'-'*10}")

    per_symbol_aucs = {}
    for sym in SYMBOLS:
        sym_mask = pooled[~train_mask]["_symbol"] == sym
        if sym_mask.sum() < 5:
            print(f"  {sym:10s}  {'N/A':>10s}  {int(sym_mask.sum()):>7d}")
            continue

        sym_y = y_test[sym_mask.values]
        sym_proba = y_test_proba[sym_mask.values]

        try:
            sym_auc = roc_auc_score(sym_y, sym_proba)
        except ValueError:
            sym_auc = 0.0

        per_symbol_aucs[sym] = round(sym_auc, 4)
        verdict = "✅" if sym_auc >= 0.65 else "🟡" if sym_auc >= 0.55 else "⚠️"
        print(f"  {sym:10s}  {sym_auc:>10.4f}  {int(sym_mask.sum()):>7d}  {verdict:>10s}")

    # --- Feature importance ---
    print(f"\n--- Feature Importance (Pooled) ---")
    importances = model.feature_importances_
    sorted_idx = np.argsort(importances)[::-1]
    for i in sorted_idx:
        bar = "█" * int(importances[i] * 50)
        print(f"  {POOLED_FEATURE_NAMES[i]:20s}  {importances[i]:.4f}  {bar}")

    # --- Per-symbol economic edge ---
    test_pooled = pooled[~train_mask].copy()
    test_pooled["proba"] = y_test_proba
    for sym in SYMBOLS:
        sym_test = test_pooled[test_pooled["_symbol"] == sym]
        if len(sym_test) > 0:
            print_economic_edge(sym_test, sym_test["proba"].values,
                                label=f"{sym} (pooled model)")

    # --- Save ---
    MODEL_DIR_POOLED.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_DIR_POOLED / "pooled.pkl"
    joblib.dump(model, str(model_path))

    meta = {
        "model_type": "pooled",
        "symbols": SYMBOLS,
        "feature_version": FEATURE_VERSION,
        "feature_names": POOLED_FEATURE_NAMES,
        "pooled_feature_names": FEATURE_NAMES,
        "symbol_features": SYMBOL_FEATURES,
        "model_params": {
            "max_depth": 4,
            "min_samples_leaf": 50,
            "n_estimators": 200,
            "class_weight": "balanced",
        },
        "labeling": "1h_intrabar",
        "metrics": {
            "train_auc": round(train_auc, 4),
            "test_auc": round(test_auc, 4),
            "auc_gap": round(auc_gap, 4),
        },
        "per_symbol_test_auc": per_symbol_aucs,
        "n_train_entries": int(len(X_train)),
        "n_test_entries": int(len(X_test)),
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = MODEL_DIR_POOLED / "pooled_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"\nSaved: {model_path}")
    print(f"Saved: {meta_path}")

    return meta


def main():
    parser = argparse.ArgumentParser(
        description="Train Regime Classifier with 1H intrabar labels + pooled model"
    )
    parser.add_argument("--symbol", type=str, default=None,
                        help="Train single symbol (per-symbol only, no pooled)")
    args = parser.parse_args()

    symbols = [args.symbol] if args.symbol else SYMBOLS

    conn_4h = sqlite3.connect(str(DB_4H_PATH))
    conn_1h = sqlite3.connect(str(DB_1H_PATH))

    try:
        all_entries = {}
        per_symbol_results = {}

        for sym in symbols:
            entries, meta = train_persymbol(conn_4h, conn_1h, sym)
            if entries is not None and meta is not None:
                all_entries[sym] = entries
                per_symbol_results[sym] = meta

        # Train pooled model if we have multiple symbols
        pooled_meta = None
        if len(all_entries) >= 2 and args.symbol is None:
            pooled_meta = train_pooled(all_entries)

        # --- Final summary ---
        print(f"\n{'='*60}")
        print(f"  FINAL SUMMARY")
        print(f"{'='*60}")

        if per_symbol_results:
            print(f"\n  Per-Symbol Models (1H intrabar labels):")
            print(f"  {'Symbol':10s}  {'Train AUC':>10s}  {'Test AUC':>10s}  "
                  f"{'Gap':>8s}  {'N_train':>8s}  {'N_test':>7s}")
            print(f"  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*8}  {'-'*8}  {'-'*7}")
            for sym, meta in per_symbol_results.items():
                m = meta["metrics"]
                print(f"  {sym:10s}  {m['train_auc']:>10.4f}  {m['test_auc']:>10.4f}  "
                      f"{m['auc_gap']:>+8.4f}  {meta['n_train_entries']:>8d}  "
                      f"{meta['n_test_entries']:>7d}")

        if pooled_meta:
            print(f"\n  Pooled Model:")
            pm = pooled_meta["metrics"]
            print(f"    Overall — Train AUC: {pm['train_auc']:.4f}  "
                  f"Test AUC: {pm['test_auc']:.4f}  Gap: {pm['auc_gap']:+.4f}")
            print(f"    Per-symbol test AUC:")
            for sym, auc in pooled_meta.get("per_symbol_test_auc", {}).items():
                print(f"      {sym}: {auc:.4f}")

    finally:
        conn_4h.close()
        conn_1h.close()


if __name__ == "__main__":
    main()
