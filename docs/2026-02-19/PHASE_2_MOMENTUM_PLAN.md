# Phase 2: Cross-Sectional Momentum Implementation

**Date**: 2026-02-19  
**Strategy**: Cross-Sectional Momentum for Trend Following  
**Timeline**: 3 days  
**Expected Impact**: +15-20% Sharpe improvement  

---

## Research Summary

### Key Findings (Artemis Analytics 2025)

**Momentum Factor Performance**:
- **75% annualized returns** (highest of all factors)
- **Low explanatory power** (25% of assets show significant loadings)
- **Best used as trading strategy**, not risk factor
- **3-week lookback** with volatility adjustment works best

**Implementation Approach**:
1. Rank symbols by momentum score (volatility-adjusted returns)
2. Trade only top 25-50% (strongest momentum)
3. Avoid bottom 25% (weak/negative momentum)
4. Rebalance weekly or on signal generation

**Expected Improvement**:
- Current: 27.2% win rate, 0.08 Sharpe, 1,065 trades
- Target: 32-35% win rate, 0.12-0.15 Sharpe, ~800 trades (fewer but better)

---

## Implementation Plan

### Issue Breakdown (using bd)

**Issue 1**: Research & design momentum scoring (0.5 days)
- Define momentum calculation (3-week volatility-adjusted)
- Design ranking system
- Define rebalancing frequency

**Issue 2**: Python momentum calculator (0.5 days)
- `scripts/calculate_momentum.py`
- Calculate momentum scores for all symbols
- Output: ranking CSV

**Issue 3**: Go momentum integration (1 day)
- `internal/strategy/trend_momentum.go`
- Add momentum scoring to trend strategy
- Filter signals by momentum rank

**Issue 4**: Config & testing (0.5 days)
- Add config flags
- Unit tests
- Integration tests

**Issue 5**: Backtest validation (0.5 days)
- Run backtest with momentum filter
- Compare vs baseline
- Document results

---

## Momentum Scoring Formula

### Volatility-Adjusted Momentum

```python
# 3-week (21-day) momentum with volatility adjustment
returns_21d = (price_now / price_21d_ago) - 1
volatility_21d = std(daily_returns_21d)

momentum_score = returns_21d / volatility_21d

# Rank symbols by momentum_score
# Trade only top 50% (2 out of 4 symbols)
```

### Why Volatility-Adjusted?

- Raw returns favor volatile assets (SOL often highest)
- Volatility adjustment rewards **smooth** price appreciation
- Reduces false signals from choppy markets
- Artemis research shows this outperforms raw momentum

---

## Integration Points

### 1. Trend Strategy Entry Logic

**Current**:
```go
func (ts *TrendStrategy) OnBar(symbol string, candle Candle) {
    // Check Donchian breakout
    // Check EMA confirmation
    // Check regime filters
    // Enter if all pass
}
```

**New**:
```go
func (ts *TrendStrategy) OnBar(symbol string, candle Candle) {
    // Check Donchian breakout
    // Check EMA confirmation
    // Check regime filters
    
    // NEW: Check momentum rank
    if !ts.IsTopMomentum(symbol) {
        log.Info().Str("symbol", symbol).Msg("skipping: not in top momentum")
        return
    }
    
    // Enter if all pass
}
```

### 2. Momentum Ranking

```go
// internal/strategy/trend_momentum.go
func (ts *TrendStrategy) CalculateMomentumScores() map[string]float64 {
    scores := make(map[string]float64)
    
    for _, symbol := range ts.symbols {
        candles := ts.GetCandles(symbol, 21)  // 21 days
        
        returns := (candles[20].Close / candles[0].Close) - 1
        volatility := calculateStdDev(candles)
        
        scores[symbol] = returns / volatility
    }
    
    return scores
}

func (ts *TrendStrategy) IsTopMomentum(symbol string) bool {
    scores := ts.CalculateMomentumScores()
    
    // Rank symbols
    ranked := rankByScore(scores)
    
    // Check if symbol is in top 50% (2 out of 4)
    topN := len(ranked) / 2
    for i := 0; i < topN; i++ {
        if ranked[i] == symbol {
            return true
        }
    }
    
    return false
}
```

---

## Configuration

```yaml
# config.trend.yaml
strategy:
  type: trend_following
  
  # NEW: Cross-sectional momentum filter
  momentum_filter:
    enabled: true
    lookback_days: 21          # 3 weeks
    top_pct: 0.5               # Trade top 50% (2 out of 4 symbols)
    rebalance_hours: 24        # Recalculate daily
    volatility_adjusted: true  # Use vol-adjusted momentum
```

---

## Testing Plan

### 1. Unit Tests

```go
// internal/strategy/trend_momentum_test.go
func TestCalculateMomentumScores(t *testing.T) {
    // Test momentum calculation
    // Test ranking logic
    // Test top N selection
}
```

### 2. Backtest Comparison

```bash
# Baseline (no momentum filter)
python3 scripts/backtest_trend.py

# With momentum filter
python3 scripts/backtest_trend_momentum.py
```

**Expected Results**:
- Fewer trades (~800 vs 1,065)
- Higher win rate (32-35% vs 27.2%)
- Better Sharpe (0.12-0.15 vs 0.08)
- Similar or better total return

### 3. Paper Trading

- Enable momentum filter in config
- Monitor for 24-48 hours
- Verify only top momentum symbols trade
- Check logs for momentum scores

---

## Success Metrics

| Metric | Baseline | Target | Status |
|--------|----------|--------|--------|
| Win Rate | 27.2% | 32-35% | TBD |
| Sharpe | 0.08 | 0.12-0.15 | TBD |
| Total Trades | 1,065 | ~800 | TBD |
| Max Drawdown | TBD | <15% | TBD |

---

## Risks & Mitigations

**Risk 1**: Momentum changes too frequently
- **Mitigation**: Use 24h rebalance period, not real-time

**Risk 2**: All symbols have low momentum (no trades)
- **Mitigation**: Always trade at least 1 symbol (top ranked)

**Risk 3**: Overfitting to historical data
- **Mitigation**: Use simple formula (no optimization), validate on out-of-sample

**Risk 4**: Increased correlation (all trade same symbols)
- **Mitigation**: Monitor correlation, adjust top_pct if needed

---

## Rollback Plan

If momentum filter degrades performance:

1. **Immediate**: Set `momentum_filter.enabled: false` in config
2. **Restart**: Restart trend bot
3. **Verify**: Check logs show momentum filter disabled
4. **Monitor**: Confirm trades resume on all symbols

---

## Next Steps

1. ✅ Research complete (this document)
2. ⏭️ Create beads issues (5 issues)
3. ⏭️ Implement Python momentum calculator
4. ⏭️ Implement Go integration
5. ⏭️ Backtest validation
6. ⏭️ Paper trading
7. ⏭️ Production deployment

---

**Status**: Ready to start implementation  
**Estimated Completion**: 2026-02-22 (3 days)
