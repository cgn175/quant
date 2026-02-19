# Plan B Revised: Regime-Aware Trend Following — Implementation Progress

## Summary

Plan A (4h XGBoost binary with 33 TA features) failed: -113.81%, 31% win rate.
Plan B original (HMM + OBI + 4 regime models) assessed as ~15% chance of profitability.
**Revised Plan B**: Simplified regime-aware trend following with meta-labeling.

Key changes from original Plan B:
- NO orderbook/OBI (useless at 4h), NO HMM (overkill), NO 4 regime models (overfitting)
- YES triple barrier labels, YES meta-labeling (1 model), YES funding rate features, YES walk-forward

## Architecture

```
Primary Signals (rule-based, no ML)
  ├── Trend Continuation: close > EMA21 & EMA50, RSI > 50, daily uptrend
  └── Breakout: 20-bar high breakout + volume surge + daily uptrend

Meta-Filter (single XGBoost)
  └── Trained on triple-barrier labels: "should we take this signal?"

Features (~25):
  ├── Existing TA: log returns, EMAs, RSI, BB, MACD, volume ratio
  ├── NEW: funding rate, funding_ma8, funding_extreme
  ├── NEW: btc_dominance, eth_btc_ratio, market_breadth
  ├── NEW: atr_ratio (ATR14/ATR50), volatility_percentile
  └── NEW: daily_trend, daily_rsi (multi-timeframe)
```

## Profitability Gate (ALL must pass before Go integration)

| Metric | Threshold |
|--------|-----------|
| Walk-forward win rate | > 45% |
| Expectancy per trade | > 0.3% |
| Profit factor | > 1.3 |
| Sharpe ratio | > 1.0 |
| Max drawdown | < 25% |
| Signal selectivity | < 3 trades/day |
| Consistency | > 60% profitable months |

---

## Phase 1: Data Pipeline Enhancement

### Task 1.1: Modify fetch_data.py — Add funding rate + daily OHLCV
- **File**: `scripts/fetch_data.py`
- **Status**: ✅ Complete (code)
- **Details**: Added `fetch_funding_rates()` (futures API, 730d default) and `fetch_daily_ohlcv()`. CLI flags `--add-funding` and `--add-daily` with `--extra-days` param.
- **Output**: `data_4h/funding/` parquet files + `data_daily/` parquet files
- **Data fetched?**: **NO** — `data_4h/funding/` and `data_daily/` directories do not exist. Funding/daily data has not been downloaded. The walk-forward ran **without** funding or daily features (defaulted to 0/50).

### Task 1.2: Create build_features_v2.py — Enhanced features
- **File**: `scripts/build_features_v2.py`
- **Status**: ✅ Complete
- **Details**: 29 features implemented across 7 categories:
  - Price returns (4): log_ret_1/2/6/12
  - Trend (2): ema_21, ema_50
  - Momentum (2): rsi_14, macd_histogram
  - Volatility (6): bb_width, bb_pct, atr_14, atr_ratio, vol_regime_ratio, volatility_percentile
  - Volume (2): volume_ratio, vol_surge
  - Funding (3): funding_rate, funding_ma8, funding_extreme
  - Cross-asset (3): btc_dominance_proxy, eth_btc_ratio, market_breadth
  - Daily context (2): daily_trend, daily_rsi
  - Time (4): hour_sin, hour_cos, day_sin, day_cos
- **Note**: Funding features default to 0 and daily features default to neutral (0 / 50.0) when data is missing. Cross-asset features use the 4h data dict.

### Task 1.3: Create labeling.py — Triple barrier method
- **File**: `scripts/labeling.py`
- **Status**: ✅ Complete
- **Details**: `triple_barrier_labels()` for all bars + `label_signals()` for signal-only bars. TP = tp_mult × ATR, SL = sl_mult × ATR, max hold = max_holding_bars. Uses High/Low for intrabar checks (SL checked first = conservative). Supports both long and short sides. CLI with per-symbol stats.

---

## Phase 2: Signal Generation + Meta-Label Training

### Task 2.1: Create primary_signals.py — Rule-based trend following
- **File**: `scripts/primary_signals.py`
- **Status**: ✅ Complete
- **Details**: Two signal types implemented:
  - **Trend continuation**: close > EMA21 & EMA50, RSI14 > 50, daily_trend == 1
  - **Breakout**: close > 20-bar rolling high, volume_ratio > 1.5, daily_trend == 1
  - `combined_signals()` returns union with signal_type column ('trend'/'breakout'/'both')
  - Falls back to 42-bar SMA proxy when daily_trend feature is missing

### Task 2.2: Create train_meta_model.py — Meta-label XGBoost
- **File**: `scripts/train_meta_model.py`
- **Status**: ✅ Complete
- **Details**: Full pipeline: load data -> v2 features -> primary signals -> triple barrier labels -> meta-features (V2 + signal_type one-hot) -> train XGBoost. Conservative fixed params: max_depth=4, lr=0.05, subsample=0.8, min_child_weight=10, n_estimators=500, early_stopping=30. Outputs model (.json/.joblib) + metrics + feature list to `models_meta/`.
- **Model saved?**: **NO** — `models_meta/` directory does not exist. The standalone meta-model has not been trained (only the walk-forward internal retraining was run).

### Task 2.3: Create walk_forward.py — Walk-forward validation
- **File**: `scripts/walk_forward.py`
- **Status**: ✅ Complete + **RUN**
- **Details**: 180d train, 30d test, 30d step. Retrains XGBoost each window. Includes profitability gate check, equity curve, per-window table.
- **Results**: Saved to `results/walk_forward_results.parquet` + `results/walk_forward_summary.json`
- **Run Config**: Default threshold=0.60, 4 symbols, no funding/daily data

---

## Phase 3: Backtesting & Evaluation

### Task 3.1: Create backtest_v2.py — Enhanced backtester
- **File**: `scripts/backtest_v2.py`
- **Status**: ✅ Complete (code) — **NOT RUN**
- **Details**: Full `MetaLabelBacktester` class with: risk-based position sizing (1% equity risk), ATR-scaled TP/SL, slippage + fees on both legs, max 1 position per symbol, daily loss cap (5%), monthly PnL, buy-and-hold benchmark, profitability gate check. Fixes from old backtest.py: time-based split, correct 4h annualization (sqrt(365×6)), no random shuffle.
- **Note**: Designed to consume walk_forward_results.parquet but no backtest output files exist yet.

---

## Walk-Forward Run 1: Without Funding/Daily Data (from `results/`)

### Aggregate Metrics

| Metric | Value | Gate Threshold | Pass? |
|--------|-------|---------------|-------|
| Total trades | 213 | — | — |
| Win rate | 32.9% | > 45% | **FAIL** |
| Expectancy | -0.436% | > 0.3% | **FAIL** |
| Profit factor | 0.659 | > 1.3 | **FAIL** |
| Sharpe ratio | -2.47 | > 1.0 | **FAIL** |
| Max drawdown | 62.7% | < 25% | **FAIL** |
| Trades/day | 0.15 | < 3 | PASS |
| Profitable months | 44.4% | > 60% | **FAIL** |

**Profitability Gate: FAILED (1/7 passed)**

---

## Walk-Forward Run 2: With Funding + Daily Data (from `results_v2/`)

Data fetched: funding rates (6570 records/symbol, 6yr) + daily OHLCV (2190 bars/symbol).
All 29 features now populated with real data.

### Aggregate Metrics

| Metric | Value | Gate Threshold | Pass? |
|--------|-------|---------------|-------|
| Total trades | 181 | — | — |
| Win rate | 21.5% | > 45% | **FAIL** |
| Expectancy | -0.683% | > 0.3% | **FAIL** |
| Profit factor | 0.478 | > 1.3 | **FAIL** |
| Sharpe ratio | -6.26 | > 1.0 | **FAIL** |
| Max drawdown | 77.0% | < 25% | **FAIL** |
| Trades/day | 0.10 | < 3 | PASS |
| Profitable months | 33.3% | > 60% | **FAIL** |

### **Profitability Gate: FAILED (1/7 passed) — WORSE than Run 1**

### Per-Window Summary (non-empty windows only)

| Window | Period | Trades | Win Rate | Total Return | PF |
|--------|--------|--------|----------|-------------|------|
| 2 | Mar-Apr 2021 | 4 | 50.0% | +3.4% | 1.66 |
| 29 | May-Jun 2023 | 26 | 50.0% | +4.6% | 1.17 |
| 37 | Jan-Feb 2024 | 12 | 16.7% | -7.2% | 0.35 |
| 39 | Mar-Apr 2024 | 4 | 25.0% | -1.9% | 0.62 |
| 43 | Jul-Aug 2024 | 10 | 20.0% | -11.1% | 0.49 |
| 46 | Oct-Nov 2024 | 6 | 50.0% | -1.3% | 0.87 |
| 47 | Nov-Dec 2024 | 37 | 32.4% | -1.3% | 0.97 |
| 58 | Oct-Nov 2025 | 2 | 0.0% | -2.1% | 0.00 |
| 59 | Nov-Dec 2025 | 80 | 5.0% | -106.6% | 0.06 |

**Key observations:**
- 60 windows total, only 9 had any trades (85% of windows = 0 trades) — sparsity unchanged
- Adding funding+daily data made results **worse** (WR 32.9% → 21.5%, Sharpe -2.47 → -6.26)
- Window 59 is catastrophic: 80 trades at 5% WR, -106.6% return — model completely broke down
- Only 2 of 9 active windows were profitable (windows 2 and 29)
- The additional features added noise, not signal

### Comparison: Run 1 vs Run 2

| Metric | Run 1 (no funding/daily) | Run 2 (with funding/daily) | Delta |
|--------|--------------------------|---------------------------|-------|
| Trades | 213 | 181 | -32 |
| Win rate | 32.9% | 21.5% | **-11.4%** |
| Expectancy | -0.436% | -0.683% | **-0.247%** |
| Profit factor | 0.659 | 0.478 | **-0.181** |
| Sharpe | -2.47 | -6.26 | **-3.79** |
| Max drawdown | 62.7% | 77.0% | **+14.3%** |

**Conclusion: Funding rate and daily context features did NOT help. They made every metric worse. The fundamental problem is not missing data — the strategy architecture itself is flawed.**

---

## Root Cause Analysis (Plan B Failure — Confirmed)

1. **Features don't predict**: Neither the original 24 TA features nor the additional funding/daily features contain signal for 4h crypto returns. Adding more features added noise and worsened overfitting.

2. **Extreme signal sparsity**: 85% of test windows produce zero trades. The primary signal rules + 0.60 threshold filter out nearly everything. The strategy rarely trades, and when it does it's catastrophically wrong.

3. **Catastrophic tail risk**: Window 59 (Nov-Dec 2025) alone lost -106.6% on 80 trades at 5% WR. The meta-model periodically "breaks" and fires confident but completely wrong signals.

4. **Single-regime long-only bias**: Entire 2022 bear market (windows 11-25) correctly produced zero signals, but the model has no ability to profit — it only avoids losing during obvious downtrends.

5. **Meta-labeling doesn't rescue bad signals**: The primary signals (trend continuation + breakout) are themselves not predictive. A meta-filter on unpredictive base signals cannot create alpha — it can only reduce trade frequency.

6. **Walk-forward retraining instability**: The model trained on different 180-day windows produces wildly inconsistent behavior (WR ranging from 0% to 50%), indicating it's fitting noise each window.

---

## Phase 4: Go Integration (ONLY if Phase 3 passes profitability gate)

### Task 4.1: Export ONNX model — `scripts/export_model.py`
- **Status**: 🔲 Blocked — **strategy failed profitability gate**

### Task 4.2: Update Go features — `internal/features/builder.go`
- **Status**: 🔲 Blocked — **strategy failed profitability gate**

### Task 4.3: Update Go strategy — `internal/strategy/signal.go`
- **Status**: 🔲 Blocked — **strategy failed profitability gate**

### Task 4.4: Update config — `config.yaml`
- **Status**: 🔲 Blocked — **strategy failed profitability gate**

---

## Possible Next Steps

**Plan B is dead.** Two walk-forward runs (without and with funding/daily data) both failed all profitability gates. Adding more features made it worse. The strategy architecture is fundamentally flawed.

### Options:

1. **Plan C: Mean-Reversion on Shorter Timeframe**
   - 1h or 15m timeframe with Bollinger Band / RSI mean-reversion
   - Higher trade frequency = more statistical significance
   - Pairs/spread trading between correlated assets (ETH/BTC)

2. **Plan D: Pure Trend Following (No ML)**
   - Simple moving average crossover / breakout with ATR-based sizing
   - Remove XGBoost entirely — it's adding noise on 4h crypto
   - Focus on risk management and position sizing over prediction
   - Donchian channel breakout with trailing stops

3. **Plan E: Volatility Harvesting**
   - Sell options/straddles on high IV, delta-hedge
   - Funding rate arbitrage (collect positive funding)
   - Grid trading in ranging markets

4. **Plan F: Alternative Data**
   - On-chain metrics (exchange flows, whale alerts, stablecoin supply)
   - Liquidation cascade detection
   - Order flow / CVD analysis on shorter timeframes

---

## Existing Files Reference

| File | Purpose | Status |
|------|---------|--------|
| `scripts/fetch_data.py` | OHLCV + funding + daily fetcher | ✅ Code complete, data NOT fetched for funding/daily |
| `scripts/build_features_v2.py` | V2 feature engineering (29 features) | ✅ Complete |
| `scripts/labeling.py` | Triple barrier labeling | ✅ Complete |
| `scripts/primary_signals.py` | Rule-based trend/breakout signals | ✅ Complete |
| `scripts/train_meta_model.py` | Meta-label XGBoost training | ✅ Complete, not independently run |
| `scripts/walk_forward.py` | Walk-forward validation | ✅ Complete + run |
| `scripts/backtest_v2.py` | Enhanced backtester with profitability gate | ✅ Code complete, NOT run |
| `scripts/build_features.py` | Original 5m feature eng | Legacy |
| `scripts/train_4h.py` | Plan A 4h binary training | Legacy (failed) |
| `scripts/train_binary.py` | 5m binary training | Legacy |
| `scripts/export_model.py` | ONNX export | Reusable for future models |
| `scripts/backtest.py` | Original backtester (has bugs) | Legacy (replaced by backtest_v2.py) |
| `data_4h/` | 4h OHLCV parquet (6yr, 4 symbols) | Primary data source |
| `data_4h/funding/` | Funding rate data | ✅ Fetched (6570 records/symbol, 6yr) |
| `data_daily/` | Daily OHLCV data | ✅ Fetched (2190 bars/symbol, 6yr) |
| `results/` | Walk-forward Run 1 output (no funding/daily) | Failed all gates |
| `results_v2/` | Walk-forward Run 2 output (with funding/daily) | Failed all gates, WORSE |
| `models_meta/` | Meta-model output | **DOES NOT EXIST** |

---

## Change Log

| Date | Change |
|------|--------|
| 2026-02-08 | Plan B analyzed, revised plan created, implementation started |
| 2026-02-08 | Phase 1-3 code complete: fetch_data.py (funding+daily), build_features_v2.py, labeling.py, primary_signals.py, train_meta_model.py, walk_forward.py, backtest_v2.py |
| 2026-02-08 | Walk-forward validation run (without funding/daily data) — **ALL gates FAILED** except trades/day |
| 2026-02-08 | Fetched funding rate + daily OHLCV data for all 4 symbols (6yr each) |
| 2026-02-08 | Walk-forward Run 2 (with funding/daily data) — **ALL gates FAILED, WORSE than Run 1** |
| 2026-02-08 | **Plan B declared dead.** Root cause: strategy architecture is fundamentally flawed, not a data problem |
| 2026-02-08 | Progress doc updated with Run 2 results, comparison table, and Plan C/D/E/F options |
