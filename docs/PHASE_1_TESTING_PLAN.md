# Phase 1 Testing & Validation Plan

## Objective
Validate each Phase 1 enhancement individually before combining them, ensuring:
1. Each feature works as expected
2. No unexpected interactions
3. Parameters are properly tuned
4. Baseline performance established

---

## Test 1: Order Book Imbalance (Market Making)

### Setup
- Enable `imbalance_enabled: true` in `config.mm.yaml`
- Set `imbalance_depth: 20`, `imbalance_skew_factor: 0.5`
- Run paper trading for 24 hours

### Metrics to Track
- PnL improvement vs baseline (no imbalance)
- Fill rate changes
- Adverse selection rate
- Imbalance correlation with price moves

### Success Criteria
- PnL improvement: +15-25% (target: +20-30%)
- No increase in adverse selection
- Imbalance metric shows reasonable values (-1 to +1)

### Backtest Command
```bash
# TODO: Create market making backtest script
python3 scripts/backtest_mm.py --config config.mm.yaml --days 30
```

---

## Test 2: Funding Rate Momentum (Funding Arb)

### Setup
- Enable `use_momentum: true` in `config.funding.yaml`
- Set `momentum_multiplier: 1.2`
- Set `momentum_exit_enable: true`

### Metrics to Track
- Entry count: static vs momentum
- Win rate improvement
- Average holding time
- Annualized returns

### Success Criteria
- Returns improvement: +25-35% (target: +30-40%)
- Fewer false entries (momentum filter working)
- Win rate: >60%

### Backtest Command
```bash
# Use existing funding arb backtest
python3 scripts/backtest_funding.py --momentum --days 90
```

---

## Test 3: HMM Regime Detection (Trend Following)

### Setup
1. Train HMM models:
   ```bash
   python3 ml/regime/train_regime_hmm.py
   ```

2. Start ML server with HMM models:
   ```bash
   python3 ml/server.py --models-dir ml/models
   ```

3. Enable in `config.trend.yaml`:
   ```yaml
   regime_filter:
     enabled: true
     use_hmm: true
     hmm_trending_prob: 0.6
   ```

### Metrics to Track
- Sharpe ratio: HMM vs ADX vs RandomForest
- False breakout rate
- Win rate
- Average trade duration

### Success Criteria
- Sharpe improvement: +8-12% (target: +10-15%)
- False breakouts reduced: -5-10%
- Win rate: >45%

### Backtest Command
```bash
# Use existing trend backtest
go run ./cmd/backtest -c config.trend.yaml --start 2024-01-01 --end 2026-02-01
```

---

## Test 4: GARCH Volatility (Dynamic Stops)

### Setup
1. Train GARCH models:
   ```bash
   python3 ml/volatility/train_garch.py
   ```

2. **Note**: Full integration pending (foundation only)
   - For now, test existing volatility predictor
   - GARCH integration is Phase 1.5 work

### Metrics to Track
- Stop-out rate
- Average R-multiple at exit
- Win rate with dynamic stops

### Success Criteria
- Stop-out rate: <15%
- Average R-multiple: >2.0
- Dynamic stops adapt to volatility

### Backtest Command
```bash
# Test with existing dynamic stops
go run ./cmd/backtest -c config.trend.yaml --dynamic-stops --start 2024-01-01
```

---

## Combined Testing (Phase 1 Full)

### Setup
Enable all Phase 1 features:
- Market making: imbalance detection ON
- Funding arb: momentum strategy ON
- Trend following: HMM regime ON
- Dynamic stops: existing volatility predictor ON

### Metrics to Track
- Overall portfolio Sharpe ratio
- Max drawdown
- Win rate across all strategies
- Daily PnL consistency

### Success Criteria
- Portfolio Sharpe: >1.5
- Max drawdown: <15%
- Win rate: >50%
- Positive PnL on 70%+ of days

---

## Testing Schedule

### Day 1 (Today)
- [x] Create testing plan
- [ ] Train HMM models for all symbols
- [ ] Train GARCH models for all symbols
- [ ] Run trend following backtest (baseline vs HMM)

### Day 2
- [ ] Run funding arb backtest (static vs momentum)
- [ ] Analyze results and tune parameters
- [ ] Start paper trading (trend + funding)

### Day 3-4
- [ ] Monitor paper trading performance
- [ ] Create market making backtest script
- [ ] Run market making backtest (baseline vs imbalance)

### Day 5-7
- [ ] Combined paper trading (all strategies)
- [ ] Performance analysis and reporting
- [ ] Parameter tuning based on results

### Week 2
- [ ] Extended paper trading validation
- [ ] Final performance report
- [ ] Decision: proceed to Phase 2 or iterate

---

## Risk Management During Testing

1. **Paper Trading Only**: No live funds at risk
2. **Position Sizing**: Start with small sizes (10% of normal)
3. **Circuit Breakers**: Keep existing safety limits
4. **Monitoring**: Check logs every 4 hours
5. **Rollback Plan**: Disable features if performance degrades

---

## Success Metrics Summary

| Feature | Metric | Target | Minimum Acceptable |
|---------|--------|--------|-------------------|
| Order Book Imbalance | PnL Improvement | +20-30% | +15% |
| Funding Momentum | Returns Improvement | +30-40% | +25% |
| HMM Regime | Sharpe Improvement | +10-15% | +8% |
| HMM Regime | False Breakouts | -5-10% | -3% |
| Combined | Portfolio Sharpe | >1.5 | >1.2 |
| Combined | Max Drawdown | <15% | <20% |

---

## Next Steps

1. **Immediate**: Train ML models (HMM + GARCH)
2. **Today**: Run trend following backtest with HMM
3. **Tomorrow**: Run funding arb backtest with momentum
4. **This Week**: Start paper trading with monitoring

---

**Status**: Ready to begin testing
**Estimated Duration**: 7-14 days for full validation
**Risk Level**: Low (paper trading only)
