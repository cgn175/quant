# XGBoost Model Analysis Report

**Date**: 2026-02-09
**Models**: v1 (`trend_ml_filter_v1`)
**Symbols**: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT
**Train Period**: 2020-02 → 2025-06-30 | **Test Period**: 2025-07-01 → 2026-02-08
**Target**: Binary — price >1.5% higher after 4 bars (4H candles = 16 hours ahead)
**Production Threshold**: 0.65 (in `config.yaml`)

---

## Executive Summary

The XGBoost models are **severely overfit and not production-ready**. All four models show:

- **Average OOS AUC: 0.57** (barely above random 0.50)
- **Train AUC: 0.94–0.96 vs Test AUC: 0.54–0.61** — a gap of +0.35 to +0.42
- **At production threshold (0.65)**: only 3.8–5.5% of bars pass, catching just 5–14% of true positives
- **Probabilities are badly miscalibrated**: model says 0.65 but actual positive rate is only 0.27–0.41

**Recommendation**: Keep `ml_filter.enabled: false` in production. The legacy ADX filter is safer. Before enabling ML, the models need fundamental improvements (see "Path Forward" below).

---

## 1. Overfitting Analysis

| Symbol | Train AUC | Test AUC | AUC Gap | Train LogLoss | Test LogLoss | LL Gap | Signal Rate (Train→Test) |
|--------|-----------|----------|---------|---------------|--------------|--------|--------------------------|
| BTCUSDT | 0.963 | 0.610 | +0.353 ⚠️ | 0.419 | 0.534 | +0.115 | 13.3% → 4.6% (0.35x) |
| ETHUSDT | 0.954 | 0.569 | +0.385 ⚠️ | 0.438 | 0.622 | +0.184 | 15.2% → 3.8% (0.25x) |
| SOLUSDT | 0.961 | 0.543 | +0.418 ⚠️ | 0.452 | 0.657 | +0.205 | 16.4% → 5.1% (0.31x) |
| BNBUSDT | 0.942 | 0.562 | +0.380 ⚠️ | 0.431 | 0.599 | +0.168 | 16.5% → 5.5% (0.33x) |

**Root cause**: `max_depth=6` with `n_estimators=200` on ~11K training rows is too complex. The model memorizes training patterns that don't generalize. Signal rate drops 3–4x from train to test, confirming the model's confidence doesn't transfer.

---

## 2. Target Distribution & Class Imbalance

| Symbol | Train Pos% | Test Pos% | Imbalance | Train Mean Ret | Test Mean Ret |
|--------|-----------|-----------|-----------|----------------|---------------|
| BTCUSDT | 21.7% | 13.2% | 1:3.6 | +0.116% | -0.111% |
| ETHUSDT | 27.1% | 25.5% | 1:2.7 | +0.133% | -0.007% |
| SOLUSDT | 33.0% | 28.3% | 1:2.0 | +0.276% | -0.109% |
| BNBUSDT | 24.8% | 21.7% | 1:3.0 | +0.175% | +0.026% |

**Key issue**: BTC positive rate drops from 21.7% (train) to 13.2% (test) — the market regime shifted. The model was trained on a more bullish period than it was tested on. This is a fundamental non-stationarity problem.

---

## 3. Feature Importance (Gain %)

Top 5 features by gain across symbols:

| Rank | BTCUSDT | ETHUSDT | SOLUSDT | BNBUSDT |
|------|---------|---------|---------|---------|
| 1 | dow_sin (9.6%) | volatility_20 (9.6%) | volatility_20 (7.4%) | volatility_20 (12.4%) |
| 2 | volatility_20 (8.5%) | dow_sin (7.6%) | ema_50_distance (6.7%) | dow_cos (7.1%) |
| 3 | ema_50_distance (6.2%) | funding_24h_avg (6.3%) | atr_14 (6.5%) | dow_sin (6.3%) |
| 4 | dow_cos (6.0%) | ema_50_distance (5.7%) | dow_sin (6.4%) | ema_50_distance (6.1%) |
| 5 | atr_14 (5.9%) | atr_14 (5.5%) | bb_width_20 (6.4%) | atr_14 (5.4%) |

**Observations**:
- `volatility_20` is consistently the most important feature — higher volatility correlates with bigger moves (both directions)
- `dow_sin/dow_cos` (day of week) rank surprisingly high — likely noise/overfitting since crypto trades 24/7
- `donchian_breakout` has high cover but very few splits (15–23) — it's used early in trees as a broad filter
- Feature importance is very evenly distributed (no feature dominates >12%) — suggests weak individual signal

---

## 4. Feature Correlation Issues

**8 highly correlated pairs (|r| > 0.7) consistently across all symbols:**

| Pair | Correlation | Issue |
|------|-------------|-------|
| `funding_8h_avg` ↔ `funding_24h_avg` | 0.91–0.94 | Redundant — drop one |
| `returns_4bar` ↔ `ema_9_distance` | 0.88–0.89 | Both measure short-term momentum |
| `returns_20bar` ↔ `ema_50_distance` | 0.87 | Both measure medium-term trend |
| `rsi_14` ↔ `ema_50_distance` | 0.75–0.86 | RSI encodes similar trend info |
| `returns_20bar` ↔ `rsi_14` | 0.73–0.81 | RSI is derived from returns |
| `volatility_20` ↔ `bb_width_20` | 0.78–0.83 | Both measure recent volatility |
| `rsi_14` ↔ `ema_9_distance` | 0.73–0.78 | Overlapping momentum signal |
| `ema_9_distance` ↔ `ema_50_distance` | 0.71–0.72 | Short vs medium EMA distance |

**Impact**: Redundant features waste model capacity and increase overfitting. The 19 features likely carry the information of ~10 independent signals.

---

## 5. Threshold Analysis (OOS)

### At Production Threshold (0.65)

| Symbol | Signals Passed | Signal Rate | Precision | Recall | True Positives Caught |
|--------|---------------|-------------|-----------|--------|----------------------|
| BTCUSDT | 62 / 1,335 | 4.6% | 38.7% | 13.6% | 24 / 176 |
| ETHUSDT | 51 / 1,335 | 3.8% | 49.0% | 7.4% | 25 / 340 |
| SOLUSDT | 68 / 1,335 | 5.1% | 27.9% | 5.0% | 19 / 378 |
| BNBUSDT | 73 / 1,335 | 5.5% | 37.0% | 9.3% | 27 / 290 |

### Best F1 Threshold per Symbol

| Symbol | Best Threshold | Best F1 | Notes |
|--------|---------------|---------|-------|
| BTCUSDT | 0.55 | 0.282 | Only symbol where higher threshold helps |
| ETHUSDT | 0.30 | 0.413 | Model should barely filter at all |
| SOLUSDT | 0.30 | 0.436 | Same — best F1 at lowest threshold |
| BNBUSDT | 0.30 | 0.355 | Same pattern |

**The 0.65 production threshold is too aggressive**. For 3 of 4 symbols, the best F1 is at 0.30 — meaning the model adds the most value by doing very light filtering, not aggressive screening. At 0.65, recall collapses to 5–14%.

---

## 6. Probability Calibration

The models are **systematically overconfident**. When the model predicts probability = X, the actual positive rate is much lower:

| Predicted Prob | Actual Pos Rate (BTC) | Actual Pos Rate (ETH) | Actual Pos Rate (SOL) | Actual Pos Rate (BNB) |
|----------------|----------------------|----------------------|----------------------|----------------------|
| ~0.08–0.15 | 8.4% | 16.8% | 22.2% | 19.8% |
| ~0.30–0.40 | 10.8–13.3% | 26.3–29.3% | 25.1–26.3% | 20.4–27.1% |
| ~0.50–0.52 | 12.0% | 25.1% | 31.7% | 24.0% |
| ~0.63–0.65 | 28.7% | 40.7% | 27.5% | 32.3% |

**Example**: For BTC, when the model says "65% chance of 1.5%+ move", the actual rate is only 28.7%. The model is ~2.3x overconfident.

---

## 7. Monthly AUC Stability (OOS)

| Month | BTC AUC | ETH AUC | SOL AUC | BNB AUC |
|-------|---------|---------|---------|---------|
| 2025-07 | 0.568 | 0.499 | 0.588 | 0.532 |
| 2025-08 | 0.515 | 0.426 | 0.472 | 0.510 |
| 2025-09 | 0.563 | 0.550 | 0.503 | 0.567 |
| 2025-10 | 0.465 | 0.537 | 0.559 | 0.492 |
| 2025-11 | 0.569 | **0.716** | 0.584 | 0.563 |
| 2025-12 | **0.770** | 0.577 | 0.514 | **0.718** |
| 2026-01 | 0.635 | 0.550 | 0.569 | 0.284 |
| 2026-02 | 0.717 | 0.548 | 0.682 | **0.891** |

**Pattern**: AUC swings wildly month-to-month. Some months the model is useful (AUC >0.70), others it's worse than random (AUC <0.50). This instability makes the model unreliable as a persistent filter.

---

## 8. Economic Impact Simulation (OOS)

Simulated future return on Donchian breakout bars, comparing filter strategies:

### BTCUSDT (bearish OOS period)

| Filter | Signals | Avg Return | Win% | Cumulative |
|--------|---------|-----------|------|------------|
| No filter | 137 | -0.229% | 48.2% | -31.32% |
| ADX > 20 | 102 | -0.274% | 46.1% | -27.90% |
| ML >= 0.50 | 54 | +0.062% | 50.0% | +3.35% |
| **ML >= 0.65** | **11** | **+0.277%** | **63.6%** | **+3.05%** |
| ADX + ML | 10 | +0.143% | 60.0% | +1.43% |

### ETHUSDT (flat OOS period)

| Filter | Signals | Avg Return | Win% | Cumulative |
|--------|---------|-----------|------|------------|
| No filter | 132 | +0.422% | 59.8% | +55.77% |
| ADX > 20 | 109 | +0.351% | 58.7% | +38.29% |
| ML >= 0.50 | 37 | +0.477% | 59.5% | +17.65% |
| **ML >= 0.65** | **9** | **+0.730%** | **44.4%** | **+6.57%** |
| ADX + ML | 7 | +1.146% | 57.1% | +8.02% |

### SOLUSDT

| Filter | Signals | Avg Return | Win% | Cumulative |
|--------|---------|-----------|------|------------|
| No filter | 138 | +0.110% | 55.1% | +15.16% |
| ADX > 20 | 97 | +0.181% | 54.6% | +17.55% |
| ML >= 0.50 | 47 | +0.575% | 51.1% | +27.01% |
| **ML >= 0.65** | **17** | **+0.127%** | **35.3%** | **+2.16%** |
| ADX + ML | 13 | +0.955% | 46.2% | +12.42% |

### BNBUSDT (bearish OOS period)

| Filter | Signals | Avg Return | Win% | Cumulative |
|--------|---------|-----------|------|------------|
| No filter | 135 | -0.235% | 46.7% | -31.79% |
| ADX > 20 | 106 | -0.229% | 47.2% | -24.32% |
| ML >= 0.50 | 38 | -0.635% | 44.7% | -24.13% |
| **ML >= 0.65** | **18** | **-0.203%** | **50.0%** | **-3.65%** |
| ADX + ML | 18 | -0.203% | 50.0% | -3.65% |

**Key takeaway**: The ML filter at 0.65 dramatically reduces trade count (from ~130 to ~10-18). On BTC it turns a -31% period into +3%, but on ETH it reduces a +56% opportunity to just +6.5%. The filter is **too aggressive** — it blocks good trades along with bad ones.

**The sweet spot appears to be ML >= 0.50**, which improves avg return while keeping enough signal volume. But this is a small-sample observation (7 months OOS) and may not persist.

---

## 9. Diagnosis: Why the Models Underperform

### Problem 1: Severe Overfitting
- **max_depth=6** with 200 trees on 10–12K rows is too complex
- Train AUC 0.96 vs Test AUC 0.57 = model memorized training data
- Fix: reduce to max_depth=3, n_estimators=100, add regularization (reg_alpha, reg_lambda)

### Problem 2: Target is Poorly Defined
- "Price >1.5% in 16 hours" is a directional prediction, but features are mostly regime indicators (volatility, trend strength)
- The features describe "is the market trending?" not "will price go up?"
- Fix: Redefine target as "was this a profitable Donchian entry?" using actual backtest outcomes

### Problem 3: Feature Redundancy
- 8 pairs with |r| > 0.7 — effectively 19 features carry ~10 signals
- Redundancy wastes splits and encourages overfitting
- Fix: Drop one from each correlated pair, or use PCA

### Problem 4: Scale_pos_weight with Imbalanced Classes
- Using `scale_pos_weight` amplifies noise in the minority class
- Combined with deep trees, it memorizes rare positive patterns
- Fix: Use class_weight balanced + shallower trees, or use ranking objectives

### Problem 5: No Early Stopping
- Training uses eval_set but doesn't configure `early_stopping_rounds`
- All 200 trees are used even when validation loss plateaus
- Fix: Add `early_stopping_rounds=20`

### Problem 6: Non-Stationary Market
- BTC positive rate drops from 21.7% to 13.2% between train and test
- The 2020–2025 training period includes very different regimes
- Fix: Use shorter training windows (2–3 years), or weight recent data more heavily

---

## 10. Path Forward: Recommendations

### Immediate (keep ML disabled)
1. **Keep `ml_filter.enabled: false`** — the ADX filter is more reliable
2. The bot continues paper trading with the proven mechanical system

### Short-term (v2 model improvements)
1. **Reduce model complexity**: `max_depth=3`, `n_estimators=100`, `early_stopping_rounds=20`
2. **Deduplicate features**: Drop `funding_8h_avg` (keep 24h), drop `ema_9_distance` (keep 50), drop `bb_width_20` (keep volatility_20), drop `returns_20bar` (keep ema_50_distance) → 15 features
3. **Add early stopping**: `model.fit(..., early_stopping_rounds=20)`
4. **Calibrate probabilities**: Apply Platt scaling or isotonic regression post-training
5. **Lower production threshold to 0.50** if models improve — 0.65 kills too many signals

### Medium-term (v3 fundamental rethink)
1. **Redefine target**: Instead of "price >1.5%", use actual strategy outcomes — "would this Donchian breakout have been a winning trade?"
2. **Add cross-asset features**: BTC returns/volatility as features for ETH/SOL/BNB
3. **Use shorter training window**: Last 2–3 years only, with sample weights decaying by age
4. **Try LightGBM**: Often better regularization than XGBoost for small datasets
5. **Consider a rejection model**: Instead of predicting direction, predict "is this entry likely to be stopped out quickly?" (easier target)

---

## Appendix: Analysis Script

The full analysis was generated by `ml/analyze_models.py`. Run:

```bash
python3 ml/analyze_models.py
```

Produces all tables above plus ASCII histogram distributions and calibration curves.
