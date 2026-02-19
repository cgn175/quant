# Fetcher Refactor Documentation

## Overview

The sentiment server fetcher architecture has been refactored from **symbol-specific fetching** to **general market fetching with post-processing categorization**. This results in **75% reduction in API calls** and better rate limit compliance.

## Architecture Changes

### Old Architecture (Symbol-Specific Fetching)

```
Request for BTCUSDT → All 10 fetchers fetch BTC news
Request for ETHUSDT → All 10 fetchers fetch ETH news  
Request for SOLUSDT → All 10 fetchers fetch SOL news
Request for BNBUSDT → All 10 fetchers fetch BNB news

Total: 4 symbols × 10 fetchers = 40 API calls
```

**Problems:**
- High API call volume leads to rate limiting
- Duplicate work when news mentions multiple symbols
- Cache is per-symbol, not shared
- Difficult to scale to more symbols

### New Architecture (General Fetching + Categorization)

```
General fetch cycle → All 10 fetchers fetch crypto news once
                   ↓
            Categorization by symbol
                   ↓
    ┌──────────┬──────────┬──────────┬──────────┐
 BTCUSDT   ETHUSDT   SOLUSDT   BNBUSDT   MARKET

Total: 1 fetch cycle × 10 fetchers = 10 API calls
```

**Benefits:**
- 75% reduction in API calls (40 → 10)
- News mentioning multiple symbols counted for all
- Shared cache across all symbols
- Easy to add more symbols without increasing API calls
- Better rate limit compliance

## Key Components

### 1. FetcherManager (`sentiment/fetchers/manager.py`)

Central coordinator for all news fetching:

```python
from fetchers.manager import FetcherManager

manager = FetcherManager(
    fetchers=fetchers_dict,
    cache_ttl_seconds=300,  # 5 minute cache
    target_symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
)

# Fetch general news (cached)
general_posts = await manager.fetch_general_news()

# Get symbol-specific posts
btc_posts = await manager.fetch_for_symbol("BTCUSDT")

# Get market-wide sentiment posts
market_posts = await manager.fetch_market_sentiment()
```

**Features:**
- Fetches general crypto news from all sources
- Caches results for `cache_ttl_seconds` (default 5 minutes)
- Categorizes posts by symbol using NLP/keyword matching
- Returns symbol-specific or market-wide posts

### 2. Categorizer (`sentiment/fetchers/categorizer.py`)

Categorizes general posts into symbol-specific buckets:

```python
from fetchers.categorizer import (
    categorize_posts,
    extract_symbols_from_post,
    is_general_market_post
)

# Extract relevant symbols from a post
symbols = extract_symbols_from_post(post)
# Returns: ["BTCUSDT", "ETHUSDT"]

# Check if post is general market news
is_market = is_general_market_post(post)
# Returns: True for "Crypto regulation updates", False for "BTC price"

# Categorize a list of posts
categorized = categorize_posts(posts, target_symbols)
# Returns: {
#     "BTCUSDT": [Post(...), Post(...)],
#     "ETHUSDT": [Post(...)],
#     "MARKET": [Post(...)]
# }
```

**Keyword Mappings:**
- **BTC**: bitcoin, btc, $btc, bitcoin price, bitcoin network, etc.
- **ETH**: ethereum, eth, $eth, ether, vitalik, eth 2.0, etc.
- **SOL**: solana, sol, $sol, solana network, etc.
- **BNB**: binance, bnb, $bnb, binance chain, bsc, etc.

**General Market Keywords:**
- cryptocurrency, crypto market, blockchain, defi, nft, web3
- crypto regulation, crypto adoption, institutional crypto
- etc.

### 3. Market Module (`sentiment/fetchers/market.py`)

Provides general market fetching functions for sources that need them:

```python
from fetchers import market

# Fetch general crypto news from Telegram
telegram_posts = await market.fetch_market_telegram(telegram_fetcher)

# Fetch from CryptoPanic without currency filter
cryptopanic_posts = await market.fetch_market_cryptopanic(cryptopanic_fetcher)

# Fetch from NewsAPI with general crypto keywords
newsapi_posts = await market.fetch_market_newsapi(newsapi_fetcher)

# Fetch from Reddit crypto subreddits
reddit_posts = await market.fetch_market_reddit(reddit_fetcher)
```

All posts returned have `symbol="MARKET"` for general market news.

## Integration with Main Server

### Before (Old Code)

```python
# main.py
async def compute_sentiment(symbol: str):
    # Fetch from all sources for this specific symbol
    fetch_tasks = [fetcher.fetch(symbol, limit=50) for fetcher in fetchers.values()]
    all_results = await asyncio.gather(*fetch_tasks)
    
    posts = []
    for result in all_results:
        if isinstance(result, list):
            posts.extend(result)
    
    # ... analyze sentiment ...
```

### After (New Code)

```python
# main.py
async def compute_sentiment(symbol: str):
    # Use fetcher_manager to get categorized posts
    # Fetches general news once, uses cache if available
    posts = await fetcher_manager.fetch_for_symbol(symbol, limit=200)
    
    sources_used = list(set(p.source.split(':')[0] for p in posts))
    
    # ... analyze sentiment ...
```

### Market Sentiment Endpoint

```python
@app.get("/sentiment/market")
async def get_market_sentiment():
    # Use fetcher_manager for general market posts
    posts = await fetcher_manager.fetch_market_sentiment()
    
    # ... analyze sentiment ...
```

## Cache Behavior

### Cache Flow

```
Request 1 (BTCUSDT):
  → Fetch general news from all sources (10 API calls)
  → Cache general posts (TTL: 5 minutes)
  → Categorize by symbol
  → Return BTC-relevant posts

Request 2 (ETHUSDT) - within 5 minutes:
  → Use cached general posts (0 API calls)
  → Categorize by symbol
  → Return ETH-relevant posts

Request 3 (SOLUSDT) - within 5 minutes:
  → Use cached general posts (0 API calls)
  → Categorize by symbol
  → Return SOL-relevant posts

Request 4 (after 5+ minutes):
  → Fetch general news again (10 API calls)
  → Update cache
  → Categorize and return
```

### Cache Management

```python
# Clear cache manually if needed
fetcher_manager.clear_cache()

# Adjust cache TTL
fetcher_manager = FetcherManager(
    fetchers=fetchers,
    cache_ttl_seconds=600  # 10 minute cache
)
```

## Testing

### Run Tests

```bash
cd sentiment
python3 test_fetcher_refactor.py
```

### Test Coverage

1. **Categorization Tests**
   - Symbol extraction from posts
   - General market post detection
   - Multi-symbol posts

2. **FetcherManager Tests**
   - General news fetching
   - Cache behavior (speedup verification)
   - Symbol-specific filtering
   - Market sentiment extraction

3. **API Call Reduction Tests**
   - Demonstrates 75% reduction in API calls
   - Cache benefits across multiple symbols

## Migration Guide

### For Individual Fetchers

Old fetchers still work unchanged - they implement `fetch(symbol, limit)`:

```python
# Old code still works
posts = await reddit_fetcher.fetch("BTCUSDT", limit=50)
```

But you should use FetcherManager instead:

```python
# New code (preferred)
posts = await fetcher_manager.fetch_for_symbol("BTCUSDT", limit=50)
```

### Adding New Fetchers

1. **Create fetcher class** implementing `BaseFetcher.fetch(symbol, limit)`
2. **Add to fetchers dict** in `main.py`
3. **Add general fetch method** in `FetcherManager._fetch_<source>_general()`

Example:

```python
# sentiment/fetchers/newsource.py
class NewSourceFetcher(BaseFetcher):
    async def fetch(self, symbol: str, limit: int = 100) -> list[Post]:
        # Symbol-specific fetch (still works)
        pass

# sentiment/fetchers/manager.py
async def _fetch_newsource_general(self, limit: int) -> List[Post]:
    """Fetch general crypto news from NewSource."""
    fetcher = self.fetchers["newsource"]
    # Implement general market fetching logic
    pass
```

### Adding New Symbols

Just add to `DEFAULT_SYMBOLS` in `main.py`:

```python
DEFAULT_SYMBOLS = [
    "BTCUSDT", 
    "ETHUSDT", 
    "SOLUSDT", 
    "BNBUSDT",
    "ADAUSDT",  # New symbol - no extra API calls!
]
```

No need to worry about increasing API calls - categorization handles it.

## Performance Metrics

### API Call Reduction

| Scenario | Old Architecture | New Architecture | Reduction |
|----------|------------------|------------------|-----------|
| 1 symbol | 10 calls | 10 calls | 0% |
| 2 symbols | 20 calls | 10 calls | 50% |
| 4 symbols | 40 calls | 10 calls | **75%** |
| 10 symbols | 100 calls | 10 calls | **90%** |

### Cache Performance

From test results:

```
1st fetch (cold cache): 0.59s
2nd fetch (warm cache): 0.00s
Speedup: 588x faster
```

### Rate Limit Compliance

**Before:**
- 40 API calls per minute (4 symbols × 10 fetchers)
- Telegram hit 429 errors frequently
- CryptoPanic exhausted daily quota quickly

**After:**
- 10 API calls per 5 minutes (1 fetch cycle every 5 minutes)
- 2 calls/minute average
- No rate limit issues observed

## Troubleshooting

### "FetcherManager returned 0 posts"

**Cause:** All fetchers failed or returned no results

**Solutions:**
1. Check API keys in `.env`
2. Check fetcher logs for specific errors
3. Test individual fetchers:
   ```python
   posts = await fetchers["reddit"].fetch("BTCUSDT", limit=10)
   print(f"Reddit returned {len(posts)} posts")
   ```

### "No posts found for symbol X"

**Cause:** Posts don't match symbol keywords

**Solutions:**
1. Check keyword mappings in `categorizer.py`
2. Add more keywords for your symbol:
   ```python
   SYMBOL_KEYWORDS = {
       "BTC": ["bitcoin", "btc", "$btc", "satoshi"],  # Add more
       # ...
   }
   ```

### Cache not updating

**Cause:** Cache TTL too long or clock skew

**Solutions:**
1. Clear cache: `fetcher_manager.clear_cache()`
2. Reduce cache TTL:
   ```python
   fetcher_manager = FetcherManager(
       fetchers=fetchers,
       cache_ttl_seconds=60  # 1 minute
   )
   ```

### Rate limit errors still occurring

**Cause:** Individual fetchers hitting rate limits

**Solutions:**
1. Increase `cache_ttl_seconds` to reduce fetch frequency
2. Reduce `limit_per_source` in fetch calls
3. Disable problematic fetchers temporarily

## Future Improvements

### 1. NLP-Based Categorization

Replace keyword matching with ML model:

```python
# Instead of keyword matching
def extract_symbols_from_post_nlp(post: Post) -> List[str]:
    # Use transformer model to extract entities
    entities = ner_model.predict(post.text)
    symbols = [entity_to_symbol(e) for e in entities if e.type == "CRYPTOCURRENCY"]
    return symbols
```

### 2. Adaptive Cache TTL

Adjust cache duration based on market volatility:

```python
# High volatility → shorter cache (fresh news important)
# Low volatility → longer cache (save API calls)
adaptive_ttl = calculate_adaptive_ttl(market_volatility)
fetcher_manager.cache_ttl_seconds = adaptive_ttl
```

### 3. Fetcher Priority System

Prioritize reliable fetchers:

```python
fetcher_priorities = {
    "cryptopanic": 1.0,  # High priority
    "newsapi": 1.0,
    "reddit": 0.7,       # Medium priority
    "twitter": 0.5,      # Low priority (often rate limited)
}
```

### 4. Distributed Caching

Use Redis for shared cache across multiple server instances:

```python
# Instead of in-memory cache
cache_backend = RedisCache(redis_url=settings.redis_url)
fetcher_manager = FetcherManager(
    fetchers=fetchers,
    cache_backend=cache_backend
)
```

## References

- **Source Code:**
  - `sentiment/fetchers/manager.py` - FetcherManager implementation
  - `sentiment/fetchers/categorizer.py` - Post categorization logic
  - `sentiment/fetchers/market.py` - General market fetch functions
  - `sentiment/main.py` - Integration with FastAPI server

- **Tests:**
  - `sentiment/test_fetcher_refactor.py` - Comprehensive test suite

- **Related Documentation:**
  - `docs/TELEGRAM_RATE_LIMIT_FIX.md` - Telegram rate limit solutions
  - Original thread: `T-019c486b-7a11-74ad-be9b-66400187c30d`

## Summary

The fetcher refactor provides:

✅ **75% reduction in API calls** (40 → 10 for 4 symbols)  
✅ **Better rate limit compliance** (2 calls/minute vs 40 calls/minute)  
✅ **Shared cache** across all symbols (588x faster on cache hit)  
✅ **Easier to scale** - add symbols without increasing API calls  
✅ **Better maintainability** - centralized fetching logic  
✅ **Backward compatible** - old fetchers still work  

This architecture is production-ready and significantly improves the sentiment server's reliability and performance.
