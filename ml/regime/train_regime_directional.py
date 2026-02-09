#!/usr/bin/env python3
"""Directional split experiment for the Regime Classifier.

Hypothesis: features predicting good LONG entries may differ from SHORT entries.
Trains separate models for each direction and compares to the combined model.

For each symbol, trains three model variants:
    1. Combined (all breakouts) — baseline
    2. LONG-only (long breakouts only)
    3. SHORT-only (short breakouts only)

Usage:
    python3 ml/regime/train_regime_directional.py
    python3 ml/regime/train_regime_directional.py --symbol SOLUSDT
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

# Allow imports from parent ml/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from regime.features_regime_v1 import FEATURE_NAMES, FEATURE_VERSION, build_regime_features
from regime.label_regime import label_entries

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "training.db"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
TRAIN_CUTOFF = pd.Timestamp("2025-07-01", tz="UTC")


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


def compute_economic_edge(entries_df, y_proba, threshold=0.50):
    """Compute SAFE vs DANGER win rates at given threshold."""
    safe_mask = y_proba >= threshold
    danger_mask = ~safe_mask

    safe_entries = entries_df[safe_mask]
    danger_entries = entries_df[danger_mask]

    safe_wr = safe_entries["label"].mean() * 100 if len(safe_entries) > 0 else 0
    danger_wr = danger_entries["label"].mean() * 100 if len(danger_entries) > 0 else 0
    edge = safe_wr - danger_wr

    return {
        "safe_n": len(safe_entries),
        "danger_n": len(danger_entries),
        "safe_wr": round(safe_wr, 1),
        "danger_wr": round(danger_wr, 1),
        "edge": round(edge, 1),
        "pass_pct": round(len(safe_entries) / len(entries_df) * 100, 1) if len(entries_df) > 0 else 0,
    }


def train_variant(entries, feature_names, variant_name, min_train=30, min_test=10):
    """Train one model variant and return metrics + model."""
    entries_clean = entries.dropna(subset=feature_names + ["label"])

    train_mask = entries_clean.index < TRAIN_CUTOFF
    X_train = entries_clean.loc[train_mask, feature_names]
    y_train = entries_clean.loc[train_mask, "label"]
    X_test = entries_clean.loc[~train_mask, feature_names]
    y_test = entries_clean.loc[~train_mask, "label"]

    n_train = len(X_train)
    n_test = len(X_test)

    if n_train < min_train or n_test < min_test:
        return None

    # Check for degenerate case (all same class)
    if len(y_train.unique()) < 2:
        return None

    model = RandomForestClassifier(
        max_depth=4,
        min_samples_leaf=50,
        n_estimators=200,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    y_train_proba = model.predict_proba(X_train)[:, 1]
    y_test_proba = model.predict_proba(X_test)[:, 1]

    try:
        train_auc = roc_auc_score(y_train, y_train_proba)
    except ValueError:
        train_auc = 0.0
    try:
        test_auc = roc_auc_score(y_test, y_test_proba)
    except ValueError:
        test_auc = 0.0

    auc_gap = train_auc - test_auc

    # Economic edge
    test_entries = entries_clean[~train_mask].copy()
    edge_info = compute_economic_edge(test_entries, y_test_proba, threshold=0.50)

    # Feature importance
    importances = dict(zip(feature_names, model.feature_importances_))

    return {
        "variant": variant_name,
        "n_train": n_train,
        "n_test": n_test,
        "train_safe_pct": round(y_train.mean() * 100, 1),
        "test_safe_pct": round(y_test.mean() * 100, 1),
        "train_auc": round(train_auc, 4),
        "test_auc": round(test_auc, 4),
        "auc_gap": round(auc_gap, 4),
        "edge": edge_info["edge"],
        "safe_wr": edge_info["safe_wr"],
        "danger_wr": edge_info["danger_wr"],
        "pass_pct": edge_info["pass_pct"],
        "importances": importances,
        "model": model,
    }


def analyze_symbol(conn: sqlite3.Connection, symbol: str) -> dict:
    """Run directional split analysis for one symbol."""
    print(f"\n{'='*70}")
    print(f"  DIRECTIONAL SPLIT: {symbol}")
    print(f"{'='*70}")

    # Load data
    candles = load_candles(conn, symbol)
    funding = load_funding(conn, symbol)
    df = merge_funding(candles, funding)
    df = build_regime_features(df)

    # Label entries
    entries = label_entries(df)
    if entries.empty:
        print(f"  WARNING: No breakout entries found for {symbol}")
        return {}

    entries = entries.dropna(subset=FEATURE_NAMES + ["label"])
    print(f"Total entries: {len(entries):,}")

    # Split by direction
    long_entries = entries[entries["side"] == "LONG"]
    short_entries = entries[entries["side"] == "SHORT"]

    print(f"  LONG entries:  {len(long_entries):,} "
          f"({long_entries['label'].mean()*100:.1f}% SAFE)")
    print(f"  SHORT entries: {len(short_entries):,} "
          f"({short_entries['label'].mean()*100:.1f}% SAFE)")

    # Train/test split counts
    for name, ents in [("LONG", long_entries), ("SHORT", short_entries)]:
        train_n = (ents.index < TRAIN_CUTOFF).sum()
        test_n = (ents.index >= TRAIN_CUTOFF).sum()
        print(f"    {name}: {train_n} train, {test_n} test")

    # --- Train three variants ---
    results = {}

    # 1. Combined (baseline)
    print(f"\n--- Combined (all breakouts) ---")
    r = train_variant(entries, FEATURE_NAMES, "combined")
    if r:
        results["combined"] = r
        print(f"  Train AUC: {r['train_auc']:.4f}  Test AUC: {r['test_auc']:.4f}  "
              f"Gap: {r['auc_gap']:+.4f}  Edge: {r['edge']:+.1f}pp")

    # 2. LONG-only
    print(f"\n--- LONG-only ---")
    r = train_variant(long_entries, FEATURE_NAMES, "long")
    if r:
        results["long"] = r
        print(f"  Train AUC: {r['train_auc']:.4f}  Test AUC: {r['test_auc']:.4f}  "
              f"Gap: {r['auc_gap']:+.4f}  Edge: {r['edge']:+.1f}pp")
    else:
        print(f"  SKIPPED (insufficient data)")

    # 3. SHORT-only
    print(f"\n--- SHORT-only ---")
    r = train_variant(short_entries, FEATURE_NAMES, "short")
    if r:
        results["short"] = r
        print(f"  Train AUC: {r['train_auc']:.4f}  Test AUC: {r['test_auc']:.4f}  "
              f"Gap: {r['auc_gap']:+.4f}  Edge: {r['edge']:+.1f}pp")
    else:
        print(f"  SKIPPED (insufficient data)")

    # --- Feature importance comparison ---
    if "long" in results and "short" in results:
        print(f"\n--- Feature Importance: LONG vs SHORT ---")
        print(f"  {'Feature':20s}  {'LONG':>8s}  {'SHORT':>8s}  {'Delta':>8s}  {'Dominant'}")
        print(f"  {'-'*20}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*10}")

        long_imp = results["long"]["importances"]
        short_imp = results["short"]["importances"]

        for feat in FEATURE_NAMES:
            li = long_imp.get(feat, 0)
            si = short_imp.get(feat, 0)
            delta = li - si
            dominant = "LONG" if delta > 0.03 else "SHORT" if delta < -0.03 else "≈"
            print(f"  {feat:20s}  {li:>8.4f}  {si:>8.4f}  {delta:>+8.4f}  {dominant}")

    # --- Summary ---
    print(f"\n--- Comparison Summary ---")
    print(f"  {'Variant':10s}  {'Train AUC':>10s}  {'Test AUC':>10s}  {'Gap':>8s}  "
          f"{'Edge':>8s}  {'N_test':>7s}  {'SAFE%_tr':>9s}  {'SAFE%_te':>9s}")
    print(f"  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*8}  {'-'*8}  "
          f"{'-'*7}  {'-'*9}  {'-'*9}")

    for name, r in results.items():
        print(f"  {name:10s}  {r['train_auc']:>10.4f}  {r['test_auc']:>10.4f}  "
              f"{r['auc_gap']:>+8.4f}  {r['edge']:>+7.1f}pp  "
              f"{r['n_test']:>7d}  {r['train_safe_pct']:>8.1f}%  "
              f"{r['test_safe_pct']:>8.1f}%")

    # --- Verdict ---
    if "long" in results and "short" in results:
        combined_auc = results.get("combined", {}).get("test_auc", 0)
        long_auc = results["long"]["test_auc"]
        short_auc = results["short"]["test_auc"]

        print(f"\n  Verdict:")
        if long_auc > combined_auc + 0.05 or short_auc > combined_auc + 0.05:
            better_side = "LONG" if long_auc > short_auc else "SHORT"
            print(f"    ✅ Directional split helps! {better_side} model is significantly "
                  f"better than combined.")
            print(f"       → Consider training separate LONG/SHORT models for {symbol}")
        elif long_auc < combined_auc - 0.05 and short_auc < combined_auc - 0.05:
            print(f"    ❌ Directional split hurts — both directions worse than combined.")
            print(f"       → Stick with combined model (the interaction between LONG/SHORT helps)")
        else:
            print(f"    🟡 No clear advantage from directional split.")
            print(f"       → Combined model is fine; splitting doesn't help enough")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Directional split experiment for Regime Classifier"
    )
    parser.add_argument("--symbol", type=str, default=None,
                        help="Analyze single symbol")
    args = parser.parse_args()

    symbols = [args.symbol] if args.symbol else SYMBOLS

    conn = sqlite3.connect(str(DB_PATH))
    try:
        all_results = {}
        for sym in symbols:
            results = analyze_symbol(conn, sym)
            if results:
                all_results[sym] = results

        # --- Final summary ---
        if all_results:
            print(f"\n{'='*70}")
            print(f"  FINAL DIRECTIONAL SPLIT SUMMARY")
            print(f"{'='*70}")
            print(f"\n  {'Symbol':10s}  {'Combined':>10s}  {'LONG':>10s}  {'SHORT':>10s}  "
                  f"{'Best':>10s}  {'Verdict'}")
            print(f"  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*15}")

            for sym, results in all_results.items():
                c_auc = results.get("combined", {}).get("test_auc", 0)
                l_auc = results.get("long", {}).get("test_auc", 0)
                s_auc = results.get("short", {}).get("test_auc", 0)

                best = max(c_auc, l_auc, s_auc)
                if best == c_auc:
                    best_name = "combined"
                elif best == l_auc:
                    best_name = "LONG"
                else:
                    best_name = "SHORT"

                verdict = "split helps" if best > c_auc + 0.05 else "combined OK"

                c_str = f"{c_auc:.4f}" if c_auc > 0 else "N/A"
                l_str = f"{l_auc:.4f}" if "long" in results else "N/A"
                s_str = f"{s_auc:.4f}" if "short" in results else "N/A"

                print(f"  {sym:10s}  {c_str:>10s}  {l_str:>10s}  {s_str:>10s}  "
                      f"{best_name:>10s}  {verdict}")

            print(f"\n  Note: With ~60-80 entries per direction in test, these results")
            print(f"  are noisy. Improvements >0.05 AUC are potentially meaningful;")
            print(f"  smaller differences are likely noise.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
