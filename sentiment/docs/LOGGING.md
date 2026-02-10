# Sentiment Server Logging

## Overview

The sentiment server now includes comprehensive logging to track all operations, making it easier to debug issues and monitor performance.

## Log Output

Logs are written to:
1. **Console** (stdout) - real-time monitoring
2. **File** (`sentiment_server.log`) - persistent logs

## Log Format

```
YYYY-MM-DD HH:MM:SS,mmm - module_name - LEVEL - message
```

Example:
```
2026-02-10 19:20:15,123 - __main__ - INFO - Fetcher 'reddit' returned 45 posts
```

## What's Logged

### Startup
```
============================================================
Starting Sentiment Microservice
============================================================
Initializing FinBERT model...
FinBERT model loaded successfully
Configured fetchers: reddit, coingecko, cryptopanic, telegram, newsapi
Starting background tasks...
Sentiment server ready!
============================================================
```

### API Requests

#### Symbol Sentiment
```
INFO - GET /sentiment/BTCUSDT - Sentiment requested
INFO - Returning cached sentiment for BTCUSDT (age: 45.2s)
```

or

```
INFO - GET /sentiment/BTCUSDT - Sentiment requested
INFO - Cache expired for BTCUSDT, computing fresh sentiment...
INFO - Computing sentiment for BTCUSDT...
```

#### Market Sentiment
```
INFO - GET /sentiment/market - Market sentiment requested
INFO - Market sentiment cache expired, fetching fresh data...
INFO - Fetching general market news from Telegram...
INFO - Fetching general market news from CryptoPanic...
```

### Fetcher Operations

#### Per-Symbol Fetching
```
INFO - Fetching from 9 sources: reddit, coingecko, cryptopanic, twitter, newsapi, coinmarketcap, marketaux, finnhub, fmp, telegram
INFO - Fetcher 'reddit' returned 45 posts
INFO - Fetcher 'telegram' returned 12 posts
INFO - Fetcher 'cryptopanic' returned 89 posts
WARNING - Fetcher 'twitter' failed: Authentication required
DEBUG - Fetcher 'newsapi' returned no posts
```

#### Market Fetching
```
INFO - Fetching general market news from Telegram...
INFO - Fetching general market news from CryptoPanic...
INFO - Fetching general market news from NewsAPI...
INFO - Fetching general market news from Reddit...
INFO - Market fetcher 0 returned 67 posts
INFO - Market fetcher 1 returned 123 posts
INFO - Total market posts collected: 234 from 4 sources
```

### FinBERT Analysis
```
INFO - Analyzing 146 posts with FinBERT for BTCUSDT...
INFO - FinBERT analysis complete for BTCUSDT
INFO - Sentiment computed for BTCUSDT: score_1h=0.342, mentions=146
```

### Errors
```
WARNING - Fetcher 'telegram' failed: TimeoutError
ERROR - Error computing sentiment for BTCUSDT: Database connection failed
Traceback (most recent call last):
  File "/path/to/main.py", line 123, in compute_sentiment
    ...
```

## Log Levels

### INFO (default)
- API requests
- Cache hits/misses
- Fetcher results
- FinBERT operations
- Computed sentiment scores

### WARNING
- Fetcher failures (non-critical)
- No data from sources
- Cache issues

### ERROR
- Critical failures
- API endpoint errors
- Database errors
- Includes full stack trace

### DEBUG
- Empty results from fetchers
- Detailed internal state

## Configuration

### Change Log Level

Edit `main.py`:

```python
logging.basicConfig(
    level=logging.DEBUG,  # Change to DEBUG for verbose logs
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('sentiment_server.log')
    ]
)
```

Levels (from most to least verbose):
- `logging.DEBUG` - Everything
- `logging.INFO` - Normal operations (default)
- `logging.WARNING` - Only warnings and errors
- `logging.ERROR` - Only errors

### Disable File Logging

Remove file handler:

```python
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        # Remove: logging.FileHandler('sentiment_server.log')
    ]
)
```

### Change Log File Location

```python
logging.FileHandler('/var/log/sentiment/server.log')
```

## Viewing Logs

### Real-time Monitoring

```bash
# Watch console output
python main.py

# Or tail the log file
tail -f sentiment_server.log
```

### Filter by Level

```bash
# Show only errors
grep "ERROR" sentiment_server.log

# Show only warnings and errors
grep -E "WARNING|ERROR" sentiment_server.log
```

### Filter by Operation

```bash
# Show all fetcher operations
grep "Fetcher" sentiment_server.log

# Show all API requests
grep "GET /" sentiment_server.log

# Show all FinBERT operations
grep "FinBERT" sentiment_server.log
```

### Search for Specific Symbol

```bash
# All operations for BTCUSDT
grep "BTCUSDT" sentiment_server.log

# Sentiment computations only
grep "Computing sentiment for BTCUSDT" sentiment_server.log
```

## Example Log Session

```
2026-02-10 19:20:00,000 - __main__ - INFO - ============================================================
2026-02-10 19:20:00,001 - __main__ - INFO - Starting Sentiment Microservice
2026-02-10 19:20:00,002 - __main__ - INFO - ============================================================
2026-02-10 19:20:00,003 - __main__ - INFO - Initializing FinBERT model...
2026-02-10 19:20:02,145 - __main__ - INFO - FinBERT model loaded successfully
2026-02-10 19:20:02,146 - __main__ - INFO - Configured fetchers: reddit, telegram, cryptopanic, newsapi
2026-02-10 19:20:02,147 - __main__ - INFO - Starting background tasks...
2026-02-10 19:20:02,148 - __main__ - INFO - Sentiment server ready!
2026-02-10 19:20:02,149 - __main__ - INFO - ============================================================

2026-02-10 19:20:15,234 - __main__ - INFO - GET /sentiment/BTCUSDT - Sentiment requested
2026-02-10 19:20:15,235 - __main__ - INFO - Cache expired for BTCUSDT, computing fresh sentiment...
2026-02-10 19:20:15,236 - __main__ - INFO - Computing sentiment for BTCUSDT...
2026-02-10 19:20:15,237 - __main__ - INFO - Fetching from 4 sources: reddit, telegram, cryptopanic, newsapi
2026-02-10 19:20:17,123 - __main__ - INFO - Fetcher 'reddit' returned 45 posts
2026-02-10 19:20:22,456 - __main__ - INFO - Fetcher 'telegram' returned 12 posts
2026-02-10 19:20:18,789 - __main__ - INFO - Fetcher 'cryptopanic' returned 89 posts
2026-02-10 19:20:19,012 - __main__ - INFO - Fetcher 'newsapi' returned 23 posts
2026-02-10 19:20:22,500 - __main__ - INFO - Analyzing 169 posts with FinBERT for BTCUSDT...
2026-02-10 19:20:23,678 - __main__ - INFO - FinBERT analysis complete for BTCUSDT
2026-02-10 19:20:23,679 - __main__ - INFO - Sentiment computed for BTCUSDT: score_1h=0.342, mentions=169

2026-02-10 19:21:30,123 - __main__ - INFO - GET /sentiment/BTCUSDT - Sentiment requested
2026-02-10 19:21:30,124 - __main__ - INFO - Returning cached sentiment for BTCUSDT (age: 67.4s)

2026-02-10 19:25:00,000 - __main__ - INFO - GET /sentiment/market - Market sentiment requested
2026-02-10 19:25:00,001 - __main__ - INFO - Market sentiment cache expired, fetching fresh data...
2026-02-10 19:25:00,002 - __main__ - INFO - Fetching general market news from Telegram...
2026-02-10 19:25:00,003 - __main__ - INFO - Fetching general market news from CryptoPanic...
2026-02-10 19:25:00,004 - __main__ - INFO - Fetching general market news from NewsAPI...
2026-02-10 19:25:00,005 - __main__ - INFO - Fetching general market news from Reddit...
2026-02-10 19:25:08,234 - __main__ - INFO - Market fetcher 0 returned 67 posts
2026-02-10 19:25:09,123 - __main__ - INFO - Market fetcher 1 returned 123 posts
2026-02-10 19:25:10,456 - __main__ - INFO - Market fetcher 2 returned 89 posts
2026-02-10 19:25:11,789 - __main__ - INFO - Market fetcher 3 returned 45 posts
2026-02-10 19:25:11,790 - __main__ - INFO - Total market posts collected: 324 from 4 sources
2026-02-10 19:25:11,791 - __main__ - INFO - Analyzing 324 market posts with FinBERT...
2026-02-10 19:25:13,456 - __main__ - INFO - Market sentiment FinBERT analysis complete
2026-02-10 19:25:13,457 - __main__ - INFO - Market sentiment computed: regime=fear, score=-0.127, mentions=324
```

## Troubleshooting with Logs

### Problem: Slow Response Times

**Look for**:
```bash
grep "Analyzing.*posts" sentiment_server.log
```

If you see large batch sizes:
```
Analyzing 5000 posts with FinBERT for BTCUSDT...
```

**Solution**: Reduce fetch limits or implement batching.

### Problem: No Data for Symbol

**Look for**:
```bash
grep "No posts found for" sentiment_server.log
```

```
WARNING - No posts found for XYZUSDT from any source
```

**Solution**: Symbol not supported or no recent news.

### Problem: Fetcher Always Failing

**Look for**:
```bash
grep "Fetcher.*failed" sentiment_server.log
```

```
WARNING - Fetcher 'telegram' failed: TimeoutError
```

**Solution**: Check network, API keys, rate limits.

## Log Rotation

For production, use logrotate:

```bash
# /etc/logrotate.d/sentiment-server
/path/to/sentiment/sentiment_server.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0644 user group
}
```

## Performance Impact

Logging overhead is minimal:
- **INFO level**: ~0.1ms per log statement
- **DEBUG level**: ~0.2ms per log statement
- **File I/O**: Buffered, asynchronous

For high-throughput scenarios, consider:
- Reduce to WARNING level in production
- Use async file handler
- Disable console output

## License

Same as main quant-bot project.
