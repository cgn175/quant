# ML V2 Implementation Report

**Date**: 2026-02-09
**Status**: ✅ All changes implemented, compiled, tests passing

---

## What Was Done

Implemented all 4 recommendations from `docs/ML_V2_IMPROVEMENTS_REPORT.md`:

### 1. ✅ ETH: Switched to v2 Regime Model (8 features)

- **What**: ETH now uses the v2 regime model (8 features: 6 original + `atrp_14`, `range_sma_6`) instead of v1 (6 features)
- **Why**: v2 improves ETH AUC from 0.633 → 0.695, edge from 9.5pp → 13.2pp, and reduces overfitting gap from 0.118 → 0.060
- **How**: Added `symbol_versions` map to config; Go strategy picks `BuildRegimeV2Features()` vs `BuildRegimeFeatures()` per symbol; ML server loads both `regime_v1/` and `regime_v2/` registries and routes requests by symbol

### 2. ✅ ETH: Enabled Ensemble Filter (Regime + Vol)

- **What**: After regime passes for ETH, a second gate requires the vol-predicted stop ≤ 2.5%
- **Why**: Blocks ~80% of ETH entries, but the remaining 20% have 26.9% win rate vs 8.5% for blocked = +18.4pp edge
- **How**: New `EnsembleConfig` struct in config; `OnBar()` calls `PredictVolatility()` after regime passes; blocks if `k * pred_range > max_stop_pct`

### 3. ✅ SOL: Kept v1 Regime Model

- **What**: SOL explicitly uses v1 model (AUC 0.757, +20pp edge) — v2 features hurt SOL (-0.08 AUC, -4.5pp edge)
- **How**: `symbol_versions: { SOLUSDT: "v1" }` in config ensures SOL always gets v1

### 4. ✅ SOL: Trained LONG-only Directional Model

- **What**: Trained and saved a SOL LONG-only regime model achieving **0.809 AUC** (vs 0.757 combined)
- **Training results**: AUC gap -0.038 (no overfitting), 23.1% win rate at threshold 0.50
- **How**: Created `train_regime_directional_save.py`, model saved to `ml/models/regime_v1_long/SOLUSDT.pkl`

### 5. ✅ Regime Filter Enabled (was disabled)

- **What**: `regime_filter.enabled` changed from `false` to `true` in config.yaml
- **Why**: SOL and ETH have demonstrated signal; now deployed with per-symbol optimizations

---

## Files Changed (5 existing + 2 new)

| File | Changes |
|---|---|
| `config.yaml` | Enabled regime filter; added `symbol_versions`, `ensemble`, `directional_symbols` |
| `internal/config/config.go` | Added `EnsembleConfig` struct, `SymbolVersions`, `DirectionalSymbols` to `RegimeFilterConfig` |
| `internal/strategy/trend.go` | Added per-symbol v1/v2 feature selection, ensemble vol gate, directional config fields |
| `cmd/bot/main.go` | Wired `SymbolVersions`, `EnsembleConfig`, `DirectionalSymbols` into `TrendConfig` |
| `internal/mlfilter/client.go` | Added `PredictRegimeDirectional()` method and `DirectionalPredictRequest` struct |
| `ml/server.py` | Split into `regime_v1`/`regime_v2`/`regime_long` registries; added `/predict_regime_directional` endpoint; per-symbol version routing |
| `ml/regime/train_regime_directional_save.py` | **NEW** — Training script for directional models |

## New Files Created

| File | Purpose |
|---|---|
| `ml/regime/train_regime_directional_save.py` | Train & save LONG-only / SHORT-only regime models |
| `ml/models/regime_v1_long/SOLUSDT.pkl` | Trained SOL LONG-only model (AUC 0.809) |
| `ml/models/regime_v1_long/SOLUSDT_meta.json` | Model metadata |

---

## Verification

```
✅ go build ./...         — compiles cleanly
✅ go test ./internal/...  — all tests pass
✅ SOL LONG model trained  — AUC 0.809, no overfitting (gap -0.038)
```

## Architecture Summary

```
Signal Flow (OnBar):
  Entry signal detected
    → Regime filter check:
        → Pick v1 or v2 features based on symbol_versions map
        → Call /predict_regime (server routes to correct registry)
        → If passed AND ensemble enabled for this symbol:
            → Call /predict_volatility
            → Block if predicted stop > max_stop_pct (2.5%)
    → Continue to volatility filter, funding filter, etc.
```

## Remaining Work (Not Done This Session)

1. **Paper trade validation** — Monitor ensemble decisions for 2-3 months before hard-enabling, per the report's conservative recommendation.

2. **Walk-forward retraining** — Run quarterly using `ml/regime/train_regime_walkforward.py` to check stability.

3. **BTC/BNB** — Fundamentally different approach needed; regime classification doesn't work well for these symbols.
