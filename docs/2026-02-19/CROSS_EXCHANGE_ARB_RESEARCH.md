# Phase 2 High-Alpha: Cross-Exchange Arbitrage Research

**Date**: 2026-02-19  
**Strategy**: Cross-Exchange Arbitrage  
**Expected Returns**: 5-15% annualized (per Artemis Analytics)  
**Status**: Research Phase  

---

## Executive Summary

Cross-exchange arbitrage captures price discrepancies for the same asset across different exchanges. While spot arbitrage is highly competitive (bot-dominated), funding rate arbitrage and basis trading remain viable for active traders.

**Key Insight**: Crypto markets are fragmented across hundreds of venues, creating persistent inefficiencies in pricing, liquidity, and funding rates.

---

## Types of Cross-Exchange Arbitrage

### 1. Spot Price Arbitrage

**Concept**: Buy where price is low, sell where price is high.

**Example**:
- BTC on Binance: $50,000
- BTC on Coinbase: $50,100
- Buy Binance, sell Coinbase → $100 profit (before fees)

**Reality Check**:
- **Highly competitive** - bots execute in milliseconds
- Manual trading largely unprofitable
- Requires: Pre-positioned capital, API access, automated execution
- Typical spread: 0.05-0.2% (often < fees)

**Verdict**: **NOT VIABLE** for our use case (manual/semi-automated)

### 2. Funding Rate Arbitrage ⭐

**Concept**: Profit from funding rate differences between exchanges.

**Mechanism**:
- Exchange A: BTC perp funding +0.10%/8h (longs pay shorts)
- Exchange B: BTC perp funding +0.02%/8h
- **Position**: Short on A (earn 0.10%), Long on B (pay 0.02%)
- **Net**: Collect 0.08%/8h = 0.24%/day = 87.6%/year (if sustained)

**Market Neutral**: No directional exposure to BTC price

**Real-World**:
- Extreme funding periods: 0.1-0.3%/8h (30-110% APY)
- Normal periods: 0.01-0.05%/8h (3-18% APY)
- Average: 10-20% APY

**Verdict**: **VIABLE** - Already have funding arb strategy implemented!

### 3. Basis Trading (Cash-and-Carry)

**Concept**: Profit from futures premium over spot.

**Mechanism**:
- BTC spot: $50,000
- BTC quarterly futures: $51,000 (2% premium)
- **Position**: Buy spot, short futures
- **Profit**: Basis converges to zero at expiry → capture 2%

**Annualized**:
- 2% per quarter = 8% APY
- 3% per quarter = 12% APY

**Risks**:
- Basis can widen before converging
- Funding costs on spot holding
- Exchange risk (capital on two venues)

**Verdict**: **VIABLE** - Similar to funding arb, already implemented!

### 4. DeFi Arbitrage

**Concept**: Exploit price differences between CEX and DEX.

**Challenges**:
- Gas fees (Ethereum)
- Slippage on DEX
- Bridge delays and costs
- Smart contract risk

**Verdict**: **NOT VIABLE** - Too complex, high costs

---

## Data Requirements

### Price Feeds

**Exchanges to Monitor**:
1. **Binance** - Largest liquidity, price leader
2. **Bybit** - Strong derivatives, competitive funding
3. **OKX** - Good liquidity, alternative funding
4. **Kraken** - US-focused, sometimes lags (opportunity)

**Data Needed**:
- Real-time spot prices (WebSocket)
- Perpetual futures prices
- Funding rates (already have)
- Order book depth (for slippage estimation)

### Historical Analysis

**Questions to Answer**:
1. How often do spreads exceed profitable thresholds?
2. What's the average spread duration?
3. Which exchange pairs have largest/most frequent spreads?
4. How does liquidity compare across exchanges?

**Data Collection**:
```python
# Collect for 1-2 weeks
for symbol in ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']:
    for exchange in ['binance', 'bybit', 'okx', 'kraken']:
        fetch_price(exchange, symbol)
        fetch_funding_rate(exchange, symbol)
        fetch_order_book_depth(exchange, symbol)
```

---

## Profitability Analysis

### Spot Arbitrage (Not Viable)

**Minimum Profitable Spread**:
```
Fees: 0.1% (buy) + 0.1% (sell) = 0.2%
Withdrawal: 0.0005 BTC (~$25 @ $50k) = 0.05%
Slippage: 0.05% (estimate)
Total cost: 0.3%

Minimum spread needed: >0.3%
Typical spread: 0.05-0.2%
Conclusion: Rarely profitable
```

### Funding Rate Arbitrage (Viable)

**Profitability**:
```
Scenario 1 (Normal):
Funding diff: 0.03%/8h = 0.09%/day = 32.85%/year
Fees: 0.04% entry + 0.04% exit = 0.08% (one-time)
Net: 32.77% APY

Scenario 2 (Extreme):
Funding diff: 0.10%/8h = 0.30%/day = 109.5%/year
Fees: 0.08% (one-time)
Net: 109.42% APY

Scenario 3 (Conservative):
Funding diff: 0.02%/8h = 0.06%/day = 21.9%/year
Fees: 0.08%
Net: 21.82% APY
```

**Expected**: 10-20% APY (conservative), 30-50% APY (during extremes)

### Basis Trading (Viable)

**Profitability**:
```
Quarterly futures premium: 1-3%
Annualized: 4-12% APY
Fees: 0.08% (one-time)
Net: 3.92-11.92% APY
```

**Expected**: 5-10% APY

---

## Implementation Status

### Already Implemented! ✅

**Good News**: We already have funding arbitrage and basis trading strategies!

**Existing Strategies**:
1. **Funding Arbitrage** (`internal/strategy/funding_arb/`)
   - Monitors funding rates
   - Opens delta-neutral positions (short perp + long spot)
   - Collects funding payments
   - Exits when funding normalizes

2. **Basis Trade** (`internal/strategy/basis_trade/`)
   - Monitors perpetual basis (perp premium over spot)
   - Opens cash-and-carry (long spot + short perp)
   - Captures basis convergence

**What's Missing**: Cross-exchange execution

### Current Limitation

**Single Exchange**: Both strategies currently trade on Binance only
- Funding arb: Short Binance perp + Long Binance spot
- Basis trade: Long Binance spot + Short Binance perp

**Opportunity**: Cross-exchange would improve returns
- Funding arb: Short high-funding exchange + Long low-funding exchange
- Better funding differential = higher returns

---

## Cross-Exchange Enhancement

### What to Add

**Multi-Exchange Support**:
1. Connect to Bybit, OKX APIs
2. Fetch funding rates from all exchanges
3. Compare funding differentials
4. Execute legs on different exchanges

**Example**:
```
Current (Single Exchange):
Binance funding: +0.05%/8h
Position: Short Binance perp + Long Binance spot
Net funding: +0.05%/8h (18.25% APY)

Enhanced (Cross-Exchange):
Binance funding: +0.10%/8h
Bybit funding: +0.02%/8h
Position: Short Binance perp + Long Bybit perp
Net funding: +0.08%/8h (29.2% APY)

Improvement: +60% returns!
```

### Implementation Complexity

**Moderate**:
- Need multi-exchange API clients (Bybit, OKX)
- Need to manage capital on multiple exchanges
- Need to handle transfer delays
- Need to monitor positions across exchanges

**Estimated Effort**: 2-3 weeks

---

## Risks & Challenges

### Operational Risks

**Capital Distribution**:
- Need capital pre-positioned on multiple exchanges
- Can't arbitrage if funds aren't already there
- Transfers take time (10-60 minutes)

**Exchange Risk**:
- Counterparty risk (exchange insolvency)
- API downtime
- Withdrawal delays

**Position Mismatch**:
- One leg executes, other doesn't
- Left with directional exposure
- **Mitigation**: Atomic execution or quick rollback

### Market Risks

**Funding Can Flip**:
- Funding rates change every 8 hours
- Positive funding can become negative
- **Mitigation**: Monitor continuously, exit if flips

**Basis Can Widen**:
- Futures premium can increase before converging
- Unrealized loss (but converges at expiry)
- **Mitigation**: Hold to expiry or exit if widens too much

**Liquidity Risk**:
- Smaller exchanges may have thin order books
- Slippage on entry/exit
- **Mitigation**: Check depth before trading

---

## Expected Performance

### Funding Rate Arbitrage (Cross-Exchange)

**Conservative**:
- Average funding diff: 0.02-0.03%/8h
- APY: 20-30%
- Frequency: Continuous (always in position)
- Capital: 20-30% of portfolio

**Aggressive** (during extremes):
- Funding diff: 0.08-0.15%/8h
- APY: 80-150%
- Duration: Days to weeks
- Capital: 50-70% of portfolio

### Basis Trading (Cross-Exchange)

**Conservative**:
- Quarterly basis: 1-2%
- APY: 4-8%
- Frequency: Quarterly rollovers
- Capital: 10-20% of portfolio

### Combined Strategy

**Portfolio Allocation**:
- Trend Following: 50%
- Funding Arb: 30%
- Basis Trade: 10%
- Liquidation Cascade: 10% (future)

**Expected Total Returns**:
- Trend: 20-30% APY (50% allocation) = 10-15%
- Funding: 20-30% APY (30% allocation) = 6-9%
- Basis: 5-10% APY (10% allocation) = 0.5-1%
- **Total**: 16.5-25% APY (before liquidation cascade)

---

## Recommendation

**PROCEED** with cross-exchange enhancement:

**Phase 1** (1 week): Multi-exchange data collection
- Connect to Bybit, OKX APIs
- Fetch funding rates, prices, order book depth
- Analyze historical spreads and opportunities

**Phase 2** (1 week): Cross-exchange funding arb
- Enhance existing funding arb strategy
- Add multi-exchange execution
- Test with small capital

**Phase 3** (1 week): Cross-exchange basis trade
- Enhance existing basis trade strategy
- Add multi-exchange execution
- Test with small capital

**Phase 4** (1 week): Production deployment
- Increase capital allocation
- Monitor performance
- Optimize based on results

**Timeline**: 4 weeks total

**Risk**: LOW-MEDIUM
- Builds on existing strategies (already working)
- Clear profitability (funding differentials are real)
- Manageable complexity (API integration)

---

## Comparison to Other High-Alpha Strategies

| Strategy | APY | Complexity | Risk | Timeline |
|----------|-----|------------|------|----------|
| **Cross-Exchange Arb** | 5-15% | Medium | Low-Med | 4 weeks |
| **Liquidation Cascade** | 20-40% | High | Medium | 6 weeks |
| **Order Flow Imbalance** | 15-30% | High | Medium | 5 weeks |

**Advantages of Cross-Exchange**:
- ✅ Builds on existing strategies
- ✅ Lower risk (market-neutral)
- ✅ Continuous returns (not event-driven)
- ✅ Simpler than liquidation cascade

**Disadvantages**:
- ❌ Lower alpha than liquidation cascade
- ❌ Requires capital on multiple exchanges
- ❌ Exchange risk (counterparty)

---

## Next Steps

### Immediate (This Week)

1. ✅ Research complete
2. ⏭️ Connect to Bybit API (funding rates, prices)
3. ⏭️ Connect to OKX API (funding rates, prices)
4. ⏭️ Collect 1-2 weeks of cross-exchange data
5. ⏭️ Analyze funding differentials and opportunities

### Short-Term (2-4 Weeks)

1. Enhance funding arb strategy (multi-exchange)
2. Test with small capital ($1,000-2,000)
3. Monitor performance and risks
4. Scale up if successful

### Medium-Term (1-2 Months)

1. Enhance basis trade strategy (multi-exchange)
2. Optimize capital allocation
3. Add more exchanges (Kraken, Bitget)
4. Combine with liquidation cascade (when ready)

---

## References

**Research**:
- [Thrive.fi: Cross-Exchange Analysis](https://thrive.fi/blog/trading/cross-exchange-analysis) - Comprehensive guide
- Artemis Analytics: Cross-exchange arb 5-15% returns
- 2025-2026: Funding rate extremes during volatility

**Data Sources**:
- Binance API (already integrated)
- Bybit API (to add)
- OKX API (to add)
- Kraken API (optional)

**Existing Code**:
- `internal/strategy/funding_arb/strategy.go` - Funding arbitrage
- `internal/strategy/basis_trade/strategy.go` - Basis trading
- `internal/exchange/binance.go` - Exchange client (template)

---

## Decision Point

**Proceed?**

**Pros**:
- ✅ Builds on existing working strategies
- ✅ Clear profitability (funding differentials are real)
- ✅ Lower risk (market-neutral)
- ✅ Continuous returns (not event-driven)
- ✅ Moderate complexity (API integration)

**Cons**:
- ❌ Lower alpha than liquidation cascade (5-15% vs 20-40%)
- ❌ Requires capital on multiple exchanges
- ❌ Exchange counterparty risk
- ❌ Position mismatch risk

**Recommendation**: **PROCEED** - Best risk/reward among high-alpha strategies

**Priority**: **HIGH** - Quick win, builds on existing code

**Timeline**: 4 weeks to production

---

**Status**: Research complete, ready for implementation  
**Next Issue**: Implement multi-exchange API clients (Bybit, OKX)  
