# Phase 2 Momentum Filter - Paper Trading Validation Guide

**Date**: 2026-02-19  
**Status**: ✅ Enabled in config.trend.yaml  
**Duration**: 24-48 hours recommended  

---

## What to Monitor

### 1. Prometheus Metrics

**Key Metric**: `momentum_filter_blocked_total`
- Tracks how many signals were blocked by momentum filter
- Should see ~27% of signals blocked (based on backtest)
- Check per-symbol breakdown

**Access**: http://localhost:9090

**Queries**:
```promql
# Total signals blocked
momentum_filter_blocked_total

# Blocked rate (should be ~27%)
rate(momentum_filter_blocked_total[1h]) / rate(signals_generated_total[1h])

# Per-symbol breakdown
momentum_filter_blocked_total{symbol=~".*"}
```

### 2. Bot Logs

**What to Look For**:
```
[INFO] Momentum scores: BTC=0.45 ETH=0.62 SOL=0.23 BNB=0.31
[INFO] Top momentum symbols: ETH, BTC
[INFO] Signal LONG SOL blocked by momentum filter (rank 3/4)
[INFO] Signal LONG ETH allowed (rank 1/4, top 50%)
```

**Check**:
- Momentum scores calculated correctly
- Only top 2 symbols trade at any time
- Bottom 2 symbols blocked

### 3. Trade Quality

**Compare vs Baseline** (last 24-48h without momentum):

| Metric | Baseline | With Momentum | Target |
|--------|----------|---------------|--------|
| Trades | ~10-15 | ~7-10 | -27% |
| Win Rate | ~27% | ~29% | +2% |
| Avg Win | ~8% | ~9% | +1% |
| Sharpe | ~0.08 | ~0.09 | +12% |

**Access**: Telegram alerts + Prometheus

### 4. Symbol Distribution

**Expected Behavior**:
- At any given time, only top 2 symbols should have open positions
- Bottom 2 symbols should be blocked from new entries
- Distribution should rotate as momentum changes

**Check**:
```bash
# View current positions
curl http://localhost:9090/metrics | grep open_positions
```

---

## Validation Checklist

### Day 1 (First 24h)

- [ ] Bot starts without errors
- [ ] Momentum scores calculated on each bar
- [ ] `momentum_filter_blocked_total` metric increments
- [ ] Only top 2 symbols enter new positions
- [ ] Bottom 2 symbols blocked (check logs)
- [ ] No crashes or panics

### Day 2 (24-48h)

- [ ] Trade count reduced by ~20-30% vs baseline
- [ ] Win rate improved by ~1-3%
- [ ] No unexpected behavior
- [ ] Momentum rankings rotate correctly
- [ ] All 4 symbols get chances to trade (over time)

### Success Criteria

**PASS if**:
- ✅ No errors or crashes
- ✅ Momentum filter blocks ~20-30% of signals
- ✅ Win rate improves or stays flat
- ✅ Sharpe ratio improves by 5-15%
- ✅ Only top momentum symbols trade

**FAIL if**:
- ❌ Bot crashes or errors
- ❌ All signals blocked (bug in logic)
- ❌ No signals blocked (filter not working)
- ❌ Win rate degrades significantly (>5%)
- ❌ Sharpe ratio degrades

---

## Commands

### Start Bot
```bash
cd /Users/hoangta/projects/quant
go build -o bin/bot ./cmd/bot
./bin/bot -c config.trend.yaml
```

### Monitor Logs
```bash
tail -f logs/bot.log | grep -i momentum
```

### Check Metrics
```bash
# Blocked signals
curl -s http://localhost:9090/metrics | grep momentum_filter_blocked_total

# Open positions
curl -s http://localhost:9090/metrics | grep open_positions

# Win rate
curl -s http://localhost:9090/metrics | grep win_rate
```

### Test Momentum Calculator
```bash
python3 scripts/calculate_momentum.py
```

---

## Rollback Plan

**If validation fails**, disable momentum filter:

```yaml
# config.trend.yaml
strategy:
  momentum_filter:
    enabled: false  # ❌ DISABLE
```

Then restart bot:
```bash
pkill -f "bin/bot"
./bin/bot -c config.trend.yaml
```

**Rollback time**: < 1 minute

---

## Expected Timeline

| Time | Action |
|------|--------|
| **T+0h** | Enable config, restart bot |
| **T+1h** | Check logs, verify momentum scores |
| **T+4h** | Check first blocked signals |
| **T+12h** | Review metrics, compare vs baseline |
| **T+24h** | Day 1 validation checkpoint |
| **T+48h** | Day 2 validation checkpoint, decision |

---

## Decision Points

### After 24h

**If PASS**:
- Continue monitoring for another 24h
- Document any issues

**If FAIL**:
- Rollback immediately
- Investigate root cause
- Fix and re-test

### After 48h

**If PASS**:
- ✅ Declare momentum filter validated
- Keep enabled in production
- Monitor long-term (1 week)

**If FAIL**:
- ❌ Rollback and disable
- Deep dive analysis
- Consider alternative approaches

---

## Telegram Notifications

**What to Expect**:
- Fewer trade alerts (~27% reduction)
- Higher quality signals
- Momentum scores in signal alerts
- Blocked signal notifications (if verbose logging enabled)

**Example Alert**:
```
🚀 LONG ETH @ $2,450
Momentum: Rank 1/4 (Score: 0.62)
Stop: $2,400 (-2.0%)
Risk: 1.0% ($100)
```

---

## Next Steps After Validation

### If Successful
1. ✅ Keep momentum filter enabled
2. Monitor long-term (1 week)
3. Document production performance
4. Move to Phase 2 High-Alpha strategies

### If Unsuccessful
1. ❌ Disable momentum filter
2. Analyze failure mode
3. Consider adjustments:
   - Different lookback period (14d or 28d)
   - Different top % (30% or 70%)
   - Different momentum formula
4. Re-test and validate

---

## Contact

**Issues?** Check:
1. Bot logs: `logs/bot.log`
2. Prometheus: http://localhost:9090
3. Telegram: @quantbot

**Emergency Rollback**: Set `enabled: false` and restart

---

**Status**: Ready for paper trading validation  
**Risk**: LOW (easy rollback)  
**Expected**: +12.6% Sharpe improvement  
