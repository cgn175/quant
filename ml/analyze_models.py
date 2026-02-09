#!/usr/bin/env python3
"""Deep analysis of trained XGBoost trend-filter models.

Produces:
1. Feature importance analysis (gain, cover, weight)
2. Class imbalance & target distribution
3. Probability calibration curves
4. Precision-Recall at multiple thresholds (especially 0.65 used in prod)
5. Per-symbol OOS equity curve simulation
6. Feature correlation analysis
7. Temporal stability analysis (monthly AUC)
8. SHAP summary (if shap installed)

Usage:
    python3 ml/analyze_models.py
"""

from __future__ import annotations

import json
import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.metrics import (
    auc,
    brier_score_loss,
    classification_report,
    confusion_matrix,
    log_loss,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)
from xgboost import XGBClassifier

from features import FEATURE_NAMES, build_features

warnings.filterwarnings("ignore", category=FutureWarning)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "training.db"
MODEL_DIR = Path(__file__).resolve().parent / "models"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
TRAIN_CUTOFF = pd.Timestamp("2025-07-01", tz="UTC")
TARGET_HORIZON = 4
TARGET_THRESHOLD = 0.015
PROD_THRESHOLD = 0.65  # The threshold used in config.yaml


def load_data(conn: sqlite3.Connection, symbol: str) -> pd.DataFrame:
    """Load candles + funding, build features, add target."""
    candles = pd.read_sql_query(
        "SELECT open_time, open, high, low, close, volume FROM candles "
        "WHERE symbol = ? AND is_closed = 1 ORDER BY open_time",
        conn, params=(symbol,),
    )
    candles["timestamp"] = pd.to_datetime(candles["open_time"], unit="ms", utc=True)
    candles = candles.set_index("timestamp").drop(columns=["open_time"])

    funding = pd.read_sql_query(
        "SELECT timestamp, funding_rate FROM funding WHERE symbol = ? ORDER BY timestamp",
        conn, params=(symbol,),
    )
    funding["timestamp"] = pd.to_datetime(funding["timestamp"], unit="ms", utc=True)
    funding = funding.set_index("timestamp")

    df = candles.copy()
    df["funding_rate"] = funding["funding_rate"].reindex(df.index, method="ffill")
    df = build_features(df)

    future_ret = df["close"].shift(-TARGET_HORIZON) / df["close"] - 1
    df["target"] = (future_ret > TARGET_THRESHOLD).astype(float)
    df["future_return"] = future_ret

    df = df.dropna(subset=FEATURE_NAMES + ["target"])
    return df


def load_model(symbol: str) -> XGBClassifier:
    model = XGBClassifier()
    model.load_model(str(MODEL_DIR / f"{symbol}.json"))
    return model


def analyze_target_distribution(df: pd.DataFrame, symbol: str):
    """Analyze class imbalance."""
    train = df[df.index < TRAIN_CUTOFF]
    test = df[df.index >= TRAIN_CUTOFF]

    print(f"\n{'='*70}")
    print(f"  TARGET DISTRIBUTION: {symbol}")
    print(f"{'='*70}")
    print(f"  Train  ({train.index.min().date()} → {train.index.max().date()}):")
    print(f"    Total: {len(train):,}  |  Pos: {int(train['target'].sum()):,}  "
          f"({train['target'].mean()*100:.1f}%)  |  Neg: {int((1-train['target']).sum()):,}  "
          f"({(1-train['target']).mean()*100:.1f}%)")
    print(f"    Imbalance ratio: 1:{(1-train['target']).sum()/max(train['target'].sum(),1):.1f}")
    print(f"  Test   ({test.index.min().date()} → {test.index.max().date()}):")
    print(f"    Total: {len(test):,}  |  Pos: {int(test['target'].sum()):,}  "
          f"({test['target'].mean()*100:.1f}%)  |  Neg: {int((1-test['target']).sum()):,}  "
          f"({(1-test['target']).mean()*100:.1f}%)")

    # Future return distribution
    print(f"\n  Future Return Stats (4-bar horizon):")
    print(f"    Train mean: {train['future_return'].mean()*100:.3f}%  "
          f"std: {train['future_return'].std()*100:.3f}%")
    print(f"    Test  mean: {test['future_return'].mean()*100:.3f}%  "
          f"std: {test['future_return'].std()*100:.3f}%")
    print(f"    Test  median: {test['future_return'].median()*100:.3f}%")


def analyze_feature_importance(model: XGBClassifier, symbol: str):
    """Multi-metric feature importance."""
    print(f"\n{'='*70}")
    print(f"  FEATURE IMPORTANCE: {symbol}")
    print(f"{'='*70}")

    # Get all importance types — XGBoost uses feature names when trained with DataFrame
    booster = model.get_booster()
    gain = booster.get_score(importance_type="gain")
    cover = booster.get_score(importance_type="cover")
    weight = booster.get_score(importance_type="weight")

    rows = []
    for name in FEATURE_NAMES:
        # XGBoost may use the feature name directly or f{i} format
        key_name = name
        key_idx = f"f{FEATURE_NAMES.index(name)}"
        rows.append({
            "feature": name,
            "gain": gain.get(key_name, gain.get(key_idx, 0)),
            "cover": cover.get(key_name, cover.get(key_idx, 0)),
            "weight": weight.get(key_name, weight.get(key_idx, 0)),
        })

    imp_df = pd.DataFrame(rows)

    # Normalize
    for col in ["gain", "cover", "weight"]:
        total = imp_df[col].sum()
        if total > 0:
            imp_df[f"{col}_pct"] = imp_df[col] / total * 100

    imp_df = imp_df.sort_values("gain", ascending=False)

    print(f"\n  {'Feature':<25s}  {'Gain%':>8s}  {'Cover%':>8s}  {'Weight%':>8s}  {'Splits':>7s}")
    print(f"  {'-'*25}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*7}")
    for _, row in imp_df.iterrows():
        print(f"  {row['feature']:<25s}  {row.get('gain_pct',0):>7.1f}%  "
              f"{row.get('cover_pct',0):>7.1f}%  {row.get('weight_pct',0):>7.1f}%  "
              f"{int(row['weight']):>7d}")

    # Identify dead features (zero importance)
    dead = imp_df[imp_df["gain"] == 0]["feature"].tolist()
    if dead:
        print(f"\n  ⚠️  Dead features (zero gain): {dead}")

    return imp_df


def analyze_threshold_sweep(y_true, y_proba, symbol: str):
    """Precision/Recall/F1/Trade count at various thresholds."""
    print(f"\n{'='*70}")
    print(f"  THRESHOLD ANALYSIS (OOS): {symbol}")
    print(f"{'='*70}")

    thresholds = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]

    print(f"\n  {'Thresh':>7s}  {'Prec':>7s}  {'Recall':>7s}  {'F1':>7s}  "
          f"{'Pred+':>7s}  {'TP':>5s}  {'FP':>5s}  {'Blocked%':>9s}")
    print(f"  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*5}  {'-'*5}  {'-'*9}")

    best_f1 = 0
    best_thresh = 0.5

    for t in thresholds:
        y_pred = (y_proba >= t).astype(int)
        tp = int(((y_pred == 1) & (y_true == 1)).sum())
        fp = int(((y_pred == 1) & (y_true == 0)).sum())
        fn = int(((y_pred == 0) & (y_true == 1)).sum())
        pred_pos = int(y_pred.sum())
        total = len(y_true)

        prec = tp / max(tp + fp, 1)
        rec = tp / max(tp + fn, 1)
        f1 = 2 * prec * rec / max(prec + rec, 1e-9)
        blocked_pct = (1 - pred_pos / total) * 100

        marker = " ← PROD" if t == PROD_THRESHOLD else ""
        if f1 > best_f1:
            best_f1 = f1
            best_thresh = t

        print(f"  {t:>7.2f}  {prec:>7.3f}  {rec:>7.3f}  {f1:>7.3f}  "
              f"{pred_pos:>7d}  {tp:>5d}  {fp:>5d}  {blocked_pct:>8.1f}%{marker}")

    print(f"\n  Best F1 threshold: {best_thresh:.2f} (F1={best_f1:.3f})")

    # At production threshold
    y_pred_prod = (y_proba >= PROD_THRESHOLD).astype(int)
    pred_pos = int(y_pred_prod.sum())
    total_pos = int(y_true.sum())
    print(f"\n  At PROD threshold ({PROD_THRESHOLD}):")
    print(f"    Signals passed: {pred_pos}/{len(y_true)} ({pred_pos/len(y_true)*100:.1f}%)")
    print(f"    True positives caught: {int(((y_pred_prod==1)&(y_true==1)).sum())}/{total_pos} "
          f"({int(((y_pred_prod==1)&(y_true==1)).sum())/max(total_pos,1)*100:.1f}%)")

    return best_thresh


def analyze_calibration(y_true, y_proba, symbol: str):
    """Probability calibration analysis."""
    print(f"\n{'='*70}")
    print(f"  PROBABILITY CALIBRATION (OOS): {symbol}")
    print(f"{'='*70}")

    brier = brier_score_loss(y_true, y_proba)
    ll = log_loss(y_true, y_proba)

    print(f"  Brier Score: {brier:.4f}  (lower = better, random = 0.25)")
    print(f"  Log Loss:    {ll:.4f}")

    # Calibration bins
    try:
        prob_true, prob_pred = calibration_curve(y_true, y_proba, n_bins=8, strategy="quantile")
        print(f"\n  {'Predicted':>10s}  {'Actual':>10s}  {'Diff':>10s}")
        print(f"  {'-'*10}  {'-'*10}  {'-'*10}")
        for pt, pp in zip(prob_true, prob_pred):
            diff = pt - pp
            print(f"  {pp:>10.3f}  {pt:>10.3f}  {diff:>+10.3f}")
    except ValueError:
        print("  (Not enough data for calibration curve)")

    # Probability distribution
    bins = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    counts, _ = np.histogram(y_proba, bins=bins)
    print(f"\n  Probability Distribution:")
    for i in range(len(counts)):
        bar = "█" * int(counts[i] / max(counts) * 30)
        print(f"    [{bins[i]:.1f}-{bins[i+1]:.1f}): {counts[i]:>6d}  {bar}")


def analyze_monthly_stability(df: pd.DataFrame, y_proba: np.ndarray, symbol: str):
    """Monthly AUC/precision stability on OOS."""
    test = df[df.index >= TRAIN_CUTOFF].copy()
    test = test.iloc[:len(y_proba)]  # align
    test["proba"] = y_proba

    print(f"\n{'='*70}")
    print(f"  MONTHLY STABILITY (OOS): {symbol}")
    print(f"{'='*70}")

    print(f"\n  {'Month':>10s}  {'N':>6s}  {'Pos%':>6s}  {'AUC':>7s}  "
          f"{'P@0.65':>7s}  {'Sigs':>6s}")
    print(f"  {'-'*10}  {'-'*6}  {'-'*6}  {'-'*7}  {'-'*7}  {'-'*6}")

    for month, group in test.groupby(test.index.to_period("M")):
        n = len(group)
        pos_pct = group["target"].mean() * 100
        try:
            month_auc = roc_auc_score(group["target"], group["proba"])
        except ValueError:
            month_auc = float("nan")

        pred_65 = (group["proba"] >= PROD_THRESHOLD).astype(int)
        tp = int(((pred_65 == 1) & (group["target"] == 1)).sum())
        fp = int(((pred_65 == 1) & (group["target"] == 0)).sum())
        prec_65 = tp / max(tp + fp, 1)
        sigs = int(pred_65.sum())

        print(f"  {str(month):>10s}  {n:>6d}  {pos_pct:>5.1f}%  {month_auc:>7.3f}  "
              f"{prec_65:>7.3f}  {sigs:>6d}")


def analyze_feature_correlations(df: pd.DataFrame, symbol: str):
    """Feature correlation with target and inter-feature redundancy."""
    print(f"\n{'='*70}")
    print(f"  FEATURE-TARGET CORRELATION (Training): {symbol}")
    print(f"{'='*70}")

    train = df[df.index < TRAIN_CUTOFF]
    corr = train[FEATURE_NAMES + ["target"]].corr()["target"].drop("target")
    corr = corr.abs().sort_values(ascending=False)

    print(f"\n  {'Feature':<25s}  {'|corr|':>8s}")
    print(f"  {'-'*25}  {'-'*8}")
    for feat, c in corr.items():
        bar = "█" * int(c * 50)
        print(f"  {feat:<25s}  {c:>8.4f}  {bar}")

    # Inter-feature correlation (identify redundant pairs)
    feat_corr = train[FEATURE_NAMES].corr()
    high_corr = []
    for i in range(len(FEATURE_NAMES)):
        for j in range(i+1, len(FEATURE_NAMES)):
            c = abs(feat_corr.iloc[i, j])
            if c > 0.7:
                high_corr.append((FEATURE_NAMES[i], FEATURE_NAMES[j], c))

    if high_corr:
        high_corr.sort(key=lambda x: -x[2])
        print(f"\n  ⚠️  Highly Correlated Feature Pairs (|r| > 0.7):")
        for f1, f2, c in high_corr:
            print(f"    {f1} ↔ {f2}: {c:.3f}")
    else:
        print(f"\n  ✅  No highly correlated feature pairs (|r| > 0.7)")


def analyze_profit_impact(df: pd.DataFrame, y_proba: np.ndarray, symbol: str):
    """Simulate the economic impact of the ML filter vs no filter."""
    test = df[df.index >= TRAIN_CUTOFF].copy()
    test = test.iloc[:len(y_proba)]
    test["proba"] = y_proba

    print(f"\n{'='*70}")
    print(f"  ECONOMIC IMPACT SIMULATION (OOS): {symbol}")
    print(f"{'='*70}")

    # Only look at bars where donchian_breakout != 0 (actual entry signals)
    breakout_bars = test[test["donchian_breakout"] != 0].copy()
    all_bars = test.copy()

    # For each threshold, compute avg future return of passed signals
    print(f"\n  Scenario: What if we only take entries when model prob >= threshold?")
    print(f"  (Using 4-bar future return as proxy for trade outcome)")
    print(f"\n  {'Filter':>20s}  {'Signals':>8s}  {'Avg Ret':>8s}  {'Pos%':>6s}  "
          f"{'Cum Ret':>8s}")
    print(f"  {'-'*20}  {'-'*8}  {'-'*8}  {'-'*6}  {'-'*8}")

    # No filter (all breakout bars)
    if len(breakout_bars) > 0:
        avg_ret = breakout_bars["future_return"].mean() * 100
        pos_pct = (breakout_bars["future_return"] > 0).mean() * 100
        cum_ret = breakout_bars["future_return"].sum() * 100
        print(f"  {'No filter':<20s}  {len(breakout_bars):>8d}  {avg_ret:>7.3f}%  "
              f"{pos_pct:>5.1f}%  {cum_ret:>7.2f}%")

    # ADX > 20 only
    adx_bars = breakout_bars[breakout_bars["adx_14"] > 20]
    if len(adx_bars) > 0:
        avg_ret = adx_bars["future_return"].mean() * 100
        pos_pct = (adx_bars["future_return"] > 0).mean() * 100
        cum_ret = adx_bars["future_return"].sum() * 100
        print(f"  {'ADX > 20':<20s}  {len(adx_bars):>8d}  {avg_ret:>7.3f}%  "
              f"{pos_pct:>5.1f}%  {cum_ret:>7.2f}%")

    # ML filter at various thresholds
    for thresh in [0.40, 0.50, 0.60, PROD_THRESHOLD, 0.70]:
        ml_bars = breakout_bars[breakout_bars["proba"] >= thresh]
        if len(ml_bars) > 0:
            avg_ret = ml_bars["future_return"].mean() * 100
            pos_pct = (ml_bars["future_return"] > 0).mean() * 100
            cum_ret = ml_bars["future_return"].sum() * 100
            label = f"ML >= {thresh:.2f}"
            if thresh == PROD_THRESHOLD:
                label += " (PROD)"
            print(f"  {label:<20s}  {len(ml_bars):>8d}  {avg_ret:>7.3f}%  "
                  f"{pos_pct:>5.1f}%  {cum_ret:>7.2f}%")
        else:
            label = f"ML >= {thresh:.2f}"
            if thresh == PROD_THRESHOLD:
                label += " (PROD)"
            print(f"  {label:<20s}  {'0':>8s}  {'N/A':>8s}  {'N/A':>6s}  {'N/A':>8s}")

    # Combined: ADX > 20 AND ML >= 0.65
    combo = breakout_bars[(breakout_bars["adx_14"] > 20) & (breakout_bars["proba"] >= PROD_THRESHOLD)]
    if len(combo) > 0:
        avg_ret = combo["future_return"].mean() * 100
        pos_pct = (combo["future_return"] > 0).mean() * 100
        cum_ret = combo["future_return"].sum() * 100
        print(f"  {'ADX+ML combined':<20s}  {len(combo):>8d}  {avg_ret:>7.3f}%  "
              f"{pos_pct:>5.1f}%  {cum_ret:>7.2f}%")


def analyze_confusion_detail(y_true, y_proba, symbol: str):
    """Detailed confusion matrix at production threshold."""
    print(f"\n{'='*70}")
    print(f"  CONFUSION MATRIX @ {PROD_THRESHOLD} (OOS): {symbol}")
    print(f"{'='*70}")

    y_pred = (y_proba >= PROD_THRESHOLD).astype(int)
    cm = confusion_matrix(y_true, y_pred)

    if cm.shape == (2, 2):
        tn, fp, fn, tp = cm.ravel()
        total = len(y_true)
        print(f"\n                  Predicted")
        print(f"                  Neg      Pos")
        print(f"  Actual Neg    {tn:>6d}   {fp:>6d}   ({tn+fp:,} actual negatives)")
        print(f"  Actual Pos    {fn:>6d}   {tp:>6d}   ({fn+tp:,} actual positives)")
        print(f"\n  TPR (Sensitivity): {tp/max(tp+fn,1):.3f}")
        print(f"  TNR (Specificity): {tn/max(tn+fp,1):.3f}")
        print(f"  PPV (Precision):   {tp/max(tp+fp,1):.3f}")
        print(f"  NPV:               {tn/max(tn+fn,1):.3f}")
        print(f"  FPR:               {fp/max(fp+tn,1):.3f}")
        print(f"  Signal Rate:       {(tp+fp)/total*100:.1f}%  ({tp+fp}/{total})")
    else:
        print(f"  Confusion matrix shape unexpected: {cm.shape}")
        print(f"  (Model may predict only one class at this threshold)")
        print(f"  Predictions: {int(y_pred.sum())} positive out of {len(y_pred)}")


def analyze_overfitting(model: XGBClassifier, X_train, y_train, X_test, y_test, symbol: str):
    """Compare train vs test performance to detect overfitting."""
    print(f"\n{'='*70}")
    print(f"  OVERFITTING CHECK: {symbol}")
    print(f"{'='*70}")

    train_proba = model.predict_proba(X_train)[:, 1]
    test_proba = model.predict_proba(X_test)[:, 1]

    try:
        train_auc = roc_auc_score(y_train, train_proba)
    except ValueError:
        train_auc = 0.0
    try:
        test_auc = roc_auc_score(y_test, test_proba)
    except ValueError:
        test_auc = 0.0

    train_ll = log_loss(y_train, train_proba)
    test_ll = log_loss(y_test, test_proba)

    auc_gap = train_auc - test_auc
    ll_gap = test_ll - train_ll

    print(f"\n  {'Metric':<20s}  {'Train':>10s}  {'Test':>10s}  {'Gap':>10s}  {'Verdict':>12s}")
    print(f"  {'-'*20}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*12}")

    auc_verdict = "⚠️ OVERFIT" if auc_gap > 0.10 else ("🟡 Mild" if auc_gap > 0.05 else "✅ OK")
    print(f"  {'AUC':<20s}  {train_auc:>10.4f}  {test_auc:>10.4f}  {auc_gap:>+10.4f}  {auc_verdict:>12s}")

    ll_verdict = "⚠️ OVERFIT" if ll_gap > 0.10 else ("🟡 Mild" if ll_gap > 0.05 else "✅ OK")
    print(f"  {'Log Loss':<20s}  {train_ll:>10.4f}  {test_ll:>10.4f}  {ll_gap:>+10.4f}  {ll_verdict:>12s}")

    # Train accuracy at production threshold
    train_pred = (train_proba >= PROD_THRESHOLD).astype(int)
    test_pred = (test_proba >= PROD_THRESHOLD).astype(int)

    train_signals = int(train_pred.sum())
    test_signals = int(test_pred.sum())
    train_signal_rate = train_signals / len(train_pred) * 100
    test_signal_rate = test_signals / len(test_pred) * 100

    print(f"\n  Signal Rate @ {PROD_THRESHOLD}:")
    print(f"    Train: {train_signals:,} / {len(train_pred):,} ({train_signal_rate:.1f}%)")
    print(f"    Test:  {test_signals:,} / {len(test_pred):,} ({test_signal_rate:.1f}%)")
    if train_signal_rate > 0:
        rate_ratio = test_signal_rate / train_signal_rate
        print(f"    Ratio: {rate_ratio:.2f}x  {'(stable)' if 0.5 < rate_ratio < 2.0 else '⚠️ unstable'}")


def main():
    conn = sqlite3.connect(str(DB_PATH))

    all_results = {}

    try:
        for symbol in SYMBOLS:
            print(f"\n\n{'#'*70}")
            print(f"{'#'*70}")
            print(f"  ANALYZING: {symbol}")
            print(f"{'#'*70}")
            print(f"{'#'*70}")

            # Load data
            df = load_data(conn, symbol)
            model = load_model(symbol)

            train_mask = df.index < TRAIN_CUTOFF
            X_train = df[train_mask][FEATURE_NAMES]
            y_train = df[train_mask]["target"]
            X_test = df[~train_mask][FEATURE_NAMES]
            y_test = df[~train_mask]["target"]

            y_proba = model.predict_proba(X_test)[:, 1]

            # 1. Target distribution
            analyze_target_distribution(df, symbol)

            # 2. Feature importance
            imp_df = analyze_feature_importance(model, symbol)

            # 3. Overfitting check
            analyze_overfitting(model, X_train, y_train, X_test, y_test, symbol)

            # 4. Threshold sweep
            best_thresh = analyze_threshold_sweep(y_test.values, y_proba, symbol)

            # 5. Calibration
            analyze_calibration(y_test.values, y_proba, symbol)

            # 6. Confusion matrix
            analyze_confusion_detail(y_test.values, y_proba, symbol)

            # 7. Monthly stability
            analyze_monthly_stability(df, y_proba, symbol)

            # 8. Feature correlations
            analyze_feature_correlations(df, symbol)

            # 9. Economic impact
            analyze_profit_impact(df, y_proba, symbol)

            all_results[symbol] = {
                "test_auc": roc_auc_score(y_test, y_proba),
                "best_thresh": best_thresh,
                "n_test": len(y_test),
                "pos_rate": y_test.mean(),
            }

        # Final summary
        print(f"\n\n{'='*70}")
        print(f"  CROSS-SYMBOL SUMMARY")
        print(f"{'='*70}")
        print(f"\n  {'Symbol':<10s}  {'AUC':>7s}  {'Best Th':>8s}  {'Test N':>8s}  {'Pos%':>6s}")
        print(f"  {'-'*10}  {'-'*7}  {'-'*8}  {'-'*8}  {'-'*6}")
        for sym, r in all_results.items():
            print(f"  {sym:<10s}  {r['test_auc']:>7.4f}  {r['best_thresh']:>8.2f}  "
                  f"{r['n_test']:>8,}  {r['pos_rate']*100:>5.1f}%")

        print(f"\n  Key Findings:")
        avg_auc = np.mean([r["test_auc"] for r in all_results.values()])
        print(f"    Average OOS AUC: {avg_auc:.4f}  {'(weak - barely above random)' if avg_auc < 0.60 else '(moderate)' if avg_auc < 0.70 else '(good)'}")
        print(f"    Production threshold: {PROD_THRESHOLD} — check if any symbol has useful signals at this level")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
