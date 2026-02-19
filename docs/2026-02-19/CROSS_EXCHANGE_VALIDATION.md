# Cross-Exchange Arbitrage Validation Guide

**Date**: 2026-02-19  
**Status**: Authentication complete, ready for validation  

---

## Validation Phases

### Phase 1: Read-Only Validation (✅ DO THIS FIRST)

**No API keys needed. Safe to run anytime.**

```bash
# Run validation script
python3 scripts/validate_cross_exchange.py
```

**What it checks**:
- ✅ Can fetch funding rates from all 3 exchanges
- ✅ Can fetch perp prices from all 3 exchanges
- ✅ Calculates funding rate spreads
- ✅ Calculates price spreads
- ✅ Identifies arbitrage opportunities
- ✅ Estimates APY potential

**Expected output**:
```
✅ Binance: Funding=0.000002 (0.0002%), Price=$65,881.70
✅ Bybit:   Funding=-0.000005 (-0.0005%), Price=$65,896.80
✅ OKX:     Funding=0.000026 (0.0026%), Price=$65,905.70

📊 Funding Rate Spread:
   Lowest:  Bybit = -0.000005 (-0.0005%)
   Highest: OKX = 0.000026 (0.0026%)
   Spread:  0.000031 (0.0031%)
   APY:     3.36%
```

**Success criteria**:
- All 3 exchanges return data
- Spreads are calculated correctly
- APY estimates make sense

---

### Phase 2: Testnet Order Execution (⏳ NEXT STEP)

**Requires testnet API keys. Tests order placement without real money.**

#### 2.1 Get Testnet Credentials

**Bybit Testnet**:
1. Go to https://testnet.bybit.com
2. Sign up / log in
3. API Management → Create API Key
4. Save: API Key, API Secret
5. Get testnet USDT from faucet

**OKX Testnet**:
1. Go to https://www.okx.com/demo-trading
2. Sign up / log in
3. API → Create API Key
4. Save: API Key, API Secret, Passphrase

#### 2.2 Configure Testnet

Edit `config.funding.yaml`:

```yaml
exchange:
  name: binance
  testnet: true  # Use Binance testnet too
  
  # Bybit testnet
  bybit_api_key: "YOUR_BYBIT_TESTNET_KEY"
  bybit_api_secret: "YOUR_BYBIT_TESTNET_SECRET"
  bybit_testnet: true
  
  # OKX testnet (demo trading)
  okx_api_key: "YOUR_OKX_DEMO_KEY"
  okx_api_secret: "YOUR_OKX_DEMO_SECRET"
  okx_passphrase: "YOUR_OKX_DEMO_PASSPHRASE"

strategy:
  type: funding_arb
  funding_arb:
    cross_exchange: true
    exchanges:
      - binance
      - bybit
      - okx
    min_funding_rate: 0.0001  # 0.01% per 8h
    position_size_usd: 100    # Small test size
```

#### 2.3 Run Testnet Bot

```bash
# Build
go build -o bin/bot ./cmd/bot

# Run with testnet config
./bin/bot -c config.funding.yaml
```

**What to watch for**:
```
✅ "added authenticated bybit client"
✅ "added authenticated okx client"
✅ "scanning cross-exchange opportunities"
✅ "cross-exchange opportunity found"
✅ "Order placed" (if opportunity exists)
```

**Success criteria**:
- Bot starts without errors
- Authenticated clients initialized
- Can scan opportunities across exchanges
- Can place orders on testnet (if opportunity exists)
- Orders appear in testnet exchange UI

---

### Phase 3: Paper Trading Validation (⏳ AFTER TESTNET)

**Uses real market data but simulated execution.**

```yaml
mode: paper  # Keep in paper mode

exchange:
  name: binance
  testnet: false  # Use real market data
  
  # Leave credentials empty for read-only
  # bybit_api_key: ""
  # bybit_api_secret: ""

strategy:
  funding_arb:
    cross_exchange: true
    exchanges:
      - binance
      - bybit
      - okx
```

**Run for 24-48 hours**:
```bash
./bin/bot -c config.funding.yaml
```

**Monitor**:
- Opportunity detection frequency
- Simulated PnL
- Funding payments collected
- Exit timing

**Success criteria**:
- Finds opportunities regularly
- Simulated trades are profitable
- No errors or crashes
- Telegram alerts working

---

### Phase 4: Live Trading (⚠️ ONLY AFTER FULL VALIDATION)

**Real money. Start small.**

#### 4.1 Get Production API Keys

**Bybit Mainnet**:
1. Go to https://www.bybit.com
2. API Management → Create API Key
3. Permissions: Trade only (no withdrawal)
4. IP whitelist: Your server IP
5. Save credentials securely

**OKX Mainnet**:
1. Go to https://www.okx.com
2. API → Create API Key
3. Permissions: Trade only
4. IP whitelist: Your server IP
5. Save credentials securely

#### 4.2 Configure Production

```yaml
mode: live  # ⚠️ REAL MONEY

exchange:
  name: binance
  testnet: false
  api_key: "YOUR_BINANCE_KEY"
  api_secret: "YOUR_BINANCE_SECRET"
  
  bybit_api_key: "YOUR_BYBIT_MAINNET_KEY"
  bybit_api_secret: "YOUR_BYBIT_MAINNET_SECRET"
  bybit_testnet: false
  
  okx_api_key: "YOUR_OKX_MAINNET_KEY"
  okx_api_secret: "YOUR_OKX_MAINNET_SECRET"
  okx_passphrase: "YOUR_OKX_MAINNET_PASSPHRASE"

strategy:
  funding_arb:
    cross_exchange: true
    exchanges:
      - binance
      - bybit
      - okx
    position_size_usd: 500  # Start small
    max_positions: 2        # Limit exposure
```

#### 4.3 Start Live (Carefully)

```bash
# Double-check config
cat config.funding.yaml | grep mode
# Should show: mode: live

# Start bot
./bin/bot -c config.funding.yaml

# Monitor closely for first 24h
tail -f logs/bot.log
```

**Monitor**:
- Real order execution
- Actual PnL
- Funding payments
- Exchange balances
- Telegram alerts

---

## Quick Validation Checklist

### Before Testnet
- [ ] Read-only validation script runs successfully
- [ ] All 3 exchanges return data
- [ ] Opportunity detection logic works
- [ ] APY calculations are correct

### Before Paper Trading
- [ ] Testnet orders execute successfully
- [ ] Orders appear in testnet exchange UI
- [ ] No authentication errors
- [ ] Logs show proper flow

### Before Live Trading
- [ ] Paper trading runs 24-48h without errors
- [ ] Simulated PnL is positive
- [ ] Opportunity frequency is acceptable
- [ ] All edge cases handled
- [ ] API keys have correct permissions
- [ ] IP whitelist configured
- [ ] Start with small position sizes

---

## Troubleshooting

### "authentication not configured"
- Check API keys are in config
- Verify keys are not empty strings
- Check YAML indentation

### "bybit order failed: status=403"
- API key invalid or expired
- IP not whitelisted
- Insufficient permissions
- Check testnet vs mainnet mismatch

### "okx order error: Invalid sign"
- Check passphrase is correct
- Verify timestamp format
- Check API secret encoding

### No opportunities found
- Normal - spreads are often small
- Try lowering `min_funding_rate` threshold
- Check during high volatility periods
- Verify all exchanges are returning data

---

## Expected Performance

### Realistic Expectations

**Opportunity Frequency**:
- High volatility: 2-5 opportunities per day
- Normal market: 0-2 opportunities per day
- Low volatility: May go days without opportunities

**APY Range**:
- Conservative: 10-15% APY
- Average: 15-25% APY
- Aggressive (high leverage): 25-35% APY

**Position Duration**:
- Short-term: 8-24 hours (1-3 funding periods)
- Medium-term: 1-3 days
- Long-term: 3-7 days (rare)

---

## Safety Checklist

- [ ] Never commit API keys to git
- [ ] Use environment variables or secure config
- [ ] Enable IP whitelist on all exchanges
- [ ] Disable withdrawal permissions
- [ ] Start with small position sizes
- [ ] Set daily loss limits
- [ ] Monitor first 24h closely
- [ ] Have kill switch ready (`/stop` command)
- [ ] Keep emergency contact for exchanges
- [ ] Test on testnet first, always

---

## Next Steps

1. **Now**: Run `python3 scripts/validate_cross_exchange.py`
2. **Today**: Get testnet credentials
3. **Tomorrow**: Test on testnet
4. **This week**: Paper trade for 24-48h
5. **Next week**: Consider live trading (if all validations pass)

---

## Support

**Issues**: Create issue with `bd create`  
**Logs**: Check `logs/bot.log`  
**Telegram**: Alerts sent to configured chat  
**Monitoring**: Prometheus metrics on `:2112/metrics`  

---

**Status**: Ready for Phase 1 validation ✅  
**Risk Level**: Phase 1 = ZERO (read-only)  
**Time to Live**: 3-7 days (if all phases pass)
