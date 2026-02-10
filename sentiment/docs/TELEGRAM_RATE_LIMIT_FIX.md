# Telegram Fetcher Rate Limit Mitigation

## Issue Summary

The Telegram fetcher is experiencing rate limiting issues when the sentiment server polls multiple symbols rapidly. This is causing:
1. Connection timeouts/errors
2. HTTP 404 errors from Telegram servers
3. Slow response times
4. Potential IP-based rate limiting

## Root Causes

1. **Multiple Rapid Fetches**: When bot polls 4 symbols every minute, Telegram fetcher is called 4 times
2. **Shared Connection**: Single Telethon client shared across all fetch calls
3. **Per-Account Limits**: Telegram rate limits are per account, not per channel
4. **Network Issues**: Connection errors indicate possible IP-based throttling

## Implemented Mitigations

### 1. Reduced Rate Limits
```python
MESSAGES_PER_SECOND = 0.5  # Down from 1 (50% reduction)
BURST_LIMIT = 10          # Down from 20 (50% reduction)
MAX_RETRIES = 3           # Down from 5 (fail faster)
```

### 2. Minimum Fetch Interval
```python
MIN_FETCH_INTERVAL = 30  # seconds

# Enforces at least 30s between ANY fetch calls
async with self._fetch_lock:
    if time_since_last < MIN_FETCH_INTERVAL:
        await asyncio.sleep(wait_time)
```

**Effect**: When bot polls 4 symbols:
- Fetch 1 (BTCUSDT): Immediate
- Fetch 2 (ETHUSDT): Wait 30s
- Fetch 3 (SOLUSDT): Wait 30s
- Fetch 4 (BNBUSDT): Wait 30s
- Total: ~90 seconds for all 4

### 3. Reduced Retry Attempts
- Fail faster on errors (3 retries instead of 5)
- Prevents cascading delays

## Alternative Solutions

### Option 1: Disable Telegram Temporarily (Recommended)

**In `main.py`**:
```python
fetchers = {
    "reddit": RedditFetcher(),
    "coingecko": CoinGeckoFetcher(),
    "cryptopanic": CryptopanicFetcher(api_key=settings.cryptopanic_api_key),
    # ... other fetchers ...
    # "telegram": TelegramFetcher(...),  # Disabled due to rate limits
}
```

**Pros**:
- Immediate fix
- Other 9 fetchers still work
- Can re-enable later

**Cons**:
- Lose Telegram as data source

### Option 2: Batch Telegram Fetches

Only fetch Telegram once, cache results for all symbols:

```python
# Fetch market-wide once per minute
telegram_cache = {}
telegram_cache_time = 0

if time.time() - telegram_cache_time > 60:
    telegram_posts = await telegram_fetcher.fetch_all_channels()
    telegram_cache = group_posts_by_symbol(telegram_posts)
    telegram_cache_time = time.time()

# Use cached results
def telegram_fetch_wrapper(symbol):
    return telegram_cache.get(symbol, [])
```

### Option 3: Increase Bot Poll Interval

**In `config.yaml`**:
```yaml
sentiment:
  poll_interval_seconds: 120  # Up from 60
```

**Effect**: Bot polls half as often → Telegram called half as much

### Option 4: Reduce Symbols

Only enable Telegram for primary symbols:

```python
# In telegram.py, add symbol filter
TELEGRAM_ENABLED_SYMBOLS = ["BTCUSDT", "ETHUSDT"]

async def fetch(self, symbol: str, limit: int = 100):
    if symbol not in TELEGRAM_ENABLED_SYMBOLS:
        return []  # Skip Telegram for other symbols
    # ... rest of fetch logic
```

### Option 5: Use Telegram Bot API Instead of MTProto

Switch from Telethon (MTProto) to telegram.bot (Bot API):

**Pros**:
- Simpler, more reliable
- Better rate limit handling
- No session management

**Cons**:
- Can only read channels where bot is admin
- Need to create bot and add to channels
- More limited functionality

## Recommendation

**Short-term (Immediate)**:
1. **Disable Telegram fetcher** - Comment out in main.py
2. **Increase poll interval** - 60s → 120s in config.yaml
3. **Monitor other fetchers** - Check if CryptoPanic/NewsAPI also hitting limits

**Medium-term (1-2 weeks)**:
1. **Implement batched fetching** - Fetch Telegram once, share across symbols
2. **Add per-fetcher caching** - Cache Telegram results for 5 minutes
3. **Add circuit breaker** - Automatically disable failing fetchers

**Long-term (Future)**:
1. **Switch to Bot API** - More reliable for production
2. **Add webhook support** - Real-time updates instead of polling
3. **Implement smart polling** - Only fetch when needed

## Current Status

**Changes Applied**:
- ✅ Reduced rate limits (0.5 req/sec, burst 10)
- ✅ Added minimum fetch interval (30s between fetches)
- ✅ Reduced retry attempts (3 instead of 5)
- ✅ Added logging for rate limit waits

**Still Issues**:
- ❌ Connection timeouts (network-level throttling?)
- ❌ HTTP 404 errors from Telegram
- ❌ Slow overall response (45s+ per fetch)

## Quick Fix Instructions

### To Disable Telegram Immediately

**Edit `sentiment/main.py`**:
```python
# Around line 40-50
fetchers = {
    "reddit": RedditFetcher(),
    "coingecko": CoinGeckoFetcher(),
    "cryptopanic": CryptopanicFetcher(api_key=settings.cryptopanic_api_key),
    "twitter": TwitterFetcher(bearer_token=settings.twitter_bearer_token),
    "newsapi": NewsAPIFetcher(api_key=settings.newsapi_key),
    "coinmarketcap": CoinMarketCapFetcher(api_key=settings.coinmarketcap_api_key),
    "marketaux": MarketauxFetcher(api_key=settings.marketaux_api_key),
    "finnhub": FinnhubFetcher(api_key=settings.finnhub_api_key),
    "fmp": FMPFetcher(api_key=settings.fmp_api_key),
    # Temporarily disabled due to rate limiting issues
    # "telegram": TelegramFetcher(
    #     api_id=settings.telegram_api_id if settings.telegram_api_id else None,
    #     api_hash=settings.telegram_api_hash if settings.telegram_api_hash else None,
    #     session_name=settings.telegram_session_name,
    # ),
}
```

**Restart server**:
```bash
# Ctrl+C to stop
python main.py
```

### To Reduce Polling Frequency

**Edit `config.yaml`**:
```yaml
sentiment:
  poll_interval_seconds: 120  # Change from 60
```

**Restart bot**:
```bash
./bot
```

## Monitoring

**Check if fixed**:
```bash
# Watch logs
tail -f sentiment/sentiment_server.log | grep -i "telegram\|rate"

# Look for:
# - "Telegram: Rate limiting, waiting X.Xs" (good, throttling working)
# - "Fetcher 'telegram' returned N posts" (good, working)
# - "Failed to initialize" (bad, still broken)
```

**Check performance**:
```bash
# Time a request
time curl http://localhost:8000/sentiment/BTCUSDT

# Should be < 10s with Telegram disabled
# Will be 30-60s with Telegram enabled
```

## Testing After Fix

```bash
# Test without Telegram
curl http://localhost:8000/sentiment/BTCUSDT

# Should respond in 2-3 seconds with other fetchers
```

## Conclusion

**Immediate action needed**: Disable Telegram fetcher until we implement batched fetching or switch to Bot API.

The 30-second minimum interval helps but isn't enough given the connection issues. The server still has 9 other fetchers that work reliably.
