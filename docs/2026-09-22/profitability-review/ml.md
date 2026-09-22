# ML/data validation audit — quant bot

**Audit date:** 2026-09-22
**Scope:** read-only review of the ML artifacts, labels, validation scripts, Go/Python feature parity, and runtime activation path. No training was run and no database/model/data file was modified.
**Capital context:** own capital, less than USD 1,000.

## Decision summary

There is no evidence in this repository that ML adds a positive, net-of-cost trading edge that is ready for private capital. The legacy directional XGBoost model is conclusively rejected. The simpler regime models contain an exploratory signal for SOL and, more weakly, ETH in a single February 2026 test period, but that evidence is too small, stale, selected on the same OOS period, and not expressed as strategy-level net PnL. The volatility model is useful as a conditional volatility/risk input, but its low R² and the absence of a stop-aware net-PnL replay do not prove alpha.

The conservative runtime conclusion is:

* Keep legacy directional ML disabled.
* Treat regime ML, HMM, and ML-driven dynamic stops as research-only until a fresh, cost-complete, strategy-level replay and forward paper test pass.
* Use the mechanical strategy/ADX path as the control. Do not promote an ML gate because its SAFE-vs-DANGER win-rate difference is positive.

Confidence is high for rejecting legacy XGBoost and BTC/BNB regime models; medium for the volatility model as a useful risk forecast; and low-to-medium for any incremental SOL/ETH alpha claim.

## What is actually enabled

The current tracked trend template is paper mode and selects `trend_following` ([config.example.trend.yaml:1](/home/hoangt/projects/quant/config.example.trend.yaml:1), [config.example.trend.yaml:14](/home/hoangt/projects/quant/config.example.trend.yaml:14)). It does not contain `bar_size`, `ml_filter`, `regime_filter`, or `dynamic_stop` sections. The Go defaults set `bar_size` to `1m` ([internal/config/config.go:491-494](/home/hoangt/projects/quant/internal/config/config.go:491)), while regime and dynamic-stop flags default to false ([internal/config/config.go:552-572](/home/hoangt/projects/quant/internal/config/config.go:552)). The legacy ML filter also defaults to false ([internal/config/config.go:552-557](/home/hoangt/projects/quant/internal/config/config.go:552)).

The trend runner only creates an ML client when one of those feature flags is enabled ([internal/bot/trend.go:314-395](/home/hoangt/projects/quant/internal/bot/trend.go:314)). `OnBar` calls the regime endpoint only when `RegimeFilterEnabled` is true and calls the volatility endpoint only when `DynamicStopEnabled` is true ([internal/strategy/trend.go:663-679](/home/hoangt/projects/quant/internal/strategy/trend.go:663), [internal/strategy/trend.go:905-921](/home/hoangt/projects/quant/internal/strategy/trend.go:905)). Therefore, a copy of the current template runs without these ML paths unless an untracked local config overrides them.

There is a configuration hazard if somebody enables ML by copying the current template: the models were trained on 4H data, but the template omits `bar_size` and the default is 1m. The old ML example that included `bar_size: "4h"` is historical (`git show f5c15e5:config.yaml.example`), not the current tracked template. A model trained on 4H distributions must not receive 1m candles.

The current branch also contains uncommitted hardening specifications that explicitly quarantine HMM/regime ML and exclude ML selection from the initial hourly candidate ([specs/001-harden-trading-strategies/research.md:26-35](/home/hoangt/projects/quant/specs/001-harden-trading-strategies/research.md:26), [specs/001-harden-trading-strategies/research.md:125-129](/home/hoangt/projects/quant/specs/001-harden-trading-strategies/research.md:125)). Those are plans, not runtime enforcement; the Go code still contains the HMM/regime paths.

The Python server loads many artifacts, but loading is not activation. It loads per-symbol regime v1/v2, SOL directional, HMM, and volatility registries ([ml/server.py:511-535](/home/hoangt/projects/quant/ml/server.py:511)). The unused 1H and pooled model directories are not loaded by this server. The current retraining pipeline advertises HMM in `MODEL_VARIANTS` ([scripts/retrain_pipeline.py:71-81](/home/hoangt/projects/quant/scripts/retrain_pipeline.py:71)) but `cmd_train` actually trains only regime v1, regime v2, SOL long, and vol v1 ([scripts/retrain_pipeline.py:364-408](/home/hoangt/projects/quant/scripts/retrain_pipeline.py:364)). HMM artifacts are consequently static unless trained separately.

## Saved-model evidence

### Legacy directional XGBoost — reject

The repository's own analysis reports average OOS AUC 0.57, train AUC 0.94–0.96 versus test AUC 0.54–0.61, severe calibration error, and only 3.8–5.5% of bars passing the 0.65 threshold ([docs/2026-02-09/ML_MODEL_ANALYSIS.md:12-21](/home/hoangt/projects/quant/docs/2026-02-09/ML_MODEL_ANALYSIS.md:12)). Monthly AUC alternates between below-random and apparently good values ([docs/2026-02-09/ML_MODEL_ANALYSIS.md:129-142](/home/hoangt/projects/quant/docs/2026-02-09/ML_MODEL_ANALYSIS.md:129)). The document correctly recommends keeping it disabled ([docs/2026-02-09/ML_MODEL_ANALYSIS.md:230-241](/home/hoangt/projects/quant/docs/2026-02-09/ML_MODEL_ANALYSIS.md:230). This is not a candidate for capital.

### Regime classifier v1 — one useful symbol, two clear failures

The artifacts contain a chronological split with roughly five years of training and a February 2026 test period, but only 132–138 test breakout entries:

| Symbol | Train AUC | Test AUC | Gap | Test entries | Assessment |
|---|---:|---:|---:|---:|---|
| BTCUSDT | 0.7368 | 0.4573 | +0.2795 | 137 | Worse than random; reject |
| ETHUSDT | 0.7511 | 0.6331 | +0.1180 | 132 | Borderline, exploratory |
| SOLUSDT | 0.7553 | 0.7567 | -0.0013 | 138 | Best result, still small/stale |
| BNBUSDT | 0.7556 | 0.5021 | +0.2536 | 135 | Random and overfit; reject |

These values are directly recorded in the model metadata ([BTC](/home/hoangt/projects/quant/ml/models/regime_v1/BTCUSDT_meta.json:19), [ETH](/home/hoangt/projects/quant/ml/models/regime_v1/ETHUSDT_meta.json:19), [SOL](/home/hoangt/projects/quant/ml/models/regime_v1/SOLUSDT_meta.json:19), [BNB](/home/hoangt/projects/quant/ml/models/regime_v1/BNBUSDT_meta.json:19)). The SOL model is not enough to establish an edge for a portfolio: its test set is 138 breakout events, and the observed result ends in February 2026.

### Regime v2 and directional variants — selected exploratory results

Regime v2 improves ETH to AUC 0.695 with gap 0.0599, but it worsens SOL to AUC 0.6778 with gap 0.0950; BTC and BNB remain below random ([ETH v2](/home/hoangt/projects/quant/ml/models/regime_v2/ETHUSDT_meta.json:21), [SOL v2](/home/hoangt/projects/quant/ml/models/regime_v2/SOLUSDT_meta.json:21), [BTC v2](/home/hoangt/projects/quant/ml/models/regime_v2/BTCUSDT_meta.json:21), [BNB v2](/home/hoangt/projects/quant/ml/models/regime_v2/BNBUSDT_meta.json:21)). This is a per-symbol selection result, not a universal model improvement.

The SOL LONG-only artifact reports AUC 0.8088, gap -0.0376, but only 74 test entries ([ml/models/regime_v1_long/SOLUSDT_meta.json:20-45](/home/hoangt/projects/quant/ml/models/regime_v1_long/SOLUSDT_meta.json:20)). The pooled artifact reports overall AUC 0.5728 and per-symbol AUC 0.4380 BTC, 0.6261 ETH, 0.7075 SOL, and 0.5272 BNB ([ml/models/regime_v1_pooled/pooled_meta.json:42-55](/home/hoangt/projects/quant/ml/models/regime_v1_pooled/pooled_meta.json:42)). Pooling does not solve the BTC/BNB instability.

The walk-forward report is more informative than a single split but still calls all four symbols borderline or unstable: mean AUC is 0.582 BTC, 0.582 ETH, 0.618 SOL, and 0.519 BNB; SOL has bad windows at AUC 0.305 and 0.472 ([docs/2026-02-09/ML_V2_IMPROVEMENTS_REPORT.md:19-32](/home/hoangt/projects/quant/docs/2026-02-09/ML_V2_IMPROVEMENTS_REPORT.md:19)). The same report explicitly warns that directional results have only roughly 60–80 entries per direction and are noisy ([docs/2026-02-09/ML_V2_IMPROVEMENTS_REPORT.md:36-49](/home/hoangt/projects/quant/docs/2026-02-09/ML_V2_IMPROVEMENTS_REPORT.md:36).

### Volatility predictor — useful ordering, unproven trading improvement

The saved Huber models report lower test MAE than train MAE, but R² is only 0.0808–0.2649 ([BTC](/home/hoangt/projects/quant/ml/models/vol_v1/BTCUSDT_meta.json:23), [ETH](/home/hoangt/projects/quant/ml/models/vol_v1/ETHUSDT_meta.json:23), [SOL](/home/hoangt/projects/quant/ml/models/vol_v1/SOLUSDT_meta.json:23), [BNB](/home/hoangt/projects/quant/ml/models/vol_v1/BNBUSDT_meta.json:23)). This supports “recent range helps rank the next range,” not “dynamic stops make the strategy profitable.” The training script chooses Huber versus Ridge using the same test MAE it reports ([ml/volatility/train_volatility.py:145-197](/home/hoangt/projects/quant/ml/volatility/train_volatility.py:145)), which makes the reported test result optimistic as a model-selection estimate.

The target is next-candle high-low range divided by current close ([ml/volatility/train_volatility.py:76-83](/home/hoangt/projects/quant/ml/volatility/train_volatility.py:76)). Runtime then uses the prediction as a stop width for the whole position ([internal/strategy/trend.go:905-921](/home/hoangt/projects/quant/internal/strategy/trend.go:905)), but there is no artifact showing net PnL, drawdown, or stop-out behavior after that substitution.

## Validation and data weaknesses

### The data snapshot is unavailable

The checkout contains no `data/training.db`, `data/training_1h.db`, or candle/funding database; only model artifacts and scripts are present. I therefore could not independently recompute counts, timestamp gaps, duplicate candles, funding alignment, or the reported metrics. The model metadata and reports are treated as claims about a prior run, not as reproducible evidence in this checkout.

### Temporal split is not purged or embargoed

The regime label looks six bars ahead for a stop/target outcome ([ml/regime/label_regime.py:93-115](/home/hoangt/projects/quant/ml/regime/label_regime.py:93)). The trainer then splits rows only by entry timestamp ([ml/regime/train_regime.py:120-139](/home/hoangt/projects/quant/ml/regime/train_regime.py:120)). A training entry immediately before the cutoff can therefore have a label whose outcome window extends into the test period. The last six bars of a dataset also have a shortened evaluation window but remain labeled 0 by default. A defensible event split needs a purge/embargo of at least the label horizon and should drop censored tail events.

Breakout rows are generated for every qualifying bar; there is no explicit position de-duplication, cooldown, or non-overlap rule ([ml/regime/label_regime.py:64-75](/home/hoangt/projects/quant/ml/regime/label_regime.py:64)). Consecutive entries can share future candles and are not independent observations. The nominal 132–138 test events therefore overstate effective sample size.

### “Economic edge” is win-rate separation, not trading PnL

The regime reports define edge as `SAFE win rate - DANGER win rate` ([ml/regime/train_regime_v2.py:95-114](/home/hoangt/projects/quant/ml/regime/train_regime_v2.py:95)). The ensemble report uses the same statistic ([ml/regime/analyze_ensemble.py:129-146](/home/hoangt/projects/quant/ml/regime/analyze_ensemble.py:129)). Neither computes the actual Plan D payoff distribution (trailing exit, partial exits, time stop, funding, fees, spread, slippage, or next-event fill). A 1R target and 1R stop also make a raw label win rate below 50% negative before costs if the actual trade exits symmetrically; the label is not the production strategy payoff.

The ensemble script searches many thresholds and stop-width combinations on the same OOS period and selects the best result when at least five events pass ([ml/regime/analyze_ensemble.py:205-277](/home/hoangt/projects/quant/ml/regime/analyze_ensemble.py:205)). This is a multiple-testing/selection loop. For example, the headline ETH result is 26 passing events and 26.9% win rate versus 8.5% blocked (+18.4pp), while SOL is 23 events and 30.4% versus 7.8% (+22.6pp) ([docs/2026-02-09/ML_V2_IMPROVEMENTS_REPORT.md:77-94](/home/hoangt/projects/quant/docs/2026-02-09/ML_V2_IMPROVEMENTS_REPORT.md:77)). Those groups are too small to support a capital decision; approximate Wilson 95% intervals for the passing win rates are about 13.7–46.1% ETH and 15.6–50.8% SOL.

There is no calibration step for regime `predict_proba` values. Thresholds are chosen from the same historical OOS outputs and then written as suggested/deployment settings. The original XGBoost calibration failure is documented ([docs/2026-02-09/ML_MODEL_ANALYSIS.md:114-125](/home/hoangt/projects/quant/docs/2026-02-09/ML_MODEL_ANALYSIS.md:114)), but regime probabilities have not been shown to be calibrated on a later holdout.

### Funding alignment and feature parity are not fully proven

Python forward-fills funding rates directly onto candle timestamps ([ml/regime/train_regime.py:75-90](/home/hoangt/projects/quant/ml/regime/train_regime.py:75)). There is no explicit as-of publication/settlement lag, interval metadata, or stale-rate check. The feature is named `funding_24h_avg` but averages six funding observations ([ml/regime/features_regime_v1.py:44-61](/home/hoangt/projects/quant/ml/regime/features_regime_v1.py:44)); Binance funding observations are normally 8-hour events, so six observations are not 24 hours unless the data frequency is separately proven.

The Go implementation computes the 20-bar return volatility using population variance (`/count`), whereas pandas rolling standard deviation defaults to sample variance ([internal/strategy/trend_regime_features.go:25-43](/home/hoangt/projects/quant/internal/strategy/trend_regime_features.go:25)). This is a small numerical mismatch, but it violates exact feature parity. More materially, Go only populates the funding cache when `funding_filter.enabled` is true ([internal/bot/trend.go:111-115](/home/hoangt/projects/quant/internal/bot/trend.go:111)); a regime model trained with real funding can receive zeros at runtime if that unrelated filter is disabled.

### HMM runtime is not the trained feature process

The HMM trainer learns on one-bar returns, a range-based volatility, and volume ratio ([ml/regime/train_regime_hmm.py:60-82](/home/hoangt/projects/quant/ml/regime/train_regime_hmm.py:60)). The Go runtime instead passes `returns_20` and `volatility_20` from the RandomForest feature map plus volume ratio ([internal/strategy/trend.go:692-700](/home/hoangt/projects/quant/internal/strategy/trend.go:692)). The server predicts an HMM state from one observation ([ml/server.py:191-219](/home/hoangt/projects/quant/ml/server.py:191)), so it does not use a sequence of observations to capture transition dynamics. No HMM metadata records OOS AUC, net PnL, calibration, or a threshold-selection holdout. HMM should remain quarantined.

## Why the result is especially weak for USD 1,000

The ML research does not model fees, spread, slippage, latency, partial fills, or minimum order constraints in the reported regime/volatility results. The model outputs are gates or stop widths, so their value must be measured by the complete Go execution/replay path after those costs. At this capital size, the relevant question is net basis points per accepted trade and the absolute minimum order/fee burden, not a positive classification edge by itself.

The OOS artifacts end around 2026-02-08; the HMM refresh is around 2026-02-19. The audit date is 2026-09-22, so there is no evidence here for the intervening market regime. Any paper or live decision now would be an extrapolation beyond the only reported holdout.

## Recommended experiments before reconsidering ML

1. Build an immutable 1H or 4H snapshot with candle/funding/quote manifests, UTC as-of timestamps, duplicate/gap checks, and a record of which periods were previously inspected. Keep a truly fresh forward window after the freeze.
2. Rebuild regime labels with next-event execution, fees/spread/slippage, one position per signal lifecycle, non-overlapping events, a six-bar purge/embargo around split boundaries, and exclusion of censored tail events.
3. Replay the actual Plan D lifecycle in Go for four arms: mechanical/ADX control, regime gate, dynamic-stop-only, and regime+dynamic-stop. Report net PnL, expectancy in bps, turnover, trade count, drawdown, exposure, cost stress at 1x/2x, and asset attribution. Do not use SAFE-vs-DANGER win rate as the acceptance metric.
4. Fit probability calibration and thresholds using train/validation only; reserve the forward holdout for one final report. Record every threshold/model/ensemble trial and apply a multiple-testing-aware gate (DSR/PBO or a conservative trial correction).
5. Add a Go/Python parity fixture for every deployed feature and assert timeframe/feature version at server startup. Either remove HMM from eligible runtime paths or fix it to receive the exact trained feature sequence and validate it on a fresh holdout.
6. Run at least 8 weeks of paper A/B logging with the same signals and costs. For the sub-USD 1,000 account, require positive net expectancy under doubled costs and enough trades to form a credible interval before considering any real order.

**Bottom line:** ML is currently a complexity and validation liability. Keep it off the capital path until a fresh, cost-complete, strategy-level test proves incremental net PnL over the mechanical control.
