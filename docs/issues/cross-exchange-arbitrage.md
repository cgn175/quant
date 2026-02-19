# Cross-Exchange Arbitrage Enhancement

## Overview
Implement cross-exchange arbitrage enhancement for the quant trading bot to improve funding arbitrage returns from 18% APY to 29% APY by executing legs on different exchanges.

## Background
Currently, the funding arbitrage strategy only works with Binance. By comparing funding rates across multiple exchanges (Binance, Bybit, OKX) and executing the short leg on the high-funding exchange and long leg on the low-funding exchange, we can capture funding rate differentials while maintaining market neutrality.

## Implementation Status

### ✅ Completed
- [x] Created Bybit API client (`internal/exchange/bybit.go`)
  - GetFundingRate, GetPerpPrice, GetSpotPrice, GetOrderBook methods
  - Proper error handling and response parsing
- [x] Created OKX API client (`internal/exchange/okx.go`) 
  - Same interface as Bybit client
  - Symbol format conversion (BTCUSDT → BTC-USDT-SWAP)
- [x] Enhanced funding arbitrage strategy (`internal/strategy/funding_arb/strategy.go`)
  - Cross-exchange opportunity scanning
  - Multi-exchange position management
  - Updated position tracking with exchange information
- [x] Added cross-exchange manager (`internal/strategy/funding_arb/cross_exchange.go`)
  - Opportunity identification logic
  - Spread calculation and filtering
  - Momentum analysis functions
- [x] Updated configuration support
  - Multi-exchange config in `FundingArbConfig`
  - Per-exchange testnet settings
  - Minimum spread threshold configuration
- [x] Created comprehensive unit tests
  - Cross-exchange functionality tests
  - Bybit and OKX client tests
  - Mock implementations for testing
- [x] Updated config file with cross-exchange settings

### 🚧 Remaining Work
- [ ] **Order Execution Implementation**
  - Implement authenticated API calls for Bybit/OKX
  - Add API key management and request signing
  - Implement PlaceOrder methods with proper error handling
- [ ] **Position Management**
  - Cross-exchange position closing logic
  - Proper PnL calculation across exchanges
  - Risk management for cross-exchange positions
- [ ] **Integration Testing**
  - End-to-end testing with testnet environments
  - Performance testing with multiple exchanges
  - Error handling and failover scenarios
- [ ] **Monitoring & Alerting**
  - Cross-exchange metrics in Prometheus
  - Telegram alerts for cross-exchange opportunities
  - Dashboard for monitoring spread opportunities

## Expected Outcomes
- **Return Improvement**: 18% APY → 29% APY (61% increase)
- **Risk Reduction**: Market-neutral positions reduce directional risk
- **Opportunity Expansion**: Access to more funding rate opportunities across exchanges
- **Diversification**: Reduced dependency on single exchange

## Configuration Example
```yaml
strategy:
  funding_arb:
    cross_exchange: true
    min_spread_bps: 30  # 0.3% minimum spread
    exchanges: ["binance", "bybit", "okx"]
    exchange_testnet:
      binance: false
      bybit: false
      okx: false
```

## Timeline
- **Week 1-2**: Complete order execution implementation
- **Week 3**: Integration testing and risk management
- **Week 4**: Production deployment and monitoring

## Risk Considerations
- Exchange connectivity issues
- API rate limits and failures
- Cross-exchange settlement timing
- Regulatory compliance across exchanges

## Success Metrics
- [ ] Successful cross-exchange position execution
- [ ] Improved APY performance (target: 29%)
- [ ] Reduced maximum drawdown
- [ ] Zero failed cross-exchange settlements

---

**Priority**: High  
**Effort**: 3-4 weeks  
**Impact**: 61% return improvement  
**Risk**: Medium (new exchange integrations)