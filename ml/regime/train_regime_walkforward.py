#!/usr/bin/env python3
"""Walk-forward validation for the Regime Classifier.

Instead of a single train/test split, retrain every 3 months on a rolling
2-year window and evaluate on the next 3-month period. This tests whether
the model's signal is stable over time or just an artifact of one split.

Walk-forward windows:
    Window 1: train [2020-02, 2022-02) → test [2022-02, 2022-05)
    Window 2: train [2020-05, 2022-05) → test [2022-05, 2022-08)
    ...
    Window N: train [2023-11, 2025-11) → test [2025-11, 2026-02)

Usage:
    python3 ml/regime/train_regime_walkforward.py
    python3 ml/regime/train_regime_walkforward.py --symbol SOLUSDT
"""

from __future__ import annotations

import argparse
import json
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

# Walk-forward parameters
TRAIN_WINDOW_MONTHS = 24  # 2-year rolling window
STEP_MONTHS = 3           # retrain every 3 months
MIN_TRAIN_ENTRIES = 50    # minimum entries to train on
MIN_TEST_ENTRIES = 10     # minimum entries to evaluate on


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


def generate_windows(data_start: pd.Timestamp, data_end: pd.Timestamp):
    """Generate walk-forward (train_start, train_end, test_start, test_end) tuples."""
    windows = []

    # First train window starts at data_start
    train_start = data_start

    while True:
        train_end = train_start + pd.DateOffset(months=TRAIN_WINDOW_MONTHS)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=STEP_MONTHS)

        # Stop if test period goes beyond available data
        if test_start >= data_end:
            break

        # Clip test_end to data_end if needed
        if test_end > data_end:
            test_end = data_end

        windows.append((train_start, train_end, test_start, test_end))

        # Slide forward by step size
        train_start = train_start + pd.DateOffset(months=STEP_MONTHS)

    return windows


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
    }


def walkforward_symbol(conn: sqlite3.Connection, symbol: str) -> list[dict]:
    """Run walk-forward validation for one symbol."""
    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD VALIDATION: {symbol}")
    print(f"{'='*70}")

    # Load data
    candles = load_candles(conn, symbol)
    funding = load_funding(conn, symbol)
    df = merge_funding(candles, funding)
    df = build_regime_features(df)

    print(f"Total candles: {len(df):,}")
    print(f"Date range: {df.index.min().strftime('%Y-%m-%d')} → "
          f"{df.index.max().strftime('%Y-%m-%d')}")

    # Label all entries upfront
    entries = label_entries(df)
    if entries.empty:
        print(f"  WARNING: No breakout entries found for {symbol}")
        return []

    entries = entries.dropna(subset=FEATURE_NAMES + ["label"])
    print(f"Total breakout entries: {len(entries):,}")
    print(f"  SAFE_TO_TRADE (1): {int(entries['label'].sum()):,} "
          f"({entries['label'].mean()*100:.1f}%)")

    # Generate windows
    data_start = entries.index.min()
    data_end = entries.index.max()
    windows = generate_windows(data_start, data_end)
    print(f"\nWalk-forward windows: {len(windows)}")

    # Header
    print(f"\n  {'Window':>6s}  {'Train Period':>25s}  {'Test Period':>25s}  "
          f"{'N_tr':>5s}  {'N_te':>5s}  {'Tr AUC':>7s}  {'Te AUC':>7s}  "
          f"{'Gap':>7s}  {'Edge@0.5':>9s}  {'Verdict':>8s}")
    print(f"  {'-'*6}  {'-'*25}  {'-'*25}  {'-'*5}  {'-'*5}  {'-'*7}  "
          f"{'-'*7}  {'-'*7}  {'-'*9}  {'-'*8}")

    results = []

    for w_idx, (train_start, train_end, test_start, test_end) in enumerate(windows, 1):
        # Split entries by time
        train_mask = (entries.index >= train_start) & (entries.index < train_end)
        test_mask = (entries.index >= test_start) & (entries.index < test_end)

        X_train = entries.loc[train_mask, FEATURE_NAMES]
        y_train = entries.loc[train_mask, "label"]
        X_test = entries.loc[test_mask, FEATURE_NAMES]
        y_test = entries.loc[test_mask, "label"]

        train_str = f"{train_start.strftime('%Y-%m')}->{train_end.strftime('%Y-%m')}"
        test_str = f"{test_start.strftime('%Y-%m')}->{test_end.strftime('%Y-%m')}"

        n_train = len(X_train)
        n_test = len(X_test)

        if n_train < MIN_TRAIN_ENTRIES or n_test < MIN_TEST_ENTRIES:
            print(f"  {w_idx:>6d}  {train_str:>25s}  {test_str:>25s}  "
                  f"{n_train:>5d}  {n_test:>5d}  {'SKIP':>7s}  {'SKIP':>7s}  "
                  f"{'':>7s}  {'':>9s}  {'skip':>8s}")
            continue

        # Train model
        model = RandomForestClassifier(
            max_depth=4,
            min_samples_leaf=50,
            n_estimators=200,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )
        model.fit(X_train, y_train)

        # Evaluate
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
        test_entries = entries.loc[test_mask].copy()
        edge_info = compute_economic_edge(test_entries, y_test_proba, threshold=0.50)

        # Verdict
        if test_auc >= 0.65 and edge_info["edge"] > 5:
            verdict = "✅ GOOD"
        elif test_auc >= 0.55 or edge_info["edge"] > 0:
            verdict = "🟡 OK"
        else:
            verdict = "⚠️ BAD"

        print(f"  {w_idx:>6d}  {train_str:>25s}  {test_str:>25s}  "
              f"{n_train:>5d}  {n_test:>5d}  {train_auc:>7.3f}  {test_auc:>7.3f}  "
              f"{auc_gap:>+7.3f}  {edge_info['edge']:>+8.1f}pp  {verdict:>8s}")

        results.append({
            "window": w_idx,
            "train_period": train_str,
            "test_period": test_str,
            "n_train": n_train,
            "n_test": n_test,
            "train_auc": round(train_auc, 4),
            "test_auc": round(test_auc, 4),
            "auc_gap": round(auc_gap, 4),
            "edge": edge_info["edge"],
            "safe_wr": edge_info["safe_wr"],
            "danger_wr": edge_info["danger_wr"],
        })

    return results


def print_symbol_summary(symbol: str, results: list[dict]):
    """Print summary statistics for one symbol's walk-forward results."""
    if not results:
        print(f"\n  {symbol}: No valid windows")
        return

    test_aucs = [r["test_auc"] for r in results]
    edges = [r["edge"] for r in results]
    gaps = [r["auc_gap"] for r in results]

    mean_auc = np.mean(test_aucs)
    std_auc = np.std(test_aucs)
    min_auc = np.min(test_aucs)
    max_auc = np.max(test_aucs)

    mean_edge = np.mean(edges)
    positive_edge_pct = sum(1 for e in edges if e > 0) / len(edges) * 100

    mean_gap = np.mean(gaps)

    # Stability verdict
    if mean_auc >= 0.60 and std_auc < 0.10 and positive_edge_pct >= 60:
        stability = "✅ STABLE"
    elif mean_auc >= 0.55 and positive_edge_pct >= 50:
        stability = "🟡 BORDERLINE"
    else:
        stability = "⚠️ UNSTABLE"

    print(f"\n  {symbol}:")
    print(f"    Windows evaluated:   {len(results)}")
    print(f"    Test AUC:           mean={mean_auc:.3f}  std={std_auc:.3f}  "
          f"range=[{min_auc:.3f}, {max_auc:.3f}]")
    print(f"    AUC Gap:            mean={mean_gap:+.3f}")
    print(f"    Edge @0.50:         mean={mean_edge:+.1f}pp  "
          f"(positive in {positive_edge_pct:.0f}% of windows)")
    print(f"    Stability:          {stability}")

    return {
        "symbol": symbol,
        "n_windows": len(results),
        "mean_auc": round(mean_auc, 4),
        "std_auc": round(std_auc, 4),
        "min_auc": round(min_auc, 4),
        "max_auc": round(max_auc, 4),
        "mean_gap": round(mean_gap, 4),
        "mean_edge": round(mean_edge, 1),
        "positive_edge_pct": round(positive_edge_pct, 1),
        "stability": stability,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Walk-forward validation for Regime Classifier"
    )
    parser.add_argument("--symbol", type=str, default=None,
                        help="Validate single symbol")
    args = parser.parse_args()

    symbols = [args.symbol] if args.symbol else SYMBOLS

    conn = sqlite3.connect(str(DB_PATH))
    try:
        all_results = {}
        for sym in symbols:
            results = walkforward_symbol(conn, sym)
            all_results[sym] = results

        # --- Final summary ---
        print(f"\n{'='*70}")
        print(f"  WALK-FORWARD SUMMARY")
        print(f"{'='*70}")
        print(f"\n  Train window: {TRAIN_WINDOW_MONTHS} months (rolling)")
        print(f"  Step size:    {STEP_MONTHS} months")

        summaries = {}
        for sym, results in all_results.items():
            summary = print_symbol_summary(sym, results)
            if summary:
                summaries[sym] = summary

        # Comparison table
        if summaries:
            print(f"\n{'='*70}")
            print(f"  COMPARISON TABLE")
            print(f"{'='*70}")
            print(f"  {'Symbol':10s}  {'Mean AUC':>9s}  {'Std AUC':>8s}  "
                  f"{'Mean Edge':>10s}  {'Edge>0%':>8s}  {'Verdict'}")
            print(f"  {'-'*10}  {'-'*9}  {'-'*8}  {'-'*10}  {'-'*8}  {'-'*12}")
            for sym, s in summaries.items():
                print(f"  {sym:10s}  {s['mean_auc']:>9.4f}  {s['std_auc']:>8.4f}  "
                      f"{s['mean_edge']:>+9.1f}pp  {s['positive_edge_pct']:>7.0f}%  "
                      f"{s['stability']}")

            print(f"\n  Interpretation:")
            print(f"  • ✅ STABLE = mean AUC ≥ 0.60, std < 0.10, positive edge ≥ 60%")
            print(f"  • 🟡 BORDERLINE = mean AUC ≥ 0.55, positive edge ≥ 50%")
            print(f"  • ⚠️ UNSTABLE = inconsistent signal, not production-ready")
            print(f"\n  If a symbol is STABLE across walk-forward windows, it means")
            print(f"  the regime signal persists over time and isn't an artifact")
            print(f"  of one particular train/test split.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
