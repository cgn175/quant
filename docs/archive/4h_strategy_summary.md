# 4H Model Strategy Summary

## Overview

This document summarizes the results of training and backtesting XGBoost binary classifiers on 4-hour OHLCV candles for BTC/USDT, ETH/USDT, SOL/USDT, and BNB/USDT. The conclusion is that **this strategy is unprofitable and not ready for live trading**.

## Data

- **Source:** Binance via CCXT
- **Timeframe:** 4h candles
- **History:** ~6 years (Feb 2020 - Feb 2026), 12,000-13,000 bars per symbol
- **Symbols:** BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT

## Model Architecture

- **Algorithm:** XGBoost binary classifier (`binary:logistic`)
- **Classification:** Binary - UP (1) vs DOWN (0), NEUTRAL bars dropped
- **Return threshold:** 0.5% (next 4h bar)
- **Features:** 33 technical indicators (no sentiment)
  - Price: close, log returns (1/2/6/12 bar lags)
  - Trend: EMA 5/9/21/50, SMA 6/30/42, trend alignment
  - Oscillators: RSI 7/14, MACD
  - Volatility: Bollinger Bands (width, %B), ATR 14, ATR ratio
  - Volume: volume ratio, volume surge
  - Momentum: ROC 6/12
  - Time: hour sin/cos, day sin/cos
- **Hyperparameter tuning:** Optuna, 50 trials per symbol
- **Train/test split:** Time-series split at 2025-02-08 (no shuffling)
  - Train: Feb 2020 - Jan 2025 (~5 years)
  - OOS validation: Feb 2025 - Feb 2026 (1 year)

## Model Training Results

| Symbol   | Train Size | Val Size | Train Acc | Val Acc | Val F1 |
|----------|-----------|----------|-----------|---------|--------|
| BTC/USDT | 5,511     | 903      | 55.0%     | 52.5%   | 0.675  |
| ETH/USDT | 6,456     | 1,293    | 55.3%     | 51.0%   | 0.669  |
| SOL/USDT | 7,459     | 1,505    | 52.3%     | 50.2%   | 0.665  |
| BNB/USDT | 6,510     | 1,108    | 53.8%     | 53.2%   | 0.659  |

**Key observation:** Validation accuracy is barely above 50% (coin flip). The F1 scores are inflated because the model overwhelmingly predicts UP (high recall on UP class, near-zero recall on DOWN class).

## Python Simple Backtest (1-bar hold, long only)

At P(UP) > 0.55 threshold:

| Symbol   | Trades | Win Rate | Total PnL | Avg PnL/Trade | Sharpe |
|----------|--------|----------|-----------|---------------|--------|
| BTC/USDT | 82     | 47.6%    | -7.5%     | -0.091%       | -2.68  |
| ETH/USDT | 717    | 53.4%    | -17.2%    | -0.024%       | -0.54  |
| SOL/USDT | 495    | 51.5%    | -75.2%    | -0.152%       | -3.34  |
| BNB/USDT | 314    | 56.4%    | -12.3%    | -0.039%       | -1.10  |

## Go Engine Backtest (OOS only: Feb 2025 - Feb 2026)

**Backtest parameters:**
- Threshold UP: 0.55, Threshold DOWN: 0.45
- Stop loss: 2%, Take profit: 4%
- Fees: 0.025%, Slippage: 5bp
- Long only (shorts disabled)
- Initial equity: $10,000

### Aggregate Results

| Metric           | Value         |
|-----------------|---------------|
| Period          | Feb 2025 - Feb 2026 (355 days) |
| Final Equity    | -$1,381       |
| Net PnL         | -$11,381 (-113.81%) |
| Total Trades    | 984           |
| Win Rate        | 31.0%         |
| Profit Factor   | 0.83          |
| Max Drawdown    | 117.08%       |
| Sharpe Ratio    | -2.80         |

### Per-Symbol Breakdown

| Symbol   | Trades | Win Rate | PnL        | Avg PnL/Trade | Profit Factor |
|----------|--------|----------|------------|---------------|---------------|
| BTC/USDT | 69     | 31.9%    | -$711      | -$10.31       | 0.86          |
| ETH/USDT | 386    | 32.4%    | -$3,277    | -$8.49        | 0.88          |
| SOL/USDT | 342    | 29.5%    | -$4,878    | -$14.26       | 0.77          |
| BNB/USDT | 187    | 30.5%    | -$2,514    | -$13.44       | 0.82          |

### Monthly PnL

| Month    | PnL        | Trades |
|----------|------------|--------|
| 2025-02  | -$1,064    | 47     |
| 2025-03  | -$2,845    | 120    |
| 2025-04  | +$1,571    | 80     |
| 2025-05  | -$124      | 89     |
| 2025-06  | -$1,173    | 58     |
| 2025-07  | +$1,578    | 64     |
| 2025-08  | +$1,091    | 78     |
| 2025-09  | -$602      | 46     |
| 2025-10  | -$1,289    | 114    |
| 2025-11  | -$4,177    | 110    |
| 2025-12  | -$1        | 63     |
| 2026-01  | -$1,895    | 55     |
| 2026-02  | -$2,451    | 60     |

## Root Cause Analysis

1. **Model has no real edge:** Validation accuracy ~50-53% is noise-level. The model cannot reliably predict 4h returns from TA indicators alone.

2. **Asymmetric TP/SL destroys win rate:** With 2% SL and 4% TP (1:2 risk/reward), the model needs ~33% win rate to break even after fees. The backtest achieved 31% - below breakeven.

3. **Too many signals:** The model fires frequently (984 trades in 355 days = ~2.8 trades/day across 4 symbols), suggesting it's not selective enough.

4. **Feature limitations:** 33 purely technical features on 4h bars may not contain enough predictive signal. No sentiment, no orderbook, no cross-asset features.

5. **Regime blindness:** The model doesn't adapt to bull/bear/sideways markets. SOL dropped from $177 to $84 in the test period and the model kept going long.

## Verdict

**UNPROFITABLE - DO NOT trade live.**

The 4h XGBoost binary strategy with pure TA features does not generate a tradeable edge. The model predictions are essentially random, and after fees/slippage the strategy loses money consistently.

## Possible Directions for Next Strategy

- Add sentiment/news features as regime filters
- Try different timeframes (1h, daily) or multi-timeframe fusion
- Use different model architectures (LSTM, Transformer, ensemble)
- Add market microstructure features (orderbook imbalance, funding rates)
- Consider trend-following rules instead of ML prediction
- Explore mean-reversion on shorter timeframes
- Add cross-asset correlation features (BTC dominance, ETH/BTC ratio)
- Implement dynamic position sizing / regime detection
