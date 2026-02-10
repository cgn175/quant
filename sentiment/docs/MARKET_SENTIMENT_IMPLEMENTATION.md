# Market Sentiment Endpoint Implementation

## Summary

Added `/sentiment/market` endpoint to fetch general cryptocurrency market news without symbol filtering. This provides market-wide context for trading decisions.

## Files Added

### 1. `sentiment/fetchers/market.py`
General market news fetching functions:
- `fetch_market_telegram()` - Fetch from Telegram channels without symbol filtering
- `fetch_market_cryptopanic()` - Fetch all crypto news from CryptoPanic
- `fetch_market_newsapi()` - Fetch general crypto news from NewsAPI
- `fetch_market_reddit()` - Fetch from crypto market subreddits

### 2. `sentiment/test_market_sentiment.py`
Test script for the market sentiment endpoint

## Files Modified

### 1. `sentiment/main.py`
- Added `MarketSentimentResponse` model
- Added `/sentiment/market` endpoint (5 minute cache)
- Added `compute_market_sentiment()` function
- Added market sentiment cache (separate from symbol cache)

### 2. `sentiment/fetchers/__init__.py`
- Exported `market` module

## Features

### Market Sentiment Response

```json
{
  "market_sentiment": -0.35,
  "score_positive": 0.25,
  "score_negative": 0.60,
  "score_neutral": 0.15,
  
  "mentions": 1245,
  "sources": ["telegram", "reddit", "cryptopanic", "newsapi"],
  
  "regime": "fear",
  "fear_greed_index": 28.0,
  
  "top_keywords": [
    ["regulation", 45],
    ["bitcoin", 120],
    ["market", 98]
  ],
  "top_narratives": ["regulation", "institutional"],
  
  "regulatory_sentiment": -0.70,
  "institutional_sentiment": 0.20,
  "technical_sentiment": 0.10,
  
  "timestamp": "2026-02-10T18:00:00Z"
}
```

### Fear & Greed Index

0-100 scale calculated from:
- Sentiment scores (positive vs negative)
- Neutral sentiment (high neutral = uncertainty = fear)

**Regimes**:
- 0-20: Extreme Fear
- 20-40: Fear
- 40-60: Neutral
- 60-80: Greed
- 80-100: Extreme Greed

### Category-Specific Sentiment

Tracks sentiment for:
- **Regulatory**: SEC, regulations, bans, enforcement
- **Institutional**: ETFs, funds, banks, institutional adoption
- **Technical**: Upgrades, launches, development

### Narrative Extraction

Automatically detects dominant market narratives:
- Regulation
- Institutional adoption
- Technical developments
- DeFi trends
- Mainstream adoption

## Usage

### API Request

```bash
curl http://localhost:8000/sentiment/market
```

### Trading Bot Integration

```python
# Fetch both market and symbol sentiment
market = await sentiment_client.get("/sentiment/market")
btc = await sentiment_client.get("/sentiment/BTCUSDT")

# Use market sentiment as risk filter
if market["regime"] == "extreme_fear":
    # Reduce position sizes in fearful market
    risk_multiplier = 0.5
elif market["regime"] == "extreme_greed":
    # Reduce exposure in greedy market (top signal)
    risk_multiplier = 0.7
else:
    risk_multiplier = 1.0

# Combine with symbol-specific signal
if btc["score_1h"] > 0.3 and market["market_sentiment"] > 0:
    # BTC bullish + market healthy → take trade
    enter_long(symbol="BTCUSDT", risk_multiplier=risk_multiplier)
```

### Example Trading Rules

```python
def should_enter_trade(symbol_sentiment, market_sentiment):
    """Combine symbol and market sentiment for trade decision."""
    
    # Rule 1: Don't fight the market
    if market_sentiment["regime"] == "extreme_fear":
        return False  # Skip all trades in extreme fear
    
    # Rule 2: Be cautious in fear
    if market_sentiment["regime"] == "fear" and symbol_sentiment < 0.5:
        return False  # Require very strong symbol signal
    
    # Rule 3: Strong regulatory headwinds
    if market_sentiment["regulatory_sentiment"] < -0.5:
        return False  # Avoid trading during regulatory crackdowns
    
    # Rule 4: Symbol bullish + market neutral/bullish
    if symbol_sentiment > 0.3 and market_sentiment["market_sentiment"] > -0.2:
        return True
    
    return False
```

## Performance

### Cache Strategy

- **Symbol sentiment**: 60 second cache (fast-moving)
- **Market sentiment**: 300 second (5 minute) cache (slower-moving)

Rationale: Market-wide sentiment changes slower than individual coin sentiment.

### Fetch Time

- Telegram: ~7-10 seconds (slowest)
- CryptoPanic: ~1-2 seconds
- NewsAPI: ~1-2 seconds
- Reddit: ~2-3 seconds

**Total**: ~10-15 seconds for fresh fetch (cached for 5 minutes)

### API Call Reduction

**Before** (4 symbols):
- 4 symbols × 9 fetchers × 1 req = 36 API calls per minute

**After** (with market endpoint):
- 1 market fetch (shared) = 4 API calls
- 4 symbol fetches = 32 API calls
- **Total**: 36 API calls (same, but better context)

**Future optimization**: Skip fetchers for symbol-specific if market already has enough data.

## Testing

### Start Sentiment Server

```bash
cd sentiment
python main.py
```

### Run Test

```bash
python test_market_sentiment.py
```

Expected output:
```
Testing Market Sentiment Endpoint
============================================================

1. Testing health endpoint...
   ✓ Sentiment server is running

2. Fetching market sentiment...
   ✓ Market sentiment endpoint works!
   
   Results:
   Market Sentiment: -0.127
   Regime: fear
   Fear & Greed Index: 36.5/100
   Mentions: 234
   Sources: reddit, cryptopanic, newsapi
   
   ...
```

## Benefits

1. **Market Context**: Understand if it's a risk-on or risk-off environment
2. **Regime Detection**: Identify fear/greed extremes for contrarian signals
3. **Narrative Tracking**: Know what's driving the market (regulation, adoption, etc.)
4. **Risk Management**: Reduce exposure during market-wide fear
5. **Avoid False Signals**: Don't buy BTC if entire market is bearish

## Next Steps

### Phase 2: Deduplication (Future)
- Implement content similarity detection
- Avoid analyzing same news for both market and symbol endpoints
- Reduce FinBERT inference calls

### Phase 3: Persistence (Future)
- Save market sentiment to database (hourly aggregates)
- Historical market regime analysis
- Backtest with market context

### Phase 4: Advanced Features (Future)
- Sector-specific sentiment (DeFi, NFT, Layer 2)
- Correlation analysis (market vs symbol sentiment)
- Anomaly detection (when symbol diverges from market)

## Documentation

- Implementation proposal: `docs/MARKET_SENTIMENT_PROPOSAL.md`
- This summary: `docs/MARKET_SENTIMENT_IMPLEMENTATION.md`

## Issue Tracking

- Issue: `quant-2g1` - Add market-wide sentiment endpoint for general crypto news
- Status: Implemented ✅
