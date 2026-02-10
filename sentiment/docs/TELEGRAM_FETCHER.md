# Telegram Channel Fetcher

Integration guide for the Telethon-based Telegram channel fetcher. This fetcher monitors public Telegram channels for crypto news and sentiment data.

## Overview

The Telegram fetcher uses the **Telethon** library to connect to Telegram's MTProto API. It provides:

- **Exponential backoff retry logic** for handling Telegram flood limits
- **Rate limiting** to comply with API restrictions
- **Secure session management** with file-based storage
- **Automatic reconnection** on network failures
- **Message deduplication** to avoid processing the same message twice

## Security Features

### MTProto Connection Security

1. **Session File Protection**
   - Session files are stored with `0600` permissions (owner read/write only)
   - Session directory created with `0700` permissions
   - Session files contain authentication tokens and must never be committed to git

2. **API Credential Safety**
   - Credentials loaded from environment variables (`.env`)
   - No hardcoded credentials in code
   - API ID and hash validated before use

3. **Connection Best Practices**
   - Uses IPv6 when available for better privacy
   - Automatic reconnection with exponential backoff
   - Graceful error handling for authentication failures
   - Connection timeouts to prevent hanging

## Installation

### 1. Install Dependencies

```bash
cd sentiment
pip install -r requirements.txt
```

This installs `telethon==1.36.0` along with other dependencies.

### 2. Get Telegram API Credentials

1. Visit https://my.telegram.org/apps
2. Log in with your phone number
3. Create a new application:
   - **App title**: Sentiment Bot (or any name)
   - **Short name**: sentiment_bot
   - **Platform**: Other
4. Copy your **API ID** (integer) and **API Hash** (hex string)

### 3. Configure Environment Variables

Add to `sentiment/.env`:

```bash
# Telegram API credentials
SENTIMENT_TELEGRAM_API_ID=12345678
SENTIMENT_TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
SENTIMENT_TELEGRAM_SESSION_NAME=sentiment_bot
```

### 4. Authenticate with Telegram

Run the setup script to create a session file:

```bash
cd sentiment
python setup_telegram.py
```

This will:
1. Prompt for your phone number
2. Send a verification code to your Telegram account
3. Prompt for the verification code
4. If you have 2FA enabled, prompt for your password
5. Create a session file in `.telegram_sessions/`

**Important**: The session file is reusable. You only need to authenticate once.

### 5. Test the Connection

```bash
python setup_telegram.py test
```

This verifies:
- Session is valid
- Can connect to Telegram
- Can access public channels
- Can fetch messages

## Configuration

### Monitored Channels

Default channels (defined in `telegram.py`):

```python
DEFAULT_CHANNELS = [
    "cointelegraph",          # CoinTelegraph official
    "crypto",                 # Crypto.com News
    "bitcoinmagazine",        # Bitcoin Magazine
    "cryptonews",             # CryptoNews
    "cryptodaily_official",   # Crypto Daily
    "binance_announcements",  # Binance Official Announcements
    "coindesk",               # CoinDesk
]
```

To customize, pass `channels` parameter when initializing:

```python
from fetchers import TelegramFetcher

fetcher = TelegramFetcher(
    api_id=settings.telegram_api_id,
    api_hash=settings.telegram_api_hash,
    channels=["cointelegraph", "bitcoinmagazine"]
)
```

### Rate Limiting

Default rate limits (conservative to avoid flood errors):

```python
MESSAGES_PER_SECOND = 1      # Max 1 request per second
BURST_LIMIT = 20             # Up to 20 requests in burst
```

The fetcher uses a **token bucket algorithm** to enforce rate limits:
- Tokens refill at `MESSAGES_PER_SECOND` rate
- Bucket capacity is `BURST_LIMIT`
- Each API call consumes 1 token
- If no tokens available, the call waits

### Retry Configuration

Exponential backoff parameters:

```python
INITIAL_BACKOFF_SECONDS = 1   # Initial wait time
MAX_BACKOFF_SECONDS = 300     # Max wait time (5 minutes)
BACKOFF_MULTIPLIER = 2        # Backoff multiplier
MAX_RETRIES = 5               # Give up after 5 retries
```

## Flood Limit Handling

Telegram enforces rate limits to prevent API abuse. When you exceed limits, Telegram returns a `FloodWaitError` with the number of seconds to wait.

### How the Fetcher Handles Flood Limits

1. **Proactive Rate Limiting**
   - Rate limiter prevents most flood errors before they happen
   - Conservative default: 1 request/second

2. **Exponential Backoff Retry**
   - If `FloodWaitError` occurs, wait the exact time Telegram specifies
   - For other errors (network, timeout), use exponential backoff
   - Max 5 retries before giving up

3. **Graceful Degradation**
   - If one channel hits flood limit, continue with other channels
   - Errors logged but don't crash the fetcher

### Example Flood Handling Flow

```
Attempt 1: Request messages → FloodWaitError (wait 30s)
Wait 30 seconds...
Attempt 2: Request messages → ConnectionError
Wait 1 second (initial backoff)...
Attempt 3: Request messages → ConnectionError  
Wait 2 seconds (backoff * 2)...
Attempt 4: Request messages → Success ✓
```

## Usage

### Basic Fetch

```python
from fetchers import TelegramFetcher
import asyncio

fetcher = TelegramFetcher(
    api_id=12345678,
    api_hash="your_api_hash"
)

posts = await fetcher.fetch("BTCUSDT", limit=100)
print(f"Fetched {len(posts)} posts")

# Clean up
await fetcher.disconnect()
```

### Integration with Sentiment Server

The fetcher is automatically initialized in `main.py`:

```python
settings = get_settings()
fetchers = {
    # ... other fetchers ...
    "telegram": TelegramFetcher(
        api_id=settings.telegram_api_id if settings.telegram_api_id else None,
        api_hash=settings.telegram_api_hash if settings.telegram_api_hash else None,
        session_name=settings.telegram_session_name,
    ),
}
```

If credentials are not configured, the fetcher returns empty results (no error).

### Manual Testing

```python
import asyncio
from config import get_settings
from fetchers import TelegramFetcher

async def test_telegram():
    settings = get_settings()
    
    fetcher = TelegramFetcher(
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash
    )
    
    try:
        # Fetch BTC mentions
        posts = await fetcher.fetch("BTCUSDT", limit=50)
        print(f"Found {len(posts)} BTC posts")
        
        for post in posts[:5]:
            print(f"\n[{post.source}] {post.timestamp}")
            print(f"{post.text[:100]}...")
            print(f"Score: {post.score}")
    
    finally:
        await fetcher.disconnect()

asyncio.run(test_telegram())
```

## Troubleshooting

### "Session not authorized" Error

**Problem**: Session file doesn't exist or is invalid.

**Solution**: Run the setup script:
```bash
python setup_telegram.py
```

### "API ID Invalid" Error

**Problem**: Wrong API credentials or not registered on Telegram.

**Solution**:
1. Visit https://my.telegram.org/apps
2. Verify you're logged in
3. Check API ID and Hash are correct
4. Ensure you created an application (not just logged in)

### FloodWaitError with Long Wait Time

**Problem**: Exceeded Telegram's rate limits significantly.

**Solution**:
1. Wait the specified time (fetcher handles this automatically)
2. Reduce `MESSAGES_PER_SECOND` in `telegram.py`
3. Reduce `limit` parameter when calling `fetch()`
4. Reduce number of monitored channels

### "Channel Private or Doesn't Exist"

**Problem**: Channel username is wrong or channel is private.

**Solution**:
1. Verify channel username on Telegram (open channel, check `@username`)
2. Ensure channel is public
3. Test manually: search for `@channelname` in Telegram app

### Connection Errors

**Problem**: Network issues or firewall blocking Telegram.

**Solution**:
1. Check internet connection
2. Verify Telegram isn't blocked in your region
3. Try using a VPN if necessary
4. Check firewall rules for outbound connections

### Session File Permissions Error

**Problem**: Can't read/write session file.

**Solution**:
```bash
# Fix permissions
chmod 700 sentiment/.telegram_sessions/
chmod 600 sentiment/.telegram_sessions/*.session
```

## Performance Notes

- **Session initialization**: ~1-2 seconds (one-time per server start)
- **Message fetch**: ~500ms per channel (with rate limiting)
- **Memory usage**: ~50MB for Telethon client
- **Message cache**: Stores last 5000 message IDs to avoid duplicates

## Rate Limit Best Practices

1. **Start Conservative**: Default 1 req/sec is safe for most use cases
2. **Monitor Flood Errors**: If you see frequent FloodWaitErrors, reduce rate
3. **Batch Requests**: Fetch more messages per request (higher `limit`) rather than frequent small requests
4. **Prioritize Channels**: Monitor only the most important channels
5. **Off-Peak Usage**: Telegram limits are more lenient during off-peak hours

## Security Checklist

- [ ] API credentials stored in `.env` (not committed to git)
- [ ] Session files in `.telegram_sessions/` directory
- [ ] `.telegram_sessions/` added to `.gitignore`
- [ ] Session directory has `0700` permissions
- [ ] Session files have `0600` permissions
- [ ] No API credentials hardcoded in source code
- [ ] 2FA enabled on Telegram account (recommended)

## Architecture

### Components

1. **TelegramFetcher**: Main fetcher class
   - Manages Telethon client lifecycle
   - Implements BaseFetcher interface
   - Handles connection errors

2. **RateLimiter**: Token bucket rate limiter
   - Enforces API rate limits
   - Thread-safe (uses asyncio.Lock)
   - Prevents flood errors

3. **Exponential Backoff**: Retry logic
   - Handles FloodWaitError (uses Telegram's wait time)
   - Handles network errors (exponential backoff)
   - Max retries with graceful failure

### Data Flow

```
User Request
    ↓
fetch(symbol, limit)
    ↓
Initialize Client (if needed)
    ↓
For each channel:
    ↓
    Rate Limiter (acquire token)
    ↓
    Get Channel Entity (with retry)
    ↓
    Fetch Messages (with retry)
    ↓
    Filter by keywords
    ↓
    Deduplicate (message cache)
    ↓
    Extract sentiment score
    ↓
    Create Post objects
    ↓
Return all posts
```

## References

- **Telethon Documentation**: https://docs.telethon.dev/
- **Telegram API Documentation**: https://core.telegram.org/api
- **MTProto Protocol**: https://core.telegram.org/mtproto
- **Rate Limits**: https://core.telegram.org/api/obtaining_api_id#using-the-api-id

## License

Same as main quant-bot project.
