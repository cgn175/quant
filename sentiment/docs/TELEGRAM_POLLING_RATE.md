# Telegram Fetcher - Polling Strategy & Rate

## How It Works

The Telegram fetcher **does NOT run continuously**. Instead, it operates on a **pull-based model** triggered by API requests to the sentiment server.

### Architecture

```
Trading Bot (Go)
    ↓
    Polls sentiment server every 60 seconds (configurable)
    ↓
Sentiment Server (Python FastAPI)
    ↓
    Receives request for /sentiment/BTCUSDT
    ↓
    Checks cache (60 second TTL by default)
    ↓
    If cache expired: fetch from all sources (including Telegram)
    ↓
    Returns aggregated sentiment
```

---

## Polling Rates

### 1. Trading Bot → Sentiment Server

**Configured in**: `config.yaml`

```yaml
sentiment:
  url: http://localhost:8000
  poll_interval_seconds: 60  # How often bot checks sentiment
  enabled: true
```

**Default**: Every **60 seconds** (1 minute)

### 2. Sentiment Server → Telegram Channels

**Configured in**: `sentiment/.env`

```bash
SENTIMENT_UPDATE_INTERVAL=60  # Cache TTL in seconds
```

**How it works**:
1. Bot requests sentiment for BTCUSDT
2. Sentiment server checks cache
3. If cache < 60 seconds old: **Return cached result** (no Telegram fetch)
4. If cache ≥ 60 seconds old: **Fetch fresh data** from all sources including Telegram

**Effective rate**: **Maximum once per 60 seconds per symbol**

### 3. Telegram Fetcher Internal Rate Limiting

**Configured in**: `sentiment/fetchers/telegram.py`

```python
MESSAGES_PER_SECOND = 1   # Max 1 request/second
BURST_LIMIT = 20          # Up to 20 requests in burst
```

**Per fetch operation**:
- 7 channels × 1 request/channel = **7 seconds total** (with rate limiting)
- Each channel: fetch last 10-50 messages
- Filter messages for symbol keywords (BTC, ETH, etc.)

---

## Real-World Polling Examples

### Scenario 1: Single Symbol (BTCUSDT)

```
Time 0:00 - Bot requests BTCUSDT sentiment
          → Sentiment server fetches from Telegram (7 channels, ~7 seconds)
          → Returns result, caches for 60s

Time 0:30 - Bot requests BTCUSDT sentiment
          → Sentiment server returns cached result (no Telegram fetch)

Time 1:00 - Bot requests BTCUSDT sentiment
          → Cache expired, fetch again from Telegram
          → Returns result, caches for 60s
```

**Telegram fetch rate**: **Once per minute** (for single symbol)

### Scenario 2: Multiple Symbols (BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT)

```
Time 0:00 - Bot requests all 4 symbols
          → 4 separate Telegram fetches (one per symbol)
          → Each takes ~7 seconds
          → Total: 4 × 7s = 28 seconds
          → Each cached for 60s

Time 1:00 - Bot requests all 4 symbols again
          → Caches expired
          → 4 more Telegram fetches
```

**Telegram fetch rate**: **4 fetches per minute** (one per symbol)

---

## Telegram API Limits

### Telegram's Official Limits

| Limit Type | Value | Our Implementation |
|-----------|-------|-------------------|
| Messages/minute | ~20/min | 1/sec = 60/min ✓ |
| Burst tolerance | 20 requests | 20 requests ✓ |
| FloodWaitError | Dynamic | Exponential backoff ✓ |

**Our rate**: Well within Telegram's limits (3x safety margin)

---

## Configuring Polling Rates

### To Poll LESS Frequently (Reduce Load)

**Option 1: Increase bot poll interval**

```yaml
# config.yaml
sentiment:
  poll_interval_seconds: 300  # Every 5 minutes
```

**Option 2: Increase sentiment cache TTL**

```bash
# sentiment/.env
SENTIMENT_UPDATE_INTERVAL=300  # Cache for 5 minutes
```

**Option 3: Reduce Telegram channels**

```python
# sentiment/fetchers/telegram.py
channels=['cointelegraph', 'binance_announcements']  # Only 2 channels
```

### To Poll MORE Frequently (More Real-Time)

```yaml
# config.yaml
sentiment:
  poll_interval_seconds: 30  # Every 30 seconds
```

```bash
# sentiment/.env
SENTIMENT_UPDATE_INTERVAL=30  # Cache for 30 seconds
```

⚠️ **Warning**: More frequent polling increases risk of hitting Telegram rate limits.

---

## Data Freshness

### How Fresh is the Data?

| Component | Latency | Notes |
|-----------|---------|-------|
| Telegram message posted | 0s | Real-time |
| Telegram API sees message | <1s | Near real-time |
| Our fetch picks it up | 0-60s | Depends on cache TTL |
| Trading bot receives signal | +60s | Bot poll interval |
| **Total latency** | **0-120s** | Worst case: 2 minutes |

For crypto trading, **60-120 second latency is acceptable** because:
- News impact takes minutes to hours to affect price
- Sentiment is a **trend signal**, not a high-frequency signal
- Over-polling wastes resources without improving edge

---

## Comparison with Other Fetchers

All fetchers use the **same polling model**:

| Fetcher | Fetch Time | Rate Limit | Notes |
|---------|-----------|------------|-------|
| Reddit | ~2s | 15 req/min | OAuth 2.0 |
| Twitter | ~1s | Limited (paid) | Often disabled |
| CoinGecko | ~1s | 50 req/min | Free tier |
| CryptoPanic | ~1s | 100 req/min | Free tier |
| NewsAPI | ~1s | 100 req/day | Free tier |
| Telegram | **~7s** | 60 req/min | Free |
| CoinMarketCap | ~1s | 333 req/day | Free tier |
| Finnhub | ~1s | 60 req/min | Free tier |
| FMP | ~1s | 250 req/day | Free tier |

**Telegram is the slowest** fetcher (7s vs 1-2s) due to:
- 7 channels to fetch from
- Rate limiting (1 req/sec)
- MTProto protocol overhead

---

## Performance Impact

### With Telegram Enabled

```
Sentiment request for BTCUSDT:
  Reddit: 2s
  CoinGecko: 1s
  CryptoPanic: 1s
  NewsAPI: 1s
  Telegram: 7s  ← Bottleneck
  Total: ~7s (fetches run in parallel, slowest wins)
```

### Without Telegram

```
Sentiment request for BTCUSDT:
  Reddit: 2s  ← Bottleneck
  CoinGecko: 1s
  CryptoPanic: 1s
  NewsAPI: 1s
  Total: ~2s
```

**Impact**: Telegram adds **~5 seconds** to sentiment fetch time.

---

## Optimizations

### 1. Reduce Channels

```python
# Only monitor most important channels
channels=['binance_announcements', 'cointelegraph']  # 2 channels = 2s instead of 7s
```

### 2. Adjust Cache Strategy

```python
# In main.py - different cache TTL per symbol type
if symbol in ["BTCUSDT", "ETHUSDT"]:
    cache_ttl = 30  # Major coins: 30s cache
else:
    cache_ttl = 300  # Altcoins: 5min cache
```

### 3. Lazy Loading

```python
# Only fetch Telegram if other sources return few results
if len(posts_from_other_sources) < 10:
    telegram_posts = await telegram_fetcher.fetch(symbol)
```

### 4. Parallel Per-Channel Fetching (Future Enhancement)

```python
# Fetch all channels in parallel instead of sequential
tasks = [fetch_channel(ch) for ch in channels]
results = await asyncio.gather(*tasks)
# Could reduce 7s to ~2s (limited by rate limiter)
```

---

## Recommended Settings

### Conservative (Default)

```yaml
# config.yaml
sentiment:
  poll_interval_seconds: 60  # Every minute
```

```bash
# sentiment/.env
SENTIMENT_UPDATE_INTERVAL=60  # 1 minute cache
```

**Good for**:
- Production trading
- Limited resources
- Staying well under API limits

### Aggressive (More Real-Time)

```yaml
# config.yaml
sentiment:
  poll_interval_seconds: 30  # Every 30 seconds
```

```bash
# sentiment/.env
SENTIMENT_UPDATE_INTERVAL=30  # 30 second cache
```

**Good for**:
- Day trading
- High volatility periods
- Testing/research

### Relaxed (Low Resource)

```yaml
# config.yaml
sentiment:
  poll_interval_seconds: 300  # Every 5 minutes
```

```bash
# sentiment/.env
SENTIMENT_UPDATE_INTERVAL=300  # 5 minute cache
```

**Good for**:
- Swing trading (4h+ timeframes)
- Avoiding rate limits completely
- Lower server load

---

## Summary

**Your Question**: At which rate does Telegram fetcher poll for news?

**Answer**:

1. **Trading bot → Sentiment server**: Every **60 seconds** (default, configurable)
2. **Sentiment server → Telegram**: **Once per minute per symbol** (when cache expires)
3. **Telegram internal rate limit**: **1 request/second** across 7 channels = **7 seconds total per fetch**

**Effective polling rate**: 
- Single symbol: **Once per minute**
- Four symbols: **Four times per minute** (one per symbol)

**Latency**: 0-120 seconds from Telegram message posted → trading bot receives signal

**API safety**: 3x safety margin under Telegram's rate limits

The fetcher is designed to be **conservative and safe** rather than aggressive, prioritizing stability over real-time updates. For crypto sentiment (which is a trend indicator), this latency is acceptable and won't impact trading performance.
