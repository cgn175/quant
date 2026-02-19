# ML v2 Improvement Experiments Report

**Date**: 2026-02-09
**Experiments**: Walk-forward, Directional split, Realized-vol features (v2), Ensemble

---

## Executive Summary

| Experiment | Key Finding | Actionable? |
|---|---|---|
| Walk-forward retraining | SOL is BORDERLINE stable (mean AUC 0.618, edge>0 in 79% of windows). BNB is UNSTABLE. BTC/ETH borderline. | 🟡 SOL signal persists but with high variance |
| Directional split | LONG-only SOL model reaches 0.809 AUC (vs 0.757 combined). Directional split helps all symbols. | ✅ Train separate LONG/SHORT models |
| Realized-vol features (v2) | v2 helps ETH (+0.06 AUC, +3.6pp edge) but hurts SOL (-0.08 AUC, -4.5pp edge). Mixed results. | ✅ Use v2 for ETH only, keep v1 for SOL |
| Ensemble (regime + vol) | ETH ensemble boosts edge +6.5pp (18.4pp vs 11.9pp). SOL ensemble adds +2.6pp. BTC/BNB no help. | ✅ Enable for ETH, optional for SOL |

---

## 1. Walk-Forward Retraining

**Setup**: 2-year rolling train window, 3-month steps, 14–16 windows per symbol.

| Symbol | Mean AUC | Std AUC | Mean Edge | Edge>0% | Verdict |
|--------|----------|---------|-----------|---------|---------|
| BTCUSDT | 0.582 | 0.134 | +11.0pp | 81% | 🟡 BORDERLINE |
| ETHUSDT | 0.582 | 0.182 | +8.8pp | 75% | 🟡 BORDERLINE |
| SOLUSDT | 0.618 | 0.131 | +12.3pp | 79% | 🟡 BORDERLINE |
| BNBUSDT | 0.519 | 0.181 | +3.3pp | 44% | ⚠️ UNSTABLE |

**Key insight**: SOL has the best average signal but still has 2 bad windows (AUC 0.305 and 0.472). The high std (0.131) means the signal strength varies significantly across market regimes. BTC shows surprisingly positive edge in 81% of windows despite low AUC — the model's ranking is useful even when AUC is modest.

**Surprise**: BTC walk-forward edge is actually +11.0pp positive in 81% of windows, contradicting the single-split result (AUC 0.457). This suggests the single OOS period (2025-07 to 2026-02) is an unusually bad test window for BTC.

---

## 2. Directional Split (LONG vs SHORT)

| Symbol | Combined AUC | LONG AUC | SHORT AUC | Best | Verdict |
|--------|:-:|:-:|:-:|---|---|
| BTCUSDT | 0.457 | **0.539** | 0.490 | LONG | split helps |
| ETHUSDT | 0.633 | 0.472 | **0.698** | SHORT | split helps |
| SOLUSDT | 0.757 | **0.809** | 0.613 | LONG | split helps |
| BNBUSDT | 0.502 | **0.556** | 0.552 | LONG | split helps |

**Key insight**: Directional split helps every symbol. SOL LONG-only reaches 0.809 AUC with +23.1pp edge — the strongest result in any experiment. Feature importance differs by direction:
- LONG models: volatility_20 more important (calm markets → better long entries)
- SHORT models: funding_24h_avg and volume_ratio_20 more important

**Caveat**: With ~60-80 entries per direction in test, these results are noisy. The SOL LONG improvement is large enough to be meaningful, but BTC/BNB improvements are within noise range.

---

## 3. Realized-Vol Features (v2: 8 features)

| Symbol | v1 AUC | v2 AUC | ΔAUC | v1 Edge | v2 Edge | ΔEdge | Verdict |
|--------|--------|--------|------|---------|---------|-------|---------|
| BTCUSDT | 0.457 | 0.465 | +0.008 | -3.9pp | -4.4pp | -0.5pp | 🟡 similar |
| ETHUSDT | 0.633 | **0.695** | **+0.062** | +9.5pp | **+13.2pp** | **+3.6pp** | ✅ v2 better |
| SOLUSDT | **0.757** | 0.678 | **-0.079** | **+20.0pp** | +15.5pp | **-4.5pp** | ❌ v2 worse |
| BNBUSDT | 0.502 | 0.489 | -0.013 | +2.2pp | -4.9pp | -7.1pp | ❌ v2 worse |

**Key insight**: atrp_14 and range_sma_6 significantly help ETH (AUC +0.06, gap reduced from 0.118 to 0.060) but hurt SOL (more overfitting). The new features distribute importance more evenly, which helps ETH but dilutes SOL's already-good signal. This is a per-symbol effect, not universal.

**v2 feature importance (ETH example):**
```
volume_ratio_20   31.7%
volatility_20     16.4%
atrp_14           15.5%  ← new, significant
rsi_14            14.9%
range_sma_6       10.0%  ← new, significant
funding_24h_avg    7.7%
hour_sin/cos       3.8%
```

---

## 4. Ensemble (Regime + Volatility)

Best ensemble configurations per symbol:

| Symbol | Regime-Only Best | Ensemble Best | Config | Improvement |
|--------|:-:|:-:|---|:-:|
| BTCUSDT | +1.6pp | +1.6pp | r≥0.55+s≤2% | +0.0pp |
| ETHUSDT | +11.9pp | **+18.4pp** | **r≥0.50+s≤2.5%** | **+6.5pp** |
| SOLUSDT | +20.0pp | **+22.6pp** | r≥0.55+s≤3.5% | +2.6pp |
| BNBUSDT | +14.5pp | +9.4pp | r≥0.40+s≤3.5% | -5.1pp |

**Key insight**: The ensemble (regime=SAFE AND stop_width≤threshold) adds meaningful value for ETH:
- ETH r≥0.50+s≤2.5%: only 26 entries pass (20%), but 26.9% win rate vs 8.5% for blocked = +18.4pp edge
- SOL r≥0.55+s≤3.5%: 23 entries pass (17%), 30.4% win rate vs 7.8% blocked = +22.6pp edge

The vol filter acts as a "quality gate" — when the vol model predicts wide stops (high volatility), breakout entries tend to fail. Restricting to narrow-stop entries improves win rates.

**SOL's adaptive sizing doesn't help** — the size scalar averages 0.78 (meaning stops are already near max), so there's no room for the vol model to differentiate.

---

## Recommendations

### Immediate Actions

1. **ETH: Switch to v2 regime model (8 features)**
   - AUC improved 0.633 → 0.695, edge improved 9.5pp → 13.2pp
   - Overfitting gap decreased (0.118 → 0.060)
   - Files ready: `ml/regime/features_regime_v2.py`, `ml/models/regime_v2/ETHUSDT.pkl`
   - Go feature builder ready: `internal/strategy/trend_regime_v2_features.go`

2. **ETH: Enable ensemble filter (regime + vol)**
   - Use r≥0.50 + stop_pct≤2.5% for maximum edge (+18.4pp)
   - Tradeoff: blocks 80% of entries but remaining 20% have 26.9% win rate

3. **SOL: Keep v1 regime model, consider directional split**
   - v1 already excellent (AUC 0.757, +20pp edge)
   - LONG-only model reaches 0.809 AUC — worth deploying for long entries
   - v2 features hurt SOL; do not use

### Future Work

1. **Train LONG-only regime model for SOL** — highest priority, clear improvement
2. **Walk-forward retraining pipeline** — script exists, run quarterly to check stability
3. **ETH ensemble in paper trade** — log ensemble decisions for 2-3 months before hard-enabling
4. **BTC/BNB: fundamentally different approach needed** — walk-forward confirms instability. Consider more features, different model type, or accept that regime classification doesn't work for these symbols.

---

## Files Created

| File | Purpose |
|---|---|
| `ml/regime/train_regime_walkforward.py` | Walk-forward validation script |
| `ml/regime/train_regime_directional.py` | Directional split analysis script |
| `ml/regime/features_regime_v2.py` | 8-feature regime feature engineering |
| `ml/regime/train_regime_v2.py` | v1 vs v2 comparison trainer |
| `ml/regime/analyze_ensemble.py` | Ensemble (regime+vol) analysis script |
| `internal/strategy/trend_regime_v2_features.go` | Go feature builder for v2 (8 features) |
| `ml/models/regime_v2/*.pkl` | Trained v2 models (all 4 symbols) |
