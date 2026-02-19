# Optimization Spec: Plan D (Turtle 2026) Refinement

## Context
The "Plan D" trend-following bot is currently active (Paper Trading). The core logic (Donchian Breakout + Regime Filter) is solid.

**Goal:** Apply 5 specific "patches" to improve Drawdown, Profit Retention, and Risk Management without rewriting the base engine.

## Issue Tracking

| Issue ID | Patch | Priority | Status |
|----------|-------|----------|--------|
| quant-lj6 | Epic: All Improvements | P1 | In Progress |
| quant-lj6.1 | Whipsaw Defense | P1 HIGH | Open |
| quant-lj6.2 | Dynamic Chandelier | P1 HIGH | Open |
| quant-lj6.3 | Correlation Guard | P1 HIGH | Open |
| quant-lj6.4 | Volatility Scalar | P2 MEDIUM | Open |
| quant-lj6.5 | Breakout Retest | P3 LOW | Open |

## Deployment Order
1. **Batch 1 (Deploy First - Highest ROI):** Patches 1, 2, 3
2. **Batch 2:** Patch 4
3. **Batch 3 (Optional):** Patch 5

---

## Patch 1: "Whipsaw Defense" (Entry Filter)
**Issue:** `quant-lj6.1`

**Objective:** Reduce false breakouts by filtering weak closes.

**Logic:**
Instead of blindly entering when Close > 20_Day_High, require the breakout candle to be bullish (Close > Open). This prevents entering on "Shooting Star" candles where buyers failed to hold the high.

**Code Implementation (Go):**
```go
// In OnBar() after Layer 1 signal detection:

// NEW: Candle Color Filter - prevent entering on shooting stars
isGreenCandle := last.Close > last.Open
if longSignal && !isGreenCandle {
    log.Debug().Str("symbol", symbol).Msg("whipsaw filter blocked LONG (red candle)")
    return nil
}
if shortSignal && isGreenCandle {
    log.Debug().Str("symbol", symbol).Msg("whipsaw filter blocked SHORT (green candle)")
    return nil
}

// NEW: BB Bandwidth dead market filter
bbWidth := features.BollingerBandwidth(candles, 20, 2.0)
if bbWidth != nil {
    bbWidthPctile := features.RollingQuantile(bbWidth, 100, 0.10)
    if bbWidthPctile != nil && bbWidth[idx] < bbWidthPctile[idx] {
        log.Debug().Str("symbol", symbol).Float64("bb_width", bbWidth[idx]).Msg("dead market filter blocked signal")
        return nil
    }
}
```

**Files to modify:**
- `internal/strategy/trend.go` - OnBar function
- `internal/features/indicators.go` - Add BollingerBandwidth, RollingQuantile

---

## Patch 2: "Dynamic Chandelier Exit" (Profit Locking)
**Issue:** `quant-lj6.2`

**Objective:** Tighten stops as the trade becomes profitable to protect unrealized gains.

**Logic:**
- Initial: Stop is 3.0 * ATR from the High
- Level 1 (>2R Profit): Tighten to 2.5 * ATR
- Level 2 (>4R Profit): Tighten to 2.0 * ATR
- Level 3 (>6R Profit): Tighten to 1.5 * ATR

**Code Implementation (Go):**
```go
// In UpdateTrailingStop() - calculate dynamic multiplier based on R-multiple
func (ts *TrendStrategy) getDynamicATRMultiplier(pos *TrendPosition, currentHigh float64) float64 {
    // Calculate current R-Multiple
    var currentProfit float64
    if pos.Side == "LONG" {
        currentProfit = currentHigh - pos.EntryPrice
    } else {
        currentProfit = pos.EntryPrice - currentHigh // currentHigh is actually currentLow for shorts
    }
    rMultiple := currentProfit / pos.InitialRisk
    
    // Select multiplier based on profit level
    switch {
    case rMultiple > 6:
        return 1.5
    case rMultiple > 4:
        return 2.0
    case rMultiple > 2:
        return 2.5
    default:
        return ts.config.ATRStopMult // 3.0 default
    }
}
```

**Files to modify:**
- `internal/strategy/trend.go` - UpdateTrailingStop function

---

## Patch 3: "Correlation Guard" (Portfolio Risk)
**Issue:** `quant-lj6.3`

**Objective:** Prevent over-exposure to a single sector (e.g., going Long on 4 different L1 coins simultaneously).

**Logic:**
Maintain a sector_map and check active_positions before entry.
- Rule: Max 1 position per sector
- Rule: Max 3 positions total

**Sector Map:**
```go
var SectorMap = map[string]string{
    "BTCUSDT":  "BTC",
    "ETHUSDT":  "L1",
    "SOLUSDT":  "L1",
    "AVAXUSDT": "L1",
    "ADAUSDT":  "L1",
    "FETUSDT":  "AI",
    "RNDRUSDT": "AI",
    "WLDUSDT":  "AI",
    "DOGEUSDT": "MEME",
    "SHIBUSDT": "MEME",
    "PEPEUSDT": "MEME",
    "BNBUSDT":  "EXCHANGE",
}
```

**Code Implementation (Go):**
```go
// In TrendConfig - add sector limits
MaxPositionsPerSector int     // 1
MaxTotalPositions     int     // 3

// In canEnterLocked() - add sector check
func (ts *TrendStrategy) canEnterLocked(symbol string, direction string) (bool, string) {
    // ... existing checks ...
    
    // Sector limit check
    newSector := SectorMap[symbol]
    if newSector == "" {
        newSector = "OTHER"
    }
    
    sectorCount := 0
    for _, pos := range ts.positions {
        posSector := SectorMap[pos.Symbol]
        if posSector == "" {
            posSector = "OTHER"
        }
        if posSector == newSector {
            sectorCount++
        }
    }
    
    if sectorCount >= ts.config.MaxPositionsPerSector {
        return false, "sector_limit"
    }
    
    return true, ""
}
```

**Files to modify:**
- `internal/strategy/trend.go` - Add SectorMap, modify canEnterLocked
- `internal/config/config.go` - Add MaxPositionsPerSector config option

---

## Patch 4: "Volatility Scalar" (Sizing)
**Issue:** `quant-lj6.4`

**Objective:** Adjust position size based on Market Regime (not just individual asset volatility).

**Logic:**
- Calculate a global "Market VIX" (e.g., average ATR% of BTC and ETH)
- If Market is Quiet (ATR% < 2%): Scale Size 1.2x (Safe to take bigger bets)
- If Market is Violent (ATR% > 5%): Scale Size 0.5x (Preserve capital)

**Code Implementation (Go):**
```go
// In a new function or in the main loop
func calculateMarketVolatilityScalar(btcCandles, ethCandles []exchange.Candle) float64 {
    btcATRPct := calculateATRPercent(btcCandles, 14)
    ethATRPct := calculateATRPercent(ethCandles, 14)
    
    marketVol := (btcATRPct + ethATRPct) / 2.0
    
    switch {
    case marketVol > 0.05: // High vol (5%+)
        return 0.5
    case marketVol < 0.02: // Low vol (<2%)
        return 1.2
    default:
        return 1.0
    }
}

func calculateATRPercent(candles []exchange.Candle, period int) float64 {
    atr := features.ATR(candles, period)
    if atr == nil || len(atr) == 0 {
        return 0
    }
    lastClose := candles[len(candles)-1].Close
    if lastClose == 0 {
        return 0
    }
    return atr[len(atr)-1] / lastClose
}

// In CalculatePositionSize - apply market volatility scalar
func (ts *TrendStrategy) CalculatePositionSize(
    equity, entryPrice, stopLoss, sizeMultiplier, marketVolScalar float64,
) float64 {
    // ... existing code ...
    riskAmount := equity * cfg.RiskPerTrade * sizeMultiplier * marketVolScalar
    // ... rest of function ...
}
```

**Files to modify:**
- `internal/strategy/trend.go` - Add market volatility calculation, modify CalculatePositionSize
- `cmd/bot/main.go` - Calculate and pass market volatility to strategy

---

## Patch 5: "Breakout Retest" (Execution)
**Issue:** `quant-lj6.5`

**Objective:** Improve average entry price.

**Logic:**
Breakouts often pull back. Don't FOMO 100% of the size at the candle close.

**Action:**
- Market Buy 50% of size immediately
- Place Limit Buy 50% at Entry_Price - (0.5 * ATR)
- If Limit not filled after 3 candles → Cancel it (Trend is too strong, just ride the 50%)

**Code Implementation (Go):**
```go
// In handleTrendEntry() - split order execution
func handleTrendEntry(ctx context.Context, signal *strategy.Signal, ...) {
    totalSize := calculatePositionSize(...)
    
    // Part 1: Immediate market order (50%)
    marketSize := totalSize * 0.5
    marketOrder := executor.MarketOrder(signal.Symbol, signal.Type, marketSize)
    
    // Part 2: Limit order at pullback level (50%)
    limitSize := totalSize * 0.5
    limitPrice := signal.Price - (0.5 * atrValue) // for longs
    if signal.Type == SignalShort {
        limitPrice = signal.Price + (0.5 * atrValue)
    }
    limitOrder := executor.LimitOrder(signal.Symbol, signal.Type, limitSize, limitPrice)
    
    // Track pending limit order for cancellation after 3 candles
    pendingLimitOrders[signal.Symbol] = &PendingLimitOrder{
        OrderID:      limitOrder.ID,
        Symbol:       signal.Symbol,
        CandleCount:  0,
        MaxCandles:   3,
    }
}

// In handleTrendTick() - check pending limit orders
func checkPendingLimitOrders(symbol string) {
    pending, exists := pendingLimitOrders[symbol]
    if !exists {
        return
    }
    
    pending.CandleCount++
    if pending.CandleCount >= pending.MaxCandles {
        // Cancel unfilled limit order
        executor.CancelOrder(pending.OrderID)
        delete(pendingLimitOrders, symbol)
        log.Info().Str("symbol", symbol).Msg("cancelled unfilled limit order after 3 candles")
    }
}
```

**Files to modify:**
- `cmd/bot/main.go` - handleTrendEntry, add limit order tracking
- `internal/strategy/trend.go` - May need to track split entry state

---

## Summary of Action Items

| Priority | Patch | Effort | Impact |
|----------|-------|--------|--------|
| **P1** | 1. Whipsaw Defense | Low | High - Reduce false entries |
| **P1** | 2. Dynamic Chandelier | Medium | High - Protect profits |
| **P1** | 3. Correlation Guard | Medium | High - Reduce portfolio risk |
| **P2** | 4. Volatility Scalar | Medium | Medium - Adaptive sizing |
| **P3** | 5. Breakout Retest | High | Medium - Better entry price |

**Recommended Deployment:**
1. **Deploy Patches 1, 2, and 3 first** — They have the highest ROI with moderate effort
2. Deploy Patch 4 after validating first batch
3. Patch 5 is optional — only implement if exchange API supports limit orders easily
