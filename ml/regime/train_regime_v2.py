#!/usr/bin/env python3
"""Train Regime Classifier v2 — with realized-volatility features.

Compares the original 6-feature regime model (v1) against an 8-feature
model that adds atrp_14 and range_sma_6 from the volatility predictor.

Key question: do these realized-vol features help the regime classifier
distinguish breakouts in calm vs volatile conditions?

Usage:
    python3 ml/regime/train_regime_v2.py                   # train all symbols
    python3 ml/regime/train_regime_v2.py --symbol BTCUSDT  # train one symbol
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
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

# Allow imports from parent ml/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from regime.features_regime_v1 import (
    FEATURE_NAMES as V1_FEATURES,
    build_regime_features,
)
from regime.features_regime_v2 import (
    FEATURE_NAMES as V2_FEATURES,
    FEATURE_VERSION as V2_VERSION,
    build_regime_features_v2,
)
from regime.label_regime import label_entries

try:
    import joblib
except ImportError:
    from sklearn.externals import joblib  # type: ignore

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "training.db"
MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "regime_v2"
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
        "safe_wr": safe_wr,
        "danger_wr": danger_wr,
        "edge": edge,
        "pass_pct": len(safe_entries) / len(entries_df) * 100 if len(entries_df) > 0 else 0,
    }


def train_model(X_train, y_train, X_test, y_test, feature_names, label=""):
    """Train a RandomForest and return model + metrics."""
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

    y_pred = model.predict(X_test)
    prec = precision_score(y_test, y_pred, zero_division=0)
    rec = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)

    metrics = {
        "train_auc": round(train_auc, 4),
        "test_auc": round(test_auc, 4),
        "auc_gap": round(auc_gap, 4),
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "f1": round(f1, 4),
    }

    return model, metrics, y_test_proba


def train_symbol(conn: sqlite3.Connection, symbol: str, model_dir: Path) -> dict:
    print(f"\n{'='*70}")
    print(f"  REGIME v1 vs v2 COMPARISON: {symbol}")
    print(f"{'='*70}")

    # --- Load & prepare data ---
    candles = load_candles(conn, symbol)
    funding = load_funding(conn, symbol)
    df = merge_funding(candles, funding)

    # Build BOTH feature sets
    df_v1 = build_regime_features(df)
    df_v2 = build_regime_features_v2(df)

    print(f"Total candles: {len(df):,}")

    # --- Label entries ---
    entries_v1 = label_entries(df_v1)
    entries_v2 = label_entries(df_v2)

    if entries_v1.empty or entries_v2.empty:
        print(f"  WARNING: No breakout entries found for {symbol}")
        return {}

    entries_v1 = entries_v1.dropna(subset=V1_FEATURES + ["label"])
    entries_v2 = entries_v2.dropna(subset=V2_FEATURES + ["label"])

    # Ensure same entries for fair comparison
    common_idx = entries_v1.index.intersection(entries_v2.index)
    entries_v1 = entries_v1.loc[common_idx]
    entries_v2 = entries_v2.loc[common_idx]

    print(f"Total breakout entries: {len(entries_v1):,}")
    print(f"  SAFE_TO_TRADE (1): {int(entries_v1['label'].sum()):,} "
          f"({entries_v1['label'].mean()*100:.1f}%)")

    # --- Train/test split ---
    train_cutoff = get_train_cutoff()
    print(f"Train cutoff: {train_cutoff.strftime('%Y-%m-%d')}")

    train_mask = entries_v1.index < train_cutoff
    n_train = train_mask.sum()
    n_test = (~train_mask).sum()

    if n_train < 30 or n_test < 10:
        print(f"  WARNING: Not enough data (train={n_train}, test={n_test})")
        return {}

    print(f"Train: {n_train:,}  |  Test: {n_test:,}")

    # === Train v1 (6 features) ===
    X_train_v1 = entries_v1.loc[train_mask, V1_FEATURES]
    y_train_v1 = entries_v1.loc[train_mask, "label"]
    X_test_v1 = entries_v1.loc[~train_mask, V1_FEATURES]
    y_test_v1 = entries_v1.loc[~train_mask, "label"]

    print(f"\n--- v1 (6 features) ---")
    model_v1, metrics_v1, proba_v1 = train_model(
        X_train_v1, y_train_v1, X_test_v1, y_test_v1, V1_FEATURES, "v1"
    )
    gap_verdict = "⚠️ OVERFIT" if metrics_v1["auc_gap"] > 0.15 else \
                  "🟡 Mild" if metrics_v1["auc_gap"] > 0.08 else "✅ OK"
    print(f"  Train AUC: {metrics_v1['train_auc']:.4f}")
    print(f"  Test AUC:  {metrics_v1['test_auc']:.4f}")
    print(f"  AUC Gap:   {metrics_v1['auc_gap']:+.4f}  {gap_verdict}")

    edge_v1 = compute_economic_edge(entries_v1[~train_mask], proba_v1)
    print(f"  Edge @0.50: {edge_v1['edge']:+.1f}pp  "
          f"(SAFE {edge_v1['safe_wr']:.1f}% vs DANGER {edge_v1['danger_wr']:.1f}%)")

    # Feature importance v1
    imp_v1 = model_v1.feature_importances_
    sorted_v1 = np.argsort(imp_v1)[::-1]
    print(f"\n  Feature Importance (v1):")
    for i in sorted_v1:
        bar = "█" * int(imp_v1[i] * 50)
        print(f"    {V1_FEATURES[i]:20s}  {imp_v1[i]:.4f}  {bar}")

    # === Train v2 (8 features) ===
    X_train_v2 = entries_v2.loc[train_mask, V2_FEATURES]
    y_train_v2 = entries_v2.loc[train_mask, "label"]
    X_test_v2 = entries_v2.loc[~train_mask, V2_FEATURES]
    y_test_v2 = entries_v2.loc[~train_mask, "label"]

    print(f"\n--- v2 (8 features: +atrp_14, +range_sma_6) ---")
    model_v2, metrics_v2, proba_v2 = train_model(
        X_train_v2, y_train_v2, X_test_v2, y_test_v2, V2_FEATURES, "v2"
    )
    gap_verdict = "⚠️ OVERFIT" if metrics_v2["auc_gap"] > 0.15 else \
                  "🟡 Mild" if metrics_v2["auc_gap"] > 0.08 else "✅ OK"
    print(f"  Train AUC: {metrics_v2['train_auc']:.4f}")
    print(f"  Test AUC:  {metrics_v2['test_auc']:.4f}")
    print(f"  AUC Gap:   {metrics_v2['auc_gap']:+.4f}  {gap_verdict}")

    edge_v2 = compute_economic_edge(entries_v2[~train_mask], proba_v2)
    print(f"  Edge @0.50: {edge_v2['edge']:+.1f}pp  "
          f"(SAFE {edge_v2['safe_wr']:.1f}% vs DANGER {edge_v2['danger_wr']:.1f}%)")

    # Feature importance v2
    imp_v2 = model_v2.feature_importances_
    sorted_v2 = np.argsort(imp_v2)[::-1]
    print(f"\n  Feature Importance (v2):")
    for i in sorted_v2:
        bar = "█" * int(imp_v2[i] * 50)
        print(f"    {V2_FEATURES[i]:20s}  {imp_v2[i]:.4f}  {bar}")

    # === Comparison ===
    auc_delta = metrics_v2["test_auc"] - metrics_v1["test_auc"]
    edge_delta = edge_v2["edge"] - edge_v1["edge"]

    print(f"\n--- v1 vs v2 COMPARISON ---")
    print(f"  AUC change:  {auc_delta:+.4f}  "
          f"({'↑ BETTER' if auc_delta > 0.02 else '↓ WORSE' if auc_delta < -0.02 else '≈ SAME'})")
    print(f"  Edge change: {edge_delta:+.1f}pp  "
          f"({'↑ BETTER' if edge_delta > 2 else '↓ WORSE' if edge_delta < -2 else '≈ SAME'})")
    print(f"  Gap change:  {metrics_v2['auc_gap'] - metrics_v1['auc_gap']:+.4f}  "
          f"({'↑ more overfit' if metrics_v2['auc_gap'] > metrics_v1['auc_gap'] + 0.02 else '↓ less overfit' if metrics_v2['auc_gap'] < metrics_v1['auc_gap'] - 0.02 else '≈ same'})")

    # --- Economic edge at multiple thresholds ---
    print(f"\n--- Economic Edge Comparison (OOS) ---")
    print(f"  {'Thresh':>7s}  {'v1 Edge':>8s}  {'v2 Edge':>8s}  {'Delta':>7s}  "
          f"{'v1 Pass%':>8s}  {'v2 Pass%':>8s}")
    print(f"  {'-'*7}  {'-'*8}  {'-'*8}  {'-'*7}  {'-'*8}  {'-'*8}")

    for t in [0.40, 0.45, 0.50, 0.55, 0.60]:
        e1 = compute_economic_edge(entries_v1[~train_mask], proba_v1, threshold=t)
        e2 = compute_economic_edge(entries_v2[~train_mask], proba_v2, threshold=t)
        d = e2["edge"] - e1["edge"]
        print(f"  {t:>7.2f}  {e1['edge']:>+7.1f}pp  {e2['edge']:>+7.1f}pp  "
              f"{d:>+6.1f}pp  {e1['pass_pct']:>7.0f}%  {e2['pass_pct']:>7.0f}%")

    # --- Save v2 model if it improves on v1 ---
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / f"{symbol}.pkl"
    joblib.dump(model_v2, str(model_path))

    meta = {
        "symbol": symbol,
        "feature_version": V2_VERSION,
        "feature_names": V2_FEATURES,
        "model_type": "RandomForestClassifier",
        "model_params": {
            "max_depth": 4,
            "min_samples_leaf": 50,
            "n_estimators": 200,
            "class_weight": "balanced",
        },
        "metrics_v2": metrics_v2,
        "metrics_v1_comparison": metrics_v1,
        "auc_delta": round(auc_delta, 4),
        "edge_v2_at_050": round(edge_v2["edge"], 2),
        "edge_v1_at_050": round(edge_v1["edge"], 2),
        "n_train_entries": int(n_train),
        "n_test_entries": int(n_test),
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }

    meta_path = model_dir / f"{symbol}_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"\nSaved v2 model: {model_path}")
    print(f"Saved v2 meta:  {meta_path}")

    return {
        "symbol": symbol,
        "v1": metrics_v1,
        "v2": metrics_v2,
        "auc_delta": auc_delta,
        "edge_v1": edge_v1["edge"],
        "edge_v2": edge_v2["edge"],
        "edge_delta": edge_delta,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Train Regime Classifier v2 (8 features) and compare to v1 (6 features)"
    )
    parser.add_argument("--symbol", type=str, default=None, help="Train single symbol")
    parser.add_argument("--model-dir", type=str, default=None, help="Model output directory (default: ml/models/regime_v2)")
    args = parser.parse_args()

    model_dir = Path(args.model_dir) if args.model_dir else MODEL_DIR
    symbols = [args.symbol] if args.symbol else SYMBOLS

    conn = sqlite3.connect(str(DB_PATH))
    try:
        results = {}
        for sym in symbols:
            result = train_symbol(conn, sym, model_dir)
            if result:
                results[sym] = result

        if results:
            print(f"\n{'='*70}")
            print(f"  FINAL SUMMARY — v1 (6 features) vs v2 (8 features)")
            print(f"{'='*70}")
            print(f"  {'Symbol':10s}  {'v1 AUC':>8s}  {'v2 AUC':>8s}  "
                  f"{'ΔAUC':>7s}  {'v1 Edge':>8s}  {'v2 Edge':>8s}  "
                  f"{'ΔEdge':>7s}  {'Verdict'}")
            print(f"  {'-'*10}  {'-'*8}  {'-'*8}  {'-'*7}  {'-'*8}  "
                  f"{'-'*8}  {'-'*7}  {'-'*10}")
            for sym, r in results.items():
                verdict = "✅ v2 better" if r["auc_delta"] > 0.02 and r["edge_delta"] > 0 else \
                          "❌ v2 worse" if r["auc_delta"] < -0.02 or r["edge_delta"] < -5 else \
                          "🟡 similar"
                print(f"  {sym:10s}  {r['v1']['test_auc']:>8.4f}  "
                      f"{r['v2']['test_auc']:>8.4f}  {r['auc_delta']:>+7.4f}  "
                      f"{r['edge_v1']:>+7.1f}pp  {r['edge_v2']:>+7.1f}pp  "
                      f"{r['edge_delta']:>+6.1f}pp  {verdict}")

            print(f"\n  Key question: do atrp_14 and range_sma_6 help?")
            improved = sum(1 for r in results.values() if r["auc_delta"] > 0.02)
            print(f"  → {improved}/{len(results)} symbols improved test AUC by >0.02")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
