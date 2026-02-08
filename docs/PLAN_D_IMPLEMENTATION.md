# Plan D: Pure Trend Following + Funding Rate Edge (No ML)

## Why Plan D

### Root Cause of Plan A & B Failures

Both Plan A (4h XGBoost binary) and Plan B (meta-labeling with 29 features) failed catastrophically:

| Plan | Win Rate | Sharpe | Max DD | Verdict |
|------|----------|--------|--------|---------|
| A | 31% | N/A | -113% | Dead |
| B Run 1 | 32.9% | -2.47 | 62.7% | Dead |
| B Run 2 | 21.5% | -6.26 | 77.0% | Dead (worse with more features) |

**The fundamental problem**: XGBoost on TA features cannot predict 4h crypto returns. Adding more features (funding, daily context) made it worse — the model fits noise. Meta-labeling cannot rescue unpredictive base signals.

### Why Remove ML Entirely

1. **ML needs edge in features, not in the model** — our features (TA indicators) are public knowledge, priced in, and have no informational edge over other participants
2. **Overfitting is the #1 killer** — walk-forward showed wildly inconsistent behavior across windows (WR 0% to 50%), classic noise-fitting
3. **Simpler systems are more robust** — trend following has worked for decades across all asset classes because it exploits a behavioral edge (herding, slow information diffusion), not a statistical pattern
4. **Fewer parameters = less to break** — an ML model has hundreds of parameters; a trend system has ~5

### Why Plan D Over C/E/F

| Plan | Approach | Verdict |
|------|----------|---------|
| **C: Mean-Reversion (15m/1h)** | Higher frequency, BB/RSI reversion | Needs new data, more trades = more fees, mean-reversion in trending crypto is dangerous |
| **D: Pure Trend Following** | No ML, systematic rules, ATR-based | Addresses root cause directly, uses existing data, battle-tested methodology |
| **E: Volatility Harvesting** | Funding arb, grid trading | Funding arb is real but needs futures infra, grid trading needs range detection (another prediction problem) |
| **F: Alternative Data** | On-chain, liquidations, CVD | Interesting but massive new data pipeline, uncertain edge, high complexity |

**Plan D wins because it directly addresses the root cause**: stop trying to predict, start following. We borrow the best element from Plan E (funding rate as a filter, not a predictor) to add a real structural edge.

---

## Strategy Design

### Core Philosophy

> "Don't predict. React. Let price tell you the trend. Let risk management do the rest."

The strategy has three layers:

```
Layer 1: Trend Detection (mechanical rules)
    ├── Donchian Channel Breakout (primary)
    └── Dual Moving Average Crossover (confirmation)

Layer 2: Regime Filter (avoid bad environments)
    ├── ADX filter (is there a trend?)
    ├── Volatility filter (is volatility normal?)
    └── Funding rate filter (is the crowd too one-sided?)

Layer 3: Risk Management (the actual edge)
    ├── ATR-based position sizing
    ├── Trailing stop (Chandelier Exit)
    ├── Daily loss cap
    └── Correlation-aware exposure limits
```

### Layer 1: Entry Signals

#### Signal A — Donchian Channel Breakout

The Donchian Channel is the purest trend-following signal: buy when price makes a new N-bar high.

```
LONG ENTRY:
  close > highest_high(20 bars)          # 20-bar = ~3.3 days on 4h
  AND close > EMA(50)                     # price above long-term trend
  AND volume_ratio(20) > 1.0              # volume confirms breakout

SHORT ENTRY:
  close < lowest_low(20 bars)
  AND close < EMA(50)
  AND volume_ratio(20) > 1.0
```

**Parameters:**
- Donchian period: 20 bars (4h = 80 hours = 3.3 days)
- EMA trend filter: 50 bars (4h = 200 hours = 8.3 days)
- Volume confirmation: current bar volume > 20-bar average

#### Signal B — Dual EMA Crossover (Confirmation)

Only used to **confirm** Donchian signals, not as standalone entries.

```
LONG CONFIRMATION:
  EMA(9) > EMA(21)                        # fast above slow
  AND EMA(9) crossed above EMA(21) within last 5 bars

SHORT CONFIRMATION:
  EMA(9) < EMA(21)
  AND EMA(9) crossed below EMA(21) within last 5 bars
```

#### Combined Entry Logic

```
LONG ENTRY = Signal A (Donchian breakout) AND Signal B (EMA confirmation)
SHORT ENTRY = Signal A (Donchian breakdown) AND Signal B (EMA confirmation)
```

This dual confirmation reduces false breakouts significantly. We don't need ML to filter — two independent trend signals agreeing IS the filter.

### Layer 2: Regime Filters

These filters **block** trades in unfavorable environments. They don't predict — they detect.

#### Filter 1: ADX Trend Strength

```
ADX(14) > 20                              # trend exists (ADX < 20 = choppy/ranging)
```

Rationale: Trend following in ranging markets gets whipsawed. ADX is a pure measure of trend strength, not direction.

#### Filter 2: Volatility Regime

```
atr_ratio = ATR(14) / ATR(50)
ALLOW TRADE if 0.5 < atr_ratio < 2.5      # normal volatility
BLOCK TRADE if atr_ratio > 2.5            # extreme volatility (crash/pump)
BLOCK TRADE if atr_ratio < 0.5            # dead market (no trend to follow)
```

Rationale: Extreme volatility causes stop hunts and slippage. Dead markets have no trend.

#### Filter 3: Funding Rate

This is the structural edge borrowed from Plan E. Funding rate reflects leveraged positioning:

```
BLOCK LONG if funding_rate_8h_avg > 0.05%   # market extremely long — crowded trade
BLOCK SHORT if funding_rate_8h_avg < -0.05%  # market extremely short — crowded trade
REDUCE SIZE by 50% if |funding_rate_8h_avg| > 0.03%  # elevated but not extreme
```

Rationale: Extreme funding = overcrowded positioning = mean-reversion risk. We're not predicting reversal — we're avoiding joining the crowd at the peak.

### Layer 3: Risk Management

This is where the real edge lives. Trend following makes money not by being right often (typical WR 35-45%), but by cutting losses short and letting winners run.

#### Position Sizing

```
risk_per_trade = 1.0% of equity
stop_distance = 2.0 * ATR(14)
position_size = (equity * risk_per_trade) / (entry_price * stop_distance_pct)
max_notional = equity * max_leverage (2x)
final_size = min(position_size, max_notional / entry_price)
```

#### Stop Loss — Chandelier Exit (Trailing)

```
Initial stop (long):  entry_price - 3.0 * ATR(14)
Initial stop (short): entry_price + 3.0 * ATR(14)

Trailing (long):  max(previous_stop, highest_high(10) - 3.0 * ATR(14))
Trailing (short): min(previous_stop, lowest_low(10) + 3.0 * ATR(14))
```

The trailing stop **never moves against the position** — it only tightens. This lets winners run while mechanically locking in profits.

#### Take Profit

**No fixed take profit.** The trailing stop IS the exit mechanism. Trend following profits come from the long tail of big trends — capping upside destroys the edge.

However, we add a **partial exit** rule:

```
At 3R profit (3x initial risk):
  Close 25% of position
  Move stop to breakeven on remainder

At 6R profit:
  Close another 25%
  Trailing stop continues on remaining 50%
```

#### Daily Loss Cap

```
If daily_realized_pnl < -3% of equity:
  HALT all new entries for rest of day
  Existing positions keep trailing stops active
```

#### Correlation-Aware Exposure

```
Max 2 positions in same direction on correlated pairs
  (BTC/USDT and ETH/USDT are highly correlated)
  (SOL/USDT and BNB/USDT are moderately correlated with BTC)

Max total exposure: 4 simultaneous positions
```

---

## Implementation Plan

### Phase 0: Data Preparation

**Goal**: Ensure we have all data needed for backtesting.

#### Task 0.1: Fetch 1h OHLCV Data (New)

While Plan D uses 4h as primary, we need 1h data for:
- More granular trailing stop simulation (4h bars miss intra-bar stop triggers)
- Future multi-timeframe confirmation

```bash
python scripts/fetch_data.py \
  --symbols "BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT" \
  --timeframe 1h \
  --days 2190 \
  --output-dir data_1h
```

**Estimated data**: 2190 * 24 = ~52,560 bars per symbol.

#### Task 0.2: Verify Existing Data

```
data_4h/         — 4h OHLCV (6yr, 4 symbols)     ✅ exists
data_4h/funding/ — funding rates (6yr, 4 symbols)  ✅ exists
data_daily/      — daily OHLCV (6yr, 4 symbols)    ✅ exists
```

### Phase 1: Python Strategy Implementation & Backtesting

**Goal**: Implement the full strategy in Python, backtest with walk-forward, pass profitability gate.

#### Task 1.1: Create `scripts/trend_signals.py` — Signal Generation

Implements Layer 1 (entry signals) + Layer 2 (regime filters):

```python
# Functions to implement:
def donchian_breakout(df, period=20) -> pd.Series:
    """Returns 1 (long), -1 (short), 0 (no signal)"""

def ema_crossover_confirmation(df, fast=9, slow=21, lookback=5) -> pd.Series:
    """Returns 1 (bullish), -1 (bearish), 0 (no confirmation)"""

def combined_entry_signal(df) -> pd.Series:
    """Donchian breakout AND EMA confirmation"""

def adx_filter(df, period=14, threshold=20) -> pd.Series:
    """Returns True if ADX > threshold"""

def volatility_filter(df, fast=14, slow=50, low=0.5, high=2.5) -> pd.Series:
    """Returns True if atr_ratio in [low, high]"""

def funding_filter(df_funding, extreme=0.0005, elevated=0.0003) -> tuple:
    """Returns (allow_long, allow_short, size_multiplier)"""

def generate_signals(df, df_funding=None) -> pd.DataFrame:
    """Full signal pipeline: entries + filters -> final signals"""
```

**Input**: 4h OHLCV DataFrame + optional funding rate DataFrame
**Output**: DataFrame with columns: `signal` (-1/0/1), `signal_type`, `size_multiplier`, `atr`, `stop_price`

#### Task 1.2: Create `scripts/backtest_trend.py` — Strategy Backtester

Implements Layer 3 (risk management) with bar-by-bar simulation:

```python
class TrendFollowingBacktester:
    """
    Core simulation:
    - Processes bars chronologically
    - Manages positions with trailing stops
    - Handles partial exits at 3R/6R
    - Enforces daily loss caps
    - Tracks correlation-aware exposure limits
    - Applies realistic fees (0.04% taker) and slippage (5bps)
    """

    def __init__(self, initial_equity=10000, risk_per_trade=0.01,
                 atr_stop_mult=3.0, max_leverage=2.0, max_daily_loss=0.03,
                 fee_rate=0.0004, slippage_bps=5):
        ...

    def run(self, signals_dict: dict[str, pd.DataFrame]) -> BacktestResult:
        """
        signals_dict: {symbol: DataFrame with signal, atr, stop_price, ...}
        Returns: equity curve, trades, metrics
        """

    class Position:
        """Tracks: entry, stop, trailing_stop, partial_exits, R-multiples"""

    class BacktestResult:
        """
        Metrics: total_return, cagr, sharpe, sortino, calmar,
                 max_drawdown, win_rate, profit_factor, expectancy,
                 avg_winner/loser, max_consecutive_losses,
                 trades_per_month, profitable_months_pct
        """
```

Key implementation details:
- **Intra-bar stop checks**: Use high/low to detect stop triggers within 4h bars
- **Trailing stop updates**: After each bar, update Chandelier Exit
- **Partial exit logic**: At 3R and 6R, reduce position and adjust stops
- **Fee model**: 0.04% per side (Binance futures taker) + 5bps slippage
- **Equity curve**: Track after every trade close, not every bar

#### Task 1.3: Create `scripts/walk_forward_trend.py` — Walk-Forward Validation

Unlike Plan B's walk-forward (which retrained ML each window), this walk-forward:
- **Does NOT retrain** (no model to train!)
- Tests the SAME rules across all windows
- Validates parameter robustness
- Checks for regime dependency

```python
def walk_forward_validate(
    data_dict: dict,                    # {symbol: df}
    funding_dict: dict | None,          # {symbol: df}
    window_size: int = 180,             # days
    step_size: int = 30,                # days
    params: dict = DEFAULT_PARAMS,      # strategy params
) -> WalkForwardResult:
    """
    Splits data into rolling windows.
    Runs backtest on each window with identical parameters.
    Reports per-window and aggregate metrics.
    Checks profitability gate.
    """
```

**Profitability Gate (revised for trend following)**:

| Metric | Threshold | Rationale |
|--------|-----------|-----------|
| Win rate | > 35% | Trend following has lower WR but higher R:R |
| Expectancy per trade | > 0.5% | Higher bar because fewer trades |
| Profit factor | > 1.3 | Same as Plan B |
| Sharpe ratio | > 0.8 | Slightly relaxed — trend following is lumpier |
| Max drawdown | < 30% | Trend following has bigger drawdowns |
| Avg winner / avg loser | > 2.0 | THIS is the key metric — must let winners run |
| Profitable months | > 50% | Relaxed — trend profits come in bursts |
| Consistency | > 70% windows profitable | Most windows should be net positive |

#### Task 1.4: Parameter Sensitivity Analysis

After initial run, sweep key parameters to ensure robustness:

```python
PARAM_GRID = {
    'donchian_period': [15, 20, 25, 30],
    'ema_fast': [7, 9, 12],
    'ema_slow': [18, 21, 26],
    'atr_stop_mult': [2.0, 2.5, 3.0, 3.5],
    'adx_threshold': [15, 20, 25],
    'risk_per_trade': [0.005, 0.01, 0.015],
}
```

**Robustness criteria**: The strategy must be profitable across >70% of parameter combinations in the "neighborhood" of default params. If it only works at exact params, it's curve-fit.

### Phase 2: Go Integration (Only After Phase 1 Passes Gate)

#### Task 2.1: Add Indicators to Go — `internal/features/indicators.go`

New indicators needed:

```go
// Donchian Channel — rolling highest high / lowest low
func DonchianUpper(highs []float64, period int) []float64
func DonchianLower(lows []float64, period int) []float64

// ADX — Average Directional Index
func ADX(highs, lows, closes []float64, period int) []float64

// Chandelier Exit — trailing stop based on ATR
func ChandelierLong(highs, closes []float64, atr []float64, period int, mult float64) []float64
func ChandelierShort(lows, closes []float64, atr []float64, period int, mult float64) []float64

// EMA Crossover Detection
func EMACrossedAbove(fast, slow []float64, lookback int) []bool
func EMACrossedBelow(fast, slow []float64, lookback int) []bool
```

Existing indicators to reuse: `EMA`, `RSI`, `ATR`, `VolumeRatio`, `LogReturn`.

#### Task 2.2: Create `internal/strategy/trend.go` — Strategy Logic

```go
type TrendStrategy struct {
    // Params
    DonchianPeriod   int     // 20
    EMAFast          int     // 9
    EMASlow          int     // 21
    EMAConfirmBars   int     // 5
    EMATrend         int     // 50
    ATRPeriod        int     // 14
    ATRStopMult      float64 // 3.0
    ADXPeriod        int     // 14
    ADXThreshold     float64 // 20.0
    VolatilityLow    float64 // 0.5
    VolatilityHigh   float64 // 2.5
    FundingExtreme   float64 // 0.0005
    FundingElevated  float64 // 0.0003

    // State (per symbol)
    positions map[string]*Position
    dailyPnL  float64
}

func (s *TrendStrategy) OnBar(symbol string, candle Candle, funding *float64) *Signal
func (s *TrendStrategy) UpdateTrailingStop(symbol string, candle Candle) *ExitSignal
func (s *TrendStrategy) CheckPartialExit(symbol string, currentPrice float64) *PartialExitSignal
```

#### Task 2.3: Update `internal/exchange/binance.go` — Funding Rate Stream

Add WebSocket subscription for mark price / funding rate:

```go
func (c *BinanceClient) SubscribeFundingRate(symbol string) error
// Stream: <symbol>@markPrice@1s (includes funding rate + next funding time)
```

#### Task 2.4: Create `internal/data/funding.go` — Funding Rate Cache

```go
type FundingCache struct {
    rates    map[string][]FundingRate  // symbol -> sorted rates
    mu       sync.RWMutex
}

func (fc *FundingCache) Add(symbol string, rate FundingRate)
func (fc *FundingCache) MovingAverage(symbol string, periods int) float64
func (fc *FundingCache) IsExtreme(symbol string, threshold float64) bool
```

#### Task 2.5: Update Config — `config.yaml`

```yaml
strategy:
  type: trend_following
  donchian_period: 20
  ema_fast: 9
  ema_slow: 21
  ema_confirm_bars: 5
  ema_trend: 50
  atr_period: 14
  atr_stop_multiplier: 3.0
  adx_period: 14
  adx_threshold: 20.0
  volatility_low: 0.5
  volatility_high: 2.5

  funding_filter:
    enabled: true
    extreme_threshold: 0.0005
    elevated_threshold: 0.0003
    size_reduction: 0.5

  partial_exits:
    enabled: true
    first_target_r: 3.0
    first_exit_pct: 0.25
    second_target_r: 6.0
    second_exit_pct: 0.25

risk:
  max_risk_per_trade_pct: 1.0
  max_daily_loss_pct: 3.0
  max_open_positions: 4
  max_leverage: 2.0
  max_correlated_positions: 2

execution:
  use_limit_orders: false
  slippage_bps: 5
  fee_rate_pct: 0.04

exchange:
  name: binance
  testnet: true           # paper trading first
  symbols:
    - BTCUSDT
    - ETHUSDT
    - SOLUSDT
    - BNBUSDT
  bar_size: 4h
```

#### Task 2.6: Update Main Loop — `cmd/bot/main.go`

Replace `signalLoop` to use `TrendStrategy`:

```go
func trendStrategyLoop(ctx context.Context, symbol string, ...) {
    for {
        select {
        case candle := <-candleCh:
            // 1. Update indicators
            // 2. Check trailing stops on existing positions
            // 3. Check partial exits
            // 4. Generate new entry signals
            // 5. Apply regime filters
            // 6. Send orders to execution engine
        case <-ctx.Done():
            return
        }
    }
}
```

### Phase 3: Paper Trading & Validation

#### Task 3.1: Paper Trading (2-4 Weeks)

```bash
./bin/bot --config config.yaml --mode paper
```

Monitor:
- Entry/exit timing vs expected behavior
- Trailing stop mechanics
- Funding rate filter activations
- Daily PnL and drawdown tracking
- Latency (bar processing, order submission)

#### Task 3.2: Validation Criteria

Before going live, paper trading must show:
- No bugs in trailing stop logic (verified against Python backtest)
- All regime filters activating correctly
- Partial exits triggering at correct R-levels
- Daily loss cap working
- Correlation limits enforced
- Prometheus metrics reporting correctly
- Telegram alerts firing on trade open/close/daily summary

### Phase 4: Live Deployment

#### Task 4.1: Small Capital Deployment

- Start with minimum viable capital (~$500-1000)
- Monitor for 2 weeks
- Compare live fills vs paper trading expectations
- Check slippage and fee accuracy

#### Task 4.2: Scale Up

If 2-week live results are within 80% of backtest expectations:
- Increase capital to target size
- Enable all 4 symbols
- Monitor daily

---

## Expected Performance (Realistic)

Based on academic research on trend following in crypto (Bianchi & Babiak 2022, Liu & Tsyvinski 2021):

| Metric | Conservative Estimate | Optimistic Estimate |
|--------|----------------------|---------------------|
| Annual return | 8-12% | 15-25% |
| Sharpe ratio | 0.6-1.0 | 1.0-1.5 |
| Max drawdown | 15-25% | 10-20% |
| Win rate | 35-42% | 40-48% |
| Avg winner / avg loser | 2.0-3.0x | 2.5-4.0x |
| Trades per month | 8-15 | 10-20 |
| % profitable months | 50-60% | 55-65% |

**Key insight**: Trend following makes money through **asymmetric payoffs** (big winners, small losers), NOT through high win rate. A 38% win rate with 2.5:1 reward-to-risk is highly profitable:

```
Expected value = (0.38 * 2.5) - (0.62 * 1.0) = 0.95 - 0.62 = +0.33R per trade
```

---

## Why This Will Work (Unlike Plan A/B)

1. **No prediction** — We don't predict price direction. We detect existing trends and follow them. The edge comes from behavioral finance (herding, momentum), not statistical prediction.

2. **No overfitting** — 5 parameters vs 500+. No ML model to overfit. Same rules for all time periods.

3. **Structural edge from funding rates** — Funding rate is NOT a prediction feature. It's a structural filter: when everyone is levered long, avoid going long. This is a real market microstructure edge.

4. **Risk management IS the strategy** — The trailing stop and position sizing generate the asymmetric payoff profile. We don't need to be right often; we need to be right big.

5. **Battle-tested methodology** — Trend following has worked for 40+ years across commodities, FX, equities, and crypto. It exploits a persistent behavioral bias (trend persistence / momentum effect).

6. **Transparent and debuggable** — Every trade can be explained: "price broke 20-bar high, volume confirmed, ADX showed trend, funding was neutral, entered with 3-ATR stop." No black box.

---

## File Structure (New/Modified)

```
scripts/
  trend_signals.py          # NEW — signal generation (Layer 1 + 2)
  backtest_trend.py          # NEW — trend following backtester (Layer 3)
  walk_forward_trend.py      # NEW — walk-forward validation
  param_sensitivity.py       # NEW — parameter robustness analysis

internal/
  features/
    indicators.go            # MODIFIED — add Donchian, ADX, Chandelier Exit
  strategy/
    trend.go                 # NEW — trend following strategy
  data/
    funding.go               # NEW — funding rate cache
  exchange/
    binance.go               # MODIFIED — add funding rate stream

config.yaml                  # MODIFIED — trend following config

docs/
  PLAN_D_IMPLEMENTATION.md   # THIS FILE
  PLAN_D_PROGRESS.md         # Track progress (create when starting)
```

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Choppy market regime (whipsaw) | High | Medium | ADX filter blocks trades in ranging markets |
| Flash crash stops triggered | Medium | High | 3-ATR stops provide wide buffer; daily loss cap limits damage |
| Funding rate data unavailable | Low | Low | Strategy works without it; just loses one filter |
| Slippage exceeds estimates | Medium | Medium | Use limit orders option; wider slippage buffer; 4h timeframe = less urgency |
| Correlated positions all stopped | Medium | High | Correlation limit of 2 positions per direction; partial exits reduce exposure |
| Extended bear market (no longs) | Medium | Low | Short signals enabled; ADX filter detects trend; still enter shorts |
| Strategy decay over time | Low | Medium | Parameters are robust to ranges; re-validate annually |

---

## Decision

**Proceed with Plan D: Pure Trend Following + Funding Rate Edge.**

Start with Phase 1 (Python backtest). If profitability gate is passed, proceed to Phase 2 (Go integration). If gate fails, the failure will be clean and informative — we'll know whether the issue is the signals, the filters, or the risk management, because each layer is independent and testable.

No ML. No complexity. Let the trend and the math do the work.
