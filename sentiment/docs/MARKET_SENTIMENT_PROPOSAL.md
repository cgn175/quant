# Proposal: Add General Market Sentiment Fetching

## Current Situation

**Problem**: All fetchers are symbol-specific (BTC, ETH, SOL, BNB). This means:
- We miss general crypto market news (regulation, institutional adoption, market crashes)
- News like "SEC approves Bitcoin ETF" gets fetched 4 times (once per symbol)
- Market-wide sentiment (fear/greed) is not captured
- Overlapping news creates duplicate analysis

**Example**:
```
"Bitcoin ETF approved by SEC" 
  → Fetched for BTC ✓
  → Fetched for ETH ✓ (because often mentions both)
  → Fetched for SOL ✓ (crypto news mentions multiple coins)
  → Fetched for BNB ✓

Result: Same news analyzed 4 times with 4x API calls
```

## User Insight

> "General news will give us overview of status of market. But maybe these news already contain news of our symbols"

**Exactly!** General crypto market news often:
- Mentions multiple coins (Bitcoin, Ethereum, etc.)
- Affects all crypto (regulatory news, institutional adoption)
- Sets overall market sentiment (bull/bear regime)

## Proposed Solution

### Option 1: Add Market-Wide Sentiment Endpoint (Recommended)

Create a new endpoint that fetches general crypto news without symbol filtering:

```python
@app.get("/sentiment/market", response_model=MarketSentimentResponse)
async def get_market_sentiment():
    """Get overall crypto market sentiment from general news."""
    
    # Fetch general crypto news (no symbol filtering)
    posts = await fetch_general_market_news()
    
    # Analyze with FinBERT
    sentiments = analyzer.analyze([p.text for p in posts])
    
    # Return market-wide sentiment
    return {
        "market_sentiment": aggregate_score,
        "fear_greed_index": calculate_fear_greed(posts, sentiments),
        "top_narratives": extract_narratives(posts),
        "regulatory_sentiment": filter_regulatory_news(posts, sentiments),
        "institutional_sentiment": filter_institutional_news(posts, sentiments),
    }
```

**Usage**:
```python
# Trading bot uses both
market_sentiment = await sentiment_client.get("/sentiment/market")
btc_sentiment = await sentiment_client.get("/sentiment/BTCUSDT")

# Decision:
if market_sentiment < -0.5:
    # Market-wide fear → reduce all position sizes
    reduce_risk_across_board()
elif btc_sentiment > 0.3 and market_sentiment > 0:
    # BTC bullish + market healthy → take BTC long
    enter_btc_long()
```

### Option 2: Enhance Symbol Fetching with Market Context (Hybrid)

Each symbol fetch includes market-wide news:

```python
@app.get("/sentiment/{symbol}")
async def get_sentiment(symbol: str):
    # Fetch symbol-specific news
    symbol_posts = await fetch_symbol_news(symbol)
    
    # Also fetch general market news (cached globally)
    market_posts = await fetch_market_news()  # Cached for all symbols
    
    # Combine and weight appropriately
    all_posts = symbol_posts + market_posts
    
    return {
        "symbol_sentiment": analyze(symbol_posts),
        "market_sentiment": analyze(market_posts),
        "combined_sentiment": weighted_average(symbol_sentiment, market_sentiment),
    }
```

## Implementation Details

### General Market News Sources

#### 1. Telegram Channels (Market-Wide)
```python
MARKET_CHANNELS = [
    "cointelegraph",           # General crypto news
    "theblock__",             # Industry news
    "cryptonews",             # Market updates
    "CryptoQuant",            # On-chain analysis
    "glassnode",              # Market analytics
]

async def fetch_market_telegram():
    """Fetch all Telegram posts without symbol filtering."""
    all_posts = []
    for channel in MARKET_CHANNELS:
        messages = await client.get_messages(channel, limit=50)
        # No keyword filtering - get all messages
        all_posts.extend(messages)
    return all_posts
```

#### 2. CryptoPanic (Market-Wide)
```python
# Instead of filtering by currency:
params = {
    "auth_token": api_key,
    "filter": "news",
    # No "currencies" parameter → returns all crypto news
}
```

#### 3. NewsAPI (General Crypto)
```python
keywords = [
    "cryptocurrency market",
    "crypto regulation",
    "bitcoin institutional",
    "crypto adoption",
    "blockchain news"
]
```

#### 4. Reddit (Crypto Market Subreddits)
```python
MARKET_SUBREDDITS = [
    "CryptoCurrency",    # General discussion
    "CryptoMarkets",     # Trading/market analysis
    "Bitcoin",           # Largest community
]
# Fetch top posts without filtering for specific coins
```

### Deduplication Strategy

**Problem**: General news often overlaps with symbol-specific news.

**Solution**: Use content-based deduplication

```python
from difflib import SequenceMatcher

def is_duplicate(text1: str, text2: str, threshold: float = 0.85) -> bool:
    """Check if two texts are similar enough to be duplicates."""
    similarity = SequenceMatcher(None, text1, text2).ratio()
    return similarity >= threshold

# When combining symbol and market news:
def deduplicate_posts(posts: list[Post]) -> list[Post]:
    unique = []
    seen_texts = []
    
    for post in posts:
        # Check against all previously seen texts
        is_dup = any(is_duplicate(post.text, seen) for seen in seen_texts)
        
        if not is_dup:
            unique.append(post)
            seen_texts.append(post.text)
    
    return unique
```

## Benefits

### 1. Market Regime Detection
```python
if market_sentiment < -0.5 and market_volatility > 2.0:
    # Market-wide panic → reduce leverage
    risk_multiplier = 0.5
```

### 2. Avoid False Signals
```python
if btc_sentiment > 0.5 but market_sentiment < -0.3:
    # BTC positive but market negative → wait
    skip_trade()
```

### 3. Narrative Tracking
```python
top_narratives = extract_narratives(market_posts)
# ["Bitcoin ETF approval", "Ethereum upgrade", "DeFi TVL growth"]

# Adjust strategy based on dominant narrative
if "regulation" in top_narratives:
    reduce_risk()
```

### 4. Reduce API Calls
```python
# Before: 4 symbols × 7 fetchers × 1 req/fetcher = 28 API calls
# After: 1 market fetch (shared) + 4 symbol fetches = ~15 API calls
```

## Recommended Implementation Plan

### Phase 1: Add Market Endpoint (Week 1)
1. Create `/sentiment/market` endpoint
2. Fetch general crypto news (no filtering)
3. Return market-wide sentiment scores
4. Add caching (5 min TTL for market data)

### Phase 2: Deduplication (Week 2)
1. Implement content similarity detection
2. Deduplicate market vs symbol news
3. Add tests for edge cases

### Phase 3: Integration with Trading Bot (Week 3)
1. Bot polls both `/sentiment/market` and `/sentiment/{symbol}`
2. Use market sentiment as risk filter
3. Adjust position sizing based on market regime

### Phase 4: Advanced Features (Future)
1. Fear & Greed Index calculation
2. Narrative extraction (NER + topic modeling)
3. Sector-specific sentiment (DeFi, NFT, Layer 2)
4. Regulatory vs technical news classification

## Example API Response

```json
{
  "market_sentiment": -0.35,
  "fear_greed_index": 28,
  "regime": "fear",
  "volatility": "high",
  "top_narratives": [
    "SEC enforcement action",
    "Binance regulatory scrutiny",
    "Bitcoin ETF optimism"
  ],
  "sentiment_by_category": {
    "regulatory": -0.7,
    "institutional": 0.2,
    "technical": 0.1,
    "adoption": 0.3
  },
  "mentions": 1245,
  "sources": [
    "telegram",
    "reddit",
    "cryptopanic",
    "newsapi"
  ],
  "timestamp": "2026-02-10T18:00:00Z"
}
```

## Questions to Consider

1. **Should market sentiment override symbol sentiment?**
   - Suggestion: Use as filter/multiplier, not replacement

2. **How to weight general vs specific news?**
   - Suggestion: 70% symbol-specific, 30% market-wide

3. **Cache duration for market data?**
   - Suggestion: 5 minutes (less volatile than symbol-specific)

4. **Should we backfill historical market sentiment?**
   - Suggestion: Yes, useful for backtesting

## Conclusion

**User is correct**: General market news provides important context that:
- Affects all trading decisions (risk-on vs risk-off)
- Often overlaps with symbol-specific news (reducing duplication)
- Captures systemic events (regulation, institutional adoption)

**Recommendation**: Implement Option 1 (separate market endpoint) first, then add deduplication in Phase 2.

This gives trading bot both:
- **Market context** (overall sentiment, regime, narratives)
- **Symbol-specific signals** (BTC bullish, ETH bearish, etc.)

Would you like me to implement this? I can start with Phase 1 (market endpoint).
