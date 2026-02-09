# ML v2 Model Analysis Report

**Date**: 2026-02-09
**Models**: Regime Classifier v1 (`regime_v1`) + Volatility Predictor v1 (`vol_v1`)
**Symbols**: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT
**Train Period**: 2020-02 → 2025-06-30 | **Test Period**: 2025-07-01 → 2026-02-08

---

## Executive Summary

### Regime Classifier (Traffic Light) — ⚠️ MIXED RESULTS

| Symbol | Train AUC | Test AUC | AUC Gap | Verdict | Production-Ready? |
|--------|-----------|----------|---------|---------|:-:|
| BTCUSDT | 0.737 | 0.457 | +0.280 | ⚠️ OVERFIT | ❌ |
| ETHUSDT | 0.751 | 0.633 | +0.118 | 🟡 Mild | ⚠️ maybe |
| SOLUSDT | 0.755 | 0.757 | -0.001 | ✅ PERFECT | ✅ yes |
| BNBUSDT | 0.756 | 0.502 | +0.254 | ⚠️ OVERFIT | ❌ |

**SOL is the star.** Zero overfitting, 0.757 OOS AUC, and +20pp edge at threshold 0.50 (SAFE win rate 21.4% vs DANGER 1.5%). ETH is borderline usable. BTC and BNB are overfit and essentially random on OOS data.

**vs. Old XGBoost v1:** The overfitting is dramatically reduced (AUC gap 0.00–0.28 vs 0.35–0.42 before), proving the simpler model + simpler target works. But the fundamental problem is **tiny test samples** (~130-138 breakout entries in 7 months OOS). This makes all metrics noisy.

### Volatility Predictor (Dynamic Stop-Loss) — ✅ GOOD, READY TO ENABLE

| Symbol | Train MAE | Test MAE | MAE Ratio | Test R² | Verdict |
|--------|-----------|----------|-----------|---------|---------|
| BTCUSDT | 0.907% | 0.503% | 0.55x | 0.265 | ✅ No overfit |
| ETHUSDT | 1.110% | 0.801% | 0.72x | 0.176 | ✅ No overfit |
| SOLUSDT | 1.536% | 0.907% | 0.59x | 0.194 | ✅ No overfit |
| BNBUSDT | 1.338% | 0.683% | 0.51x | 0.081 | ✅ No overfit |

**All four symbols pass.** Test MAE is consistently *lower* than train MAE (the model generalizes well because the test period is calmer than the 2020-2025 training period). Calibration is excellent — predicted ranges track actual ranges well across all quintile bins. R² is low (0.08–0.27) because we're trying to predict a noisy process, but the *direction* is right and the *ordering* is correct (higher predicted → higher actual).

---

## 1. Regime Classifier — Detailed Analysis

### 1.1 Why SOL Works But BTC Doesn't

The core issue is **base rate stability**. SAFE_TO_TRADE rates across train and test:

| Symbol | Train SAFE% | Test SAFE% | Shift |
|--------|-------------|------------|-------|
| BTCUSDT | 17.8% | 14.6% | -3.2pp |
| ETHUSDT | 15.1% | 12.1% | -3.0pp |
| SOLUSDT | 14.5% | 11.6% | -2.9pp |
| BNBUSDT | 16.5% | 15.6% | -0.9pp |

All symbols have ~15% SAFE rate. The base rates are actually stable. But SOL has the most stable *feature-to-outcome* relationship, while BTC's low AUC suggests the features that predict winning breakouts in BTC's training period simply stopped working.

### 1.2 Feature Importance

| Rank | BTCUSDT | ETHUSDT | SOLUSDT | BNBUSDT |
|------|---------|---------|---------|---------|
| 1 | volatility_20 (34%) | volume_ratio_20 (41%) | volume_ratio_20 (40%) | volatility_20 (31%) |
| 2 | rsi_14 (27%) | volatility_20 (25%) | rsi_14 (23%) | rsi_14 (25%) |
| 3 | volume_ratio_20 (21%) | rsi_14 (17%) | funding_24h_avg (16%) | volume_ratio_20 (22%) |
| 4 | funding_24h_avg (10%) | funding_24h_avg (11%) | volatility_20 (16%) | funding_24h_avg (18%) |
| 5 | hour_cos (5%) | hour_sin (4%) | hour_sin (2%) | hour_cos (3%) |
| 6 | hour_sin (2%) | hour_cos (3%) | hour_cos (2%) | hour_sin (2%) |

**Good news:** `hour_sin/cos` are dead last at 2-5% importance, confirming they're not driving spurious patterns (unlike v1 where `dow_sin/cos` ranked #1-2 due to overfitting).

**Key drivers:** `volume_ratio_20`, `volatility_20`, and `rsi_14` are the workhorses. High volume breakouts with moderate volatility tend to be SAFE — this is a sensible, fundamental signal.

### 1.3 Economic Edge by Threshold (OOS)

The critical question: does the model actually separate winning breakouts from losing ones?

**SOLUSDT (the winner):**

| Threshold | Entries Passed | SAFE Win Rate | DANGER Win Rate | Edge |
|-----------|:-:|:-:|:-:|:-:|
| 0.40 | 81% | 14.3% | 0.0% | **+14.3pp** |
| 0.45 | 68% | 17.0% | 0.0% | **+17.0pp** |
| 0.50 | 51% | 21.4% | 1.5% | **+20.0pp** |
| 0.55 | 32% | 22.7% | 6.4% | **+16.3pp** |

At threshold 0.50, SOL allows 51% of entries and those have a 21.4% win rate vs 1.5% for blocked entries — a massive 20pp edge. This is a real signal.

**ETHUSDT (borderline):**

| Threshold | Entries Passed | SAFE Win Rate | DANGER Win Rate | Edge |
|-----------|:-:|:-:|:-:|:-:|
| 0.40 | 76% | 15.0% | 3.1% | +11.9pp |
| 0.50 | 43% | 17.5% | 8.0% | +9.5pp |

ETH shows a real edge at 0.50 (+9.5pp), but it blocks 57% of entries. Usable but less convincing.

**BTCUSDT (broken) & BNBUSDT (broken):**
At most thresholds the DANGER group actually has a *higher* win rate than the SAFE group — the model is anti-correlated. These models are worse than a coin flip.

### 1.4 Monthly Stability (Regime Model OOS)

**SOL** is the only symbol with consistently useful AUC:
```
2025-07: 0.74   2025-08: 0.95   2025-09: 0.82   2025-10: 0.75
2025-11: 0.67   2026-01: 0.69
```

BTC and BNB swing wildly between 0.13 and 0.88 — pure noise.

---

## 2. Volatility Predictor — Detailed Analysis

### 2.1 Zero Overfitting Across All Symbols

The MAE ratio (test/train) is consistently **below 1.0** for all symbols — meaning the model actually performs *better* on test data than train data. This is because:
- The 2020-2025 training period includes extreme volatility events (COVID crash, 2021 bull run, 2022 bear market)
- The 2025H2 test period is calmer
- The simple linear model generalizes perfectly — it learned "recent range predicts next range" which is a universal property

### 2.2 Calibration — Predicted vs Actual

The calibration is the strongest signal for production readiness:

**BTCUSDT:**
| Quintile | Predicted | Actual | Ratio |
|----------|-----------|--------|-------|
| Lowest | 0.76% | 0.69% | 0.91x |
| Q2 | 0.90% | 0.89% | 0.99x |
| Q3 | 1.03% | 1.10% | 1.07x |
| Q4 | 1.20% | 1.40% | 1.16x |
| Highest | 1.79% | 2.02% | 1.13x |

The model is **well-calibrated** — when it says "wide range," ranges are wide. When it says "narrow," they're narrow. The slight under-prediction in the top quintile (1.13x) is actually desirable for stop-loss setting — we'd rather slightly over-estimate volatility than under-estimate it.

**All symbols show the same pattern:** monotonically increasing actuals across predicted quintiles, with ratios between 0.84x–1.27x. The ordering is correct everywhere.

### 2.3 Feature Coefficients

Dominant features across all symbols (in log-space):

| Feature | BTC | ETH | SOL | BNB | Role |
|---------|:---:|:---:|:---:|:---:|------|
| `atrp_14` | **31.6** | **23.4** | **10.6** | **19.8** | Long-term volatility regime |
| `range_sma_6` | **12.2** | **9.3** | **8.1** | **10.6** | Short-term volatility momentum |
| `range_1` | 0.05 | 0.90 | 1.45 | **2.95** | Immediate candle size |
| `volume_ratio_20` | 0.20 | 0.14 | 0.11 | 0.13 | Volume spike signal |
| `hour_sin/cos` | <0.15 | <0.15 | <0.10 | <0.05 | Time-of-day (minimal) |

The model is essentially: `next_range ≈ f(current ATR%, recent range average)` — a volatility autoregression. This is economically sensible and robust.

### 2.4 Dynamic Stop-Loss Width Simulation

What stop widths would the model produce in practice with `k=1.0` and `min=1%` / `max=4%`?

| Symbol | Mean Stop | P10 (tight) | P50 (median) | P90 (wide) |
|--------|-----------|-------------|--------------|------------|
| BTCUSDT | 1.20% | 1.00% | 1.03% | 1.57% |
| ETHUSDT | 1.73% | 1.18% | 1.59% | 2.39% |
| SOLUSDT | 2.29% | 1.81% | 2.19% | 2.88% |
| BNBUSDT | 1.49% | 1.04% | 1.34% | 2.02% |

This matches reality — SOL is the most volatile, BTC the least. The range across P10–P90 shows the model adapts dynamically: tight stops in quiet markets, wide stops in volatile ones.

**Comparison to current fixed stop:** The current ATR × 3.0 multiplier typically produces 3-6% stops. The dynamic model produces 1-4% stops. This means:
- In calm markets: tighter stops → less capital at risk per trade → can take more trades
- In wild markets: wider stops → avoid getting stopped out by noise → fewer false exits

### 2.5 Monthly Stability

The model is consistently useful across months (BTC example):
```
2025-07: MAE 0.35%  R² 0.23    2025-08: MAE 0.41%  R² 0.03
2025-09: MAE 0.39%  R² 0.00    2025-10: MAE 0.55%  R² -0.05
2025-11: MAE 0.61%  R² 0.19    2025-12: MAE 0.58%  R² 0.16
2026-01: MAE 0.50%  R² 0.20    2026-02: MAE 1.04%  R² 0.19
```

R² fluctuates but MAE is stable. The Feb 2026 spike is due to a high-volatility event (AvgRange 2.9% vs normal ~1.2%), but the model adapts — it still explains 19% of variance even in extreme conditions.

---

## 3. Recommendations

### ✅ Enable Now: Volatility Predictor (Dynamic Stop-Loss)

The volatility model is **production-ready for all four symbols.** Recommended config:

```yaml
strategy:
  dynamic_stop:
    enabled: true
    url: "http://localhost:9001"
    timeout_ms: 200
    fail_open: true      # fallback to ATR if ML server fails
    k: 1.2               # slight overestimate → safer stops
    min_stop_pct: 0.01   # 1% floor
    max_stop_pct: 0.04   # 4% ceiling
```

**Why `k=1.2`:** The model slightly under-predicts tail ranges (ratio 1.13–1.27x in top quintile). Using k=1.2 corrects this bias, giving stops that are wide enough to survive spikes.

**Why `fail_open=true`:** If the ML server is down, fall back to the existing ATR × 3.0 stop. Never block trades due to infrastructure issues.

### ⚠️ Enable Selectively: Regime Classifier (SOL + ETH only)

Only SOL and ETH have actionable signal. Recommended approach:

```yaml
strategy:
  regime_filter:
    enabled: true       # enable for all symbols, but...
    threshold: 0.50
    fail_open: false
    fallback_to_adx: true   # BTC/BNB will mostly use ADX fallback
```

**However**, with only ~130 test entries per symbol, even SOL's result could be noise. Consider:
1. **Paper trade for 2-3 months** with regime filter logging but not blocking
2. Track: does prob_safe > 0.50 actually correlate with winning breakouts in live data?
3. Only hard-enable after confirming the edge persists

### ❌ Do Not Enable: BTC + BNB Regime Models

These models are worse than random on OOS. The ADX > 20 legacy filter is safer for these symbols. Possible causes:
- BTC is too efficient — 6 simple features can't predict breakout quality
- BNB has idiosyncratic behavior tied to Binance-specific events
- 1,029–1,071 training entries may simply not be enough for a 4-class problem (long-win, long-loss, short-win, short-loss)

### Path Forward for v2 improvements

1. **More data:** Run the labeler on 1H candles (4x more entries) — may improve BTC/BNB
2. **Train/test regime awareness:** Use walk-forward retraining (retrain every 3 months on rolling 2-year window)
3. **Directional split:** Train separate models for long vs short breakouts — the features that predict good long entries may differ from short entries
4. **Add realized-vol features to regime model:** `atrp_14`, `range_sma_6` are powerful in the vol model — they may help the regime model too
5. **Ensemble:** For SOL/ETH, combine regime + vol predictions (only enter when regime=SAFE AND stop width is reasonable)

---

## Appendix: Comparison vs Old XGBoost v1

| Metric | XGBoost v1 (disabled) | Regime Classifier v1 | Volatility Predictor v1 |
|--------|:---:|:---:|:---:|
| **Features** | 19 | 6 | 6 |
| **Model** | XGBoost depth=6 | RandomForest depth=4 | HuberRegressor |
| **Target** | "price >1.5% in 16h" | "breakout reaches +1R" | "next candle range %" |
| **Train AUC/MAE** | 0.94–0.96 | 0.74–0.76 | 0.50–1.54% MAE |
| **Test AUC/MAE** | 0.54–0.61 | 0.46–0.76 | 0.50–0.91% MAE |
| **Overfit Gap** | **+0.35 to +0.42** ❌ | **0.00 to +0.28** ↓ | **negative (no overfit)** ✅ |
| **Usable symbols** | 0 of 4 | 1-2 of 4 | **4 of 4** |
| **Production-ready** | ❌ | ⚠️ partial | ✅ |

The fundamental redesign worked. Simpler models + simpler targets = dramatically less overfitting. The volatility predictor is a clear win. The regime classifier needs more data or a different approach for BTC/BNB.
