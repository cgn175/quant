# Trading System Strategy Status

**Last Updated:** 2026-02-19  
**Build Status:** ✅ All tests passing  
**Mode:** Paper trading only (NEVER set to `live` without explicit approval)

---

## Executive Summary

The trading system now supports **5 distinct strategies**, all running in paper mode with comprehensive risk controls. Each strategy targets different market inefficiencies:

| Strategy | Edge Type | Status | Annualized Target | Sharpe |
|----------|-----------|--------|-------------------|--------|
| Trend Following | Directional momentum | ✅ Active | 25-40% | 1.2-1.5 |
| Funding Arbitrage | Carry/term structure | ✅ Active | 15-25% | 2.0-3.0 |
| Basis Trade | Cash-and-carry | ✅ Active | 10-20% | 1.5-2.5 |
| Market Making | Spread capture | ✅ Active | 20-35% | 1.8-2.5 |
| Liquidation Cascade | Positioning squeeze | ✅ Active | Variable* | N/A |

*Liquidation targets opportunistic high-conviction setups rather than steady returns.

---

## 1. Trend Following (Plan D)

**Config:** `config.trend.yaml`  
**Prometheus:** Port 9090  
**Symbols:** BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT

### Architecture
Three-layer defense system:

```
Layer 1 (Entry) → Layer 2 (Regime) → Layer 3 (Risk)
     │                   │                  │
  Donchian           HMM/ADX          ATR stops
  EMA crossover      Regime filter    Position sizing
  Volume confirm     Momentum rank    Partial exits
  Whipsaw filter
```

### Layer 1: Entry Signals
- **Donchian breakout** (20-bar): Price breaks 20-bar high/low
- **EMA confirmation**: EMA(9) vs EMA(21) alignment
- **Trend filter**: Price vs EMA(50)
- **Volume confirmation**: > 1.5x 20-bar average
- **Whipsaw defense**: Candle color check + Bollinger width filter

### Layer 2: Regime Filters
| Filter | Status | Description |
|--------|--------|-------------|
| HMM Regime | ✅ Enabled | 3-state HMM (mean-reverting/trending/volatile) with 5-bar forward returns |
| ADX Threshold | Fallback | ADX > 20 when HMM unavailable |
| Cross-Sectional Momentum | ✅ Enabled | Top 50% momentum only (21-day Sharpe ranking) |
| Funding Filter | ✅ Enabled | Reduce size when funding extreme |

### Layer 3: Risk Management
- **Dynamic stops**: ML-predicted range with 1.2x safety factor
- **Chandelier trailing**: ATR(10) × 2.5, tightens by R-multiple
- **Partial exits**: 10% at 3R, 10% at 6R
- **Time stop**: Close if < 0.5R after 10 bars
- **Daily loss cap**: 3% max

### Key IC Analysis Result
> ⚠️ **Mean IC = -0.044** — Plan D has NEGATIVE edge. The strategy as configured predicts losses, not profits. Keep the infrastructure but understand it's the regime filters (HMM, momentum) that provide any potential edge.

---

## 2. Funding Rate Arbitrage

**Config:** `config.funding.yaml`  
**Prometheus:** Port 9092  
**Symbols:** BTCUSDT, ETHUSDT, SOLUSDT  
**Database:** `funding.db`

### Single-Exchange Strategy
- **Entry**: Funding rate > 0.01% per 8h AND > 1.2× 24h average (momentum filter)
- **Position**: SHORT perp (delta-neutral disabled in current config)
- **Exit**: Funding < 0.005% OR momentum reversal
- **Size**: $1000 per position, max 3 positions

### Cross-Exchange Arbitrage
- **Scan**: Compare rates across Binance, Bybit, OKX
- **Entry**: Spread ≥ 30 bps between exchanges
- **Position**: SHORT high-rate exchange, LONG low-rate exchange
- **Note**: Requires **pre-funded accounts** — transfer costs kill profits

### Risk Controls
- Portfolio monitor blocks overlap with Basis Trade
- Max $100k total perp-spot exposure
- Max $50k per symbol
- 3% max loss per position

### Phase 1 Features (Enabled)
- ✅ Funding momentum filter (current > avg × 1.2)
- ✅ Momentum-based exit
- ✅ Delta-neutral spot hedge (infrastructure ready)

### Phase 2 Features (Enabled)
- ✅ Cross-exchange rate scanning
- ✅ Multi-exchange client infrastructure

---

## 3. Basis Trade (Cash-and-Carry)

**Config:** `config.basis.yaml`  
**Prometheus:** Port 9093  
**Symbols:** BTCUSDT, ETHUSDT, SOLUSDT  
**Database:** `funding.db` (shared with funding arb)

### Strategy
Captures the premium of perp over spot:
- **Entry**: Annualized basis > 15%
- **Position**: LONG spot + SHORT perp (delta-neutral)
- **Exit**: Basis < 5%
- **Target**: 15% annualized from convergence

### Risk Controls
- Shares portfolio limits with funding arbitrage
- Prevents double-exposure to same symbol

---

## 4. Market Making

**Config:** `config.mm.yaml`  
**Prometheus:** Port 9091  
**Symbols:** BTCUSDT, ETHUSDT, SOLUSDT

### Core Algorithm (Avellaneda-Stoikov)
- **Spread**: Dynamic based on volatility regime
- **Inventory skew**: γ = 0.5 (moderate reversion to target)
- **Quote refresh**: 2 seconds

### Volatility Regime Filter
| Regime | ATR% | Spread Multiplier | Action |
|--------|------|-------------------|--------|
| Calm | < 2% | 1.0× | Normal quoting |
| Normal | 2-5% | 1.5× | Wider spreads |
| Elevated | 5-10% | 3.0× | Wide spreads |
| Extreme | > 10% | ∞ | Halt quoting |

### Phase 1 Features (Enabled)
- ✅ Order book imbalance (distance-weighted)
  - Analyzes top 20 levels
  - Skews quotes based on bid/ask imbalance
  - 50% skew strength (conservative)

### Phase 2 Integration (Pending)
- ⏳ Order flow delta integration (collector ready, not yet wired)

---

## 5. Liquidation Cascade

**Config:** `config.liquidation.yaml`  
**Symbols:** BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT  
**Database:** `data/liquidations.db`

### Strategy
Detects crowded positioning setups that could trigger liquidation cascades:

**Long Squeeze Setup:**
- Funding > 0.05% (extremely positive)
- OI increased > 20% in 24h
- Long/short ratio > 1.2 (more longs than shorts)
- **Trade**: Wait for first liquidations, then SHORT

**Short Squeeze Setup:**
- Funding < -0.05% (extremely negative)
- OI increased > 20% in 24h
- Long/short ratio < 0.8 (more shorts than longs)
- **Trade**: Wait for first liquidations, then LONG

### Confidence Score
```
confidence = min(|funding|/0.1, 1.0) × 0.5 +
             min(OI_change/50, 1.0) × 0.3 +
             min(extreme_ratio/0.5, 1.0) × 0.2
```

### Risk Controls
- Min confidence: 0.6
- Max 2 concurrent positions
- 2% risk per trade (higher for short-term)
- 5% daily loss cap

### Data Sources
- ✅ Real-time markPrice WebSocket streams
- ✅ OI data from database
- ✅ Funding rates via exchange API
- ⚠️ **Missing**: Coinglass/Hyblock liquidation heatmap data

### Phase 2 Status
- ✅ WebSocket infrastructure
- ✅ Positioning analysis
- ⚠️ Real liquidation cluster data needs third-party integration

---

## Cross-Strategy Risk Management

### Portfolio Monitor (`internal/risk/portfolio_monitor.go`)

Prevents correlated position buildup:

| Limit | Value | Description |
|-------|-------|-------------|
| Total Exposure | $100,000 | Across all perp-spot strategies |
| Per-Symbol | $50,000 | Max per symbol |
| Correlated Block | Enabled | Blocks funding_arb + basis_trade on same symbol |

### Symbol Overlap Matrix

|  | Trend | Funding | Basis | MM | Liquidation |
|--|:-----:|:-------:|:-----:|:--:|:-----------:|
| Trend | — | ✅ Independent | ✅ Independent | ✅ Independent | ✅ Independent |
| Funding | ✅ | — | ❌ Blocked | ✅ Independent | ✅ Independent |
| Basis | ✅ | ❌ Blocked | — | ✅ Independent | ✅ Independent |
| MM | ✅ | ✅ | ✅ | — | ✅ Independent |
| Liquidation | ✅ | ✅ | ✅ | ✅ | — |

---

## Infrastructure Status

### Data Collection
| Component | Status | Description |
|-----------|--------|-------------|
| Candle Store | ✅ Active | SQLite with 4H, 1H, 5m granularity |
| Funding Store | ✅ Active | SQLite with rate history + positions |
| OI Collector | ✅ Active | 24h rolling open interest |
| Order Flow | ✅ Active | Delta/CVD via WebSocket (not yet wired to MM) |
| Liquidation | ⚠️ Partial | Uses estimated clusters, needs real heatmap |

### ML Services (Port 9001)
| Model | Status | Use Case |
|-------|--------|----------|
| Regime Classifier | ✅ Running | Entry gating (v2 for ETH, v1 for SOL) |
| Volatility Predictor | ✅ Running | Dynamic stop sizing |
| Directional (v1) | ❌ Disabled | Overfit (Train AUC 0.96, Test 0.57) |

### Exchange Infrastructure
| Exchange | Client | Funding | Trading | Notes |
|----------|--------|---------|---------|-------|
| Binance | ✅ Full | ✅ | ✅ | Primary exchange |
| Bybit | ✅ Partial | ✅ | ⚠️ | Cross-exchange arb only |
| OKX | ✅ Partial | ✅ | ⚠️ | Cross-exchange arb only |

---

## Known Gaps & Future Work

### Critical Gaps
1. **Liquidation Heatmap Data**
   - Current: Estimated liquidation clusters (10-15× leverage assumption)
   - Needed: Real OI-by-price-level from Coinglass/Hyblock
   - Impact: Would significantly improve liquidation cascade timing

2. **Order Flow Integration**
   - Current: Collector running, data persisted to SQLite
   - Needed: Wire to MM strategy for real-time directional skew
   - Impact: Better adverse selection protection

3. **Cross-Exchange Execution**
   - Current: Infrastructure complete
   - Needed: Pre-funded accounts on Bybit/OKX
   - Impact: 10-20 bps additional alpha from rate dislocations

### Minor Improvements
- VWAP execution for large orders
- More sophisticated GARCH regime detection (currently using fixed-window)
- Survivorship bias: Dead coins added but could expand to 20+ symbols

---

## Monitoring & Alerting

### Prometheus Endpoints
| Strategy | Port | Metrics |
|----------|------|---------|
| Trend | 9090 | `trend_trades_total`, `trend_pnl`, `trend_positions` |
| MM | 9091 | `mm_spread_bps`, `mm_inventory`, `mm_orders_filled` |
| Funding | 9092 | `funding_positions`, `funding_pnl`, `funding_rates` |
| Basis | 9093 | `basis_positions`, `basis_pnl`, `basis_spread` |

### Telegram Alerts
All strategies send alerts for:
- Entry/exit signals
- Risk limit breaches
- System errors

---

## Running the System

### Start Individual Strategies
```bash
# Terminal 1: Trend Following
go run ./cmd/bot -c config.trend.yaml

# Terminal 2: Market Making
go run ./cmd/bot -c config.mm.yaml

# Terminal 3: Funding Arbitrage
go run ./cmd/bot -c config.funding.yaml

# Terminal 4: Basis Trade
go run ./cmd/bot -c config.basis.yaml

# Terminal 5: Liquidation Cascade
go run ./cmd/bot -c config.liquidation.yaml
```

### ML Server (Required for Trend)
```bash
python3 ml/server.py --models-dir ml/models
```

### Data Collectors
```bash
# WebSocket Hub (feeds all strategies)
go run ./cmd/wshub

# Order Flow (for future MM integration)
go run ./cmd/orderflow_collector

# Liquidation Data
go run ./cmd/liquidation_collector
```

---

## Performance Targets (Paper Trading)

| Metric | Target | Current Status |
|--------|--------|----------------|
| Combined Sharpe | > 1.5 | TBD |
| Max Drawdown | < 15% | TBD |
| Win Rate | > 45% | TBD |
| Daily Turnover | < 50% | TBD |

---

## Safety Checklist

Before going live, verify:
- [ ] All configs have `mode: paper`
- [ ] API keys use testnet where available
- [ ] Position limits are conservative
- [ ] Telegram alerts configured
- [ ] ML server responding on port 9001
- [ ] Prometheus scraping correctly
- [ ] Portfolio monitor logs show expected behavior

---

*This document is auto-generated from codebase review. Last updated: 2026-02-19*
