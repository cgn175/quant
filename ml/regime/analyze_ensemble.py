#!/usr/bin/env python3
"""Ensemble analysis: Regime Classifier + Volatility Predictor.

Simulates combining both models' predictions on OOS data to measure
whether the ensemble filter (regime=SAFE AND stop_width reasonable)
provides better edge than either model alone.

Strategies tested:
    A: Regime only (baseline)
    B: Vol filter only (skip when predicted stop too wide)
    C: Regime AND Vol (the ensemble)
    D: Regime + stop-width-adjusted sizing

Usage:
    python3 ml/regime/analyze_ensemble.py
    python3 ml/regime/analyze_ensemble.py --symbol SOLUSDT
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Allow imports from parent ml/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from regime.features_regime_v1 import FEATURE_NAMES as REGIME_FEATURES, build_regime_features
from volatility.features_vol_v1 import FEATURE_NAMES as VOL_FEATURES, build_vol_features
from regime.label_regime import label_entries

try:
    import joblib
except ImportError:
    from sklearn.externals import joblib  # type: ignore

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "training.db"
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
TRAIN_CUTOFF = pd.Timestamp("2025-07-01", tz="UTC")

LOG_EPS = 1e-8

# Default dynamic stop parameters
DEFAULT_K = 1.2
DEFAULT_MIN_STOP = 0.01  # 1%
DEFAULT_MAX_STOP = 0.04  # 4%


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


def load_regime_model(symbol: str):
    """Load regime classifier model + meta for a symbol."""
    model_path = MODEL_DIR / "regime_v1" / f"{symbol}.pkl"
    meta_path = MODEL_DIR / "regime_v1" / f"{symbol}_meta.json"

    if not model_path.exists() or not meta_path.exists():
        return None, None

    model = joblib.load(str(model_path))
    with open(meta_path) as f:
        meta = json.load(f)

    return model, meta


def load_vol_model(symbol: str):
    """Load volatility predictor model + meta for a symbol."""
    model_path = MODEL_DIR / "vol_v1" / f"{symbol}.pkl"
    meta_path = MODEL_DIR / "vol_v1" / f"{symbol}_meta.json"

    if not model_path.exists() or not meta_path.exists():
        return None, None

    model = joblib.load(str(model_path))
    with open(meta_path) as f:
        meta = json.load(f)

    return model, meta


def predict_vol_range(model, meta, features_array):
    """Predict range %, handling log transform."""
    log_pred = model.predict(features_array)
    log_eps = meta.get("log_eps", LOG_EPS)
    return np.exp(log_pred) - log_eps


def compute_stop_pct(pred_range_pct, k=DEFAULT_K,
                     min_stop=DEFAULT_MIN_STOP, max_stop=DEFAULT_MAX_STOP):
    """Compute clamped dynamic stop percentage."""
    stop_pct = k * pred_range_pct
    return np.clip(stop_pct, min_stop, max_stop)


def analyze_strategy(entries_df, passed_mask, strategy_name):
    """Compute win rate metrics for a filtering strategy."""
    passed = entries_df[passed_mask]
    blocked = entries_df[~passed_mask]

    passed_wr = passed["label"].mean() * 100 if len(passed) > 0 else 0
    blocked_wr = blocked["label"].mean() * 100 if len(blocked) > 0 else 0
    edge = passed_wr - blocked_wr

    return {
        "strategy": strategy_name,
        "n_passed": len(passed),
        "n_blocked": len(blocked),
        "pass_pct": round(len(passed) / len(entries_df) * 100, 1) if len(entries_df) > 0 else 0,
        "passed_wr": round(passed_wr, 1),
        "blocked_wr": round(blocked_wr, 1),
        "edge": round(edge, 1),
    }


def analyze_symbol(conn: sqlite3.Connection, symbol: str) -> dict:
    """Run ensemble analysis for one symbol."""
    print(f"\n{'='*70}")
    print(f"  ENSEMBLE ANALYSIS: {symbol}")
    print(f"{'='*70}")

    # Load models
    regime_model, regime_meta = load_regime_model(symbol)
    vol_model, vol_meta = load_vol_model(symbol)

    if regime_model is None:
        print(f"  WARNING: No regime model found for {symbol}")
        return {}
    if vol_model is None:
        print(f"  WARNING: No vol model found for {symbol}")
        return {}

    print(f"  Regime model: {regime_meta.get('feature_version', '?')}")
    print(f"  Vol model:    {vol_meta.get('feature_version', '?')} "
          f"({vol_meta.get('model_type', '?')})")

    # Load candles and build both feature sets
    candles = load_candles(conn, symbol)
    funding = load_funding(conn, symbol)
    df_base = merge_funding(candles, funding)

    df_regime = build_regime_features(df_base)
    df_vol = build_vol_features(candles)

    # Label entries
    entries = label_entries(df_regime)
    if entries.empty:
        print(f"  WARNING: No breakout entries for {symbol}")
        return {}

    entries = entries.dropna(subset=REGIME_FEATURES + ["label"])

    # Get OOS entries only
    oos_entries = entries[entries.index >= TRAIN_CUTOFF].copy()
    n_oos = len(oos_entries)

    if n_oos < 10:
        print(f"  WARNING: Only {n_oos} OOS entries for {symbol}")
        return {}

    print(f"\n  OOS entries: {n_oos}")
    print(f"  OOS SAFE rate: {oos_entries['label'].mean()*100:.1f}%")

    # --- Compute predictions for all OOS entries ---
    # Regime predictions
    regime_features_df = df_regime.loc[oos_entries.index, REGIME_FEATURES]
    regime_X = regime_features_df.values.astype(np.float64)
    regime_proba = regime_model.predict_proba(regime_X)[:, 1]
    oos_entries["prob_safe"] = regime_proba

    # Vol predictions
    vol_features_available = []
    vol_preds = []
    for idx in oos_entries.index:
        if idx in df_vol.index:
            row = df_vol.loc[idx]
            if all(pd.notna(row.get(f, np.nan)) for f in VOL_FEATURES):
                vol_features_available.append(idx)
                feat_arr = np.array([[row[f] for f in VOL_FEATURES]], dtype=np.float64)
                pred = predict_vol_range(vol_model, vol_meta, feat_arr)
                vol_preds.append(float(pred[0]))
            else:
                vol_preds.append(np.nan)
                vol_features_available.append(idx)
        else:
            vol_preds.append(np.nan)
            vol_features_available.append(idx)

    oos_entries["pred_range_pct"] = vol_preds

    # Fill NaN vol predictions with median
    median_pred = np.nanmedian(vol_preds) if any(~np.isnan(v) for v in vol_preds) else 0.02
    oos_entries["pred_range_pct"] = oos_entries["pred_range_pct"].fillna(median_pred)

    # Compute stop widths at different k values
    for k in [1.0, 1.2]:
        col = f"stop_pct_k{k:.1f}"
        oos_entries[col] = compute_stop_pct(
            oos_entries["pred_range_pct"].values, k=k
        )

    # --- Print prediction distributions ---
    print(f"\n--- Prediction Distributions (OOS) ---")
    print(f"  Regime prob_safe:   mean={regime_proba.mean():.3f}  "
          f"median={np.median(regime_proba):.3f}  "
          f"std={regime_proba.std():.3f}")
    print(f"  Vol pred_range:     mean={oos_entries['pred_range_pct'].mean()*100:.2f}%  "
          f"median={oos_entries['pred_range_pct'].median()*100:.2f}%  "
          f"std={oos_entries['pred_range_pct'].std()*100:.2f}%")
    print(f"  Stop width (k=1.2): mean={oos_entries['stop_pct_k1.2'].mean()*100:.2f}%  "
          f"P10={np.percentile(oos_entries['stop_pct_k1.2'], 10)*100:.2f}%  "
          f"P90={np.percentile(oos_entries['stop_pct_k1.2'], 90)*100:.2f}%")

    # --- Strategy Analysis ---
    all_results = []

    # Test multiple parameter combinations
    regime_thresholds = [0.40, 0.45, 0.50, 0.55]
    vol_max_stops = [0.02, 0.025, 0.03, 0.035, 0.04]

    # Strategy A: Regime only
    print(f"\n--- Strategy A: Regime Only ---")
    print(f"  {'Thresh':>7s}  {'Passed':>7s}  {'Pass%':>6s}  "
          f"{'WR_pass':>8s}  {'WR_block':>9s}  {'Edge':>8s}")
    print(f"  {'-'*7}  {'-'*7}  {'-'*6}  {'-'*8}  {'-'*9}  {'-'*8}")

    for t in regime_thresholds:
        mask = oos_entries["prob_safe"] >= t
        r = analyze_strategy(oos_entries, mask, f"regime≥{t}")
        all_results.append(r)
        print(f"  {t:>7.2f}  {r['n_passed']:>7d}  {r['pass_pct']:>5.0f}%  "
              f"{r['passed_wr']:>7.1f}%  {r['blocked_wr']:>8.1f}%  "
              f"{r['edge']:>+7.1f}pp")

    # Strategy B: Vol filter only
    print(f"\n--- Strategy B: Vol Filter Only (skip if stop too wide) ---")
    print(f"  {'Max Stop':>8s}  {'Passed':>7s}  {'Pass%':>6s}  "
          f"{'WR_pass':>8s}  {'WR_block':>9s}  {'Edge':>8s}")
    print(f"  {'-'*8}  {'-'*7}  {'-'*6}  {'-'*8}  {'-'*9}  {'-'*8}")

    for max_stop in vol_max_stops:
        mask = oos_entries["stop_pct_k1.2"] <= max_stop
        r = analyze_strategy(oos_entries, mask, f"stop≤{max_stop*100:.1f}%")
        all_results.append(r)
        print(f"  {max_stop*100:>7.1f}%  {r['n_passed']:>7d}  {r['pass_pct']:>5.0f}%  "
              f"{r['passed_wr']:>7.1f}%  {r['blocked_wr']:>8.1f}%  "
              f"{r['edge']:>+7.1f}pp")

    # Strategy C: Regime AND Vol (ensemble)
    print(f"\n--- Strategy C: Regime AND Vol Ensemble ---")
    print(f"  {'Regime≥':>8s}  {'Stop≤':>7s}  {'Passed':>7s}  {'Pass%':>6s}  "
          f"{'WR_pass':>8s}  {'WR_block':>9s}  {'Edge':>8s}")
    print(f"  {'-'*8}  {'-'*7}  {'-'*7}  {'-'*6}  {'-'*8}  {'-'*9}  {'-'*8}")

    best_ensemble = None
    best_ensemble_edge = -999

    for t in regime_thresholds:
        for max_stop in [0.025, 0.03, 0.035]:
            mask = (oos_entries["prob_safe"] >= t) & (oos_entries["stop_pct_k1.2"] <= max_stop)
            r = analyze_strategy(oos_entries, mask, f"r≥{t}+s≤{max_stop*100:.0f}%")
            all_results.append(r)

            marker = ""
            if r["edge"] > best_ensemble_edge and r["n_passed"] >= 5:
                best_ensemble_edge = r["edge"]
                best_ensemble = r
                marker = " ← best"

            print(f"  {t:>8.2f}  {max_stop*100:>6.1f}%  {r['n_passed']:>7d}  "
                  f"{r['pass_pct']:>5.0f}%  {r['passed_wr']:>7.1f}%  "
                  f"{r['blocked_wr']:>8.1f}%  {r['edge']:>+7.1f}pp{marker}")

    # Strategy D: Regime + stop-width-adjusted sizing
    print(f"\n--- Strategy D: Regime + Adaptive Sizing ---")
    print(f"  (Enter if regime≥thresh, adjust size by 1/stop_width)")
    for t in [0.45, 0.50]:
        mask = oos_entries["prob_safe"] >= t
        passed = oos_entries[mask]
        if len(passed) == 0:
            continue

        # Compute relative sizing: inverse of stop width, normalized
        stop_widths = passed["stop_pct_k1.2"].values
        size_scalars = (DEFAULT_MIN_STOP + DEFAULT_MAX_STOP) / (2 * stop_widths)
        size_scalars = np.clip(size_scalars, 0.5, 2.0)

        # Weighted win rate: trades with tighter stops get more weight
        weighted_wins = (passed["label"].values * size_scalars).sum()
        total_weight = size_scalars.sum()
        weighted_wr = weighted_wins / total_weight * 100 if total_weight > 0 else 0

        unweighted_wr = passed["label"].mean() * 100
        print(f"  Thresh {t:.2f}: {len(passed)} trades  "
              f"Unweighted WR: {unweighted_wr:.1f}%  "
              f"Weighted WR: {weighted_wr:.1f}%  "
              f"Mean size scalar: {size_scalars.mean():.2f}")

    # --- Summary ---
    print(f"\n--- Best Configuration ---")
    if best_ensemble and best_ensemble["edge"] > 0:
        print(f"  {best_ensemble['strategy']}")
        print(f"    Passed: {best_ensemble['n_passed']} ({best_ensemble['pass_pct']:.0f}%)")
        print(f"    WR (passed):  {best_ensemble['passed_wr']:.1f}%")
        print(f"    WR (blocked): {best_ensemble['blocked_wr']:.1f}%")
        print(f"    Edge: {best_ensemble['edge']:+.1f}pp")
    else:
        print(f"  No ensemble configuration provides meaningful edge for {symbol}")

    # Compare: regime-only best vs ensemble best
    regime_best = max(
        [r for r in all_results if r["strategy"].startswith("regime")],
        key=lambda r: r["edge"],
        default=None,
    )

    if regime_best and best_ensemble:
        print(f"\n  Regime-only best: {regime_best['strategy']} "
              f"(edge {regime_best['edge']:+.1f}pp)")
        print(f"  Ensemble best:    {best_ensemble['strategy']} "
              f"(edge {best_ensemble['edge']:+.1f}pp)")
        improvement = best_ensemble["edge"] - regime_best["edge"]
        print(f"  Ensemble improvement: {improvement:+.1f}pp")

    return {
        "symbol": symbol,
        "n_oos": n_oos,
        "regime_best": regime_best,
        "ensemble_best": best_ensemble,
        "all_results": all_results,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Ensemble analysis: Regime + Volatility predictor"
    )
    parser.add_argument("--symbol", type=str, default=None,
                        help="Analyze single symbol")
    args = parser.parse_args()

    symbols = [args.symbol] if args.symbol else SYMBOLS

    conn = sqlite3.connect(str(DB_PATH))
    try:
        all_results = {}
        for sym in symbols:
            result = analyze_symbol(conn, sym)
            if result:
                all_results[sym] = result

        # --- Final Summary ---
        if all_results:
            print(f"\n{'='*70}")
            print(f"  FINAL ENSEMBLE SUMMARY")
            print(f"{'='*70}")
            print(f"\n  {'Symbol':10s}  {'N_OOS':>6s}  {'Regime Best':>20s}  "
                  f"{'Ensemble Best':>20s}  {'Δ Edge':>8s}")
            print(f"  {'-'*10}  {'-'*6}  {'-'*20}  {'-'*20}  {'-'*8}")

            for sym, result in all_results.items():
                r_best = result.get("regime_best")
                e_best = result.get("ensemble_best")

                r_str = f"{r_best['edge']:+.1f}pp" if r_best else "N/A"
                e_str = f"{e_best['edge']:+.1f}pp" if e_best else "N/A"

                if r_best and e_best:
                    delta = e_best["edge"] - r_best["edge"]
                    d_str = f"{delta:+.1f}pp"
                else:
                    d_str = "N/A"

                print(f"  {sym:10s}  {result['n_oos']:>6d}  {r_str:>20s}  "
                      f"{e_str:>20s}  {d_str:>8s}")

            print(f"\n  Conclusions:")
            print(f"  • If ensemble edge >> regime-only edge: vol filter adds value")
            print(f"  • If ensemble edge ≈ regime-only edge: vol filter doesn't help")
            print(f"  • Focus on SOL and ETH (the only symbols with regime signal)")
            print(f"  • BTC/BNB regime models are broken, so ensemble won't help them")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
