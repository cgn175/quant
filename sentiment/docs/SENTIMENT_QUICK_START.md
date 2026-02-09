# Sentiment Endpoint — Quick Integration Guide

## What Was Implemented

A complete sentiment analysis system that:
1. **Fetches market news** from 5 sources (Reddit, CoinGecko, CryptoPanic, Twitter/X, NewsAPI)
2. **Analyzes sentiment** using FinBERT (financial sentiment model)
3. **Stores data** in SQLite for historical analysis
4. **Sends notifications** via Telegram twice daily (8 AM and 4 PM UTC)
5. **Integrates with your bot** via HTTP client

## Files You Need to Know About

### Configuration
- **`config.yaml`** — Add sentiment section with `enabled: true` to activate
- **`.env`** — Add your API keys (only Reddit required, others optional)
- **`docker-compose.yaml`** — Updated with sentiment service env vars

### Sentiment Service (Python)
- **`sentiment/main.py`** — FastAPI server, runs on port 8000
- **`sentiment/db.py`** — SQLite database layer for persistence
- **`sentiment/fetchers/`** — News source modules (reddit, coingecko, cryptopanic, twitter, newsapi)
- **`sentiment/README.md`** — Full API documentation

### Trading Bot (Go)
- **`internal/sentiment/client.go`** — HTTP client to fetch sentiment
- **`internal/sentiment/scheduler.go`** — Telegram notification scheduler
- **`cmd/bot/main.go`** — Bot integration (lines ~320-340 show setup)

## How to Enable

### 1. API Credentials (Reddit OAuth Required)

**Reddit OAuth Setup (Required):**
- Visit https://www.reddit.com/prefs/apps
- Create new app (select "script" type, NOT "web app")
- Copy Client ID and Client Secret
- See detailed guide with screenshots: `docs/REDDIT_OAUTH_SETUP.md`

**Other sources (all optional):**
- CoinGecko: Free (no auth needed)
- CryptoPanic: Free tier available
- NewsAPI: Free tier available
- Twitter/X: Requires paid API tier

Configure in `.env`:
```bash
# Copy template
cp env.example .env

# Reddit OAuth credentials (required)
SENTIMENT_REDDIT_CLIENT_ID=your_client_id
SENTIMENT_REDDIT_CLIENT_SECRET=your_client_secret

# Other sources (optional)
SENTIMENT_COINGECKO_API_KEY=  # Leave empty for free tier
SENTIMENT_CRYPTOPANIC_API_KEY=  # Optional
SENTIMENT_NEWSAPI_KEY=  # Optional
SENTIMENT_TWITTER_BEARER_TOKEN=  # Optional, requires paid tier
```

### 2. Enable in Trading Bot Config

```yaml
# config.yaml
sentiment:
  enabled: true              # ← Change to true
  url: http://localhost:8000
  poll_interval_seconds: 60
  schedule_times:
    - "08:00"              # 8 AM UTC
    - "16:00"              # 4 PM UTC
  use_database: true
  database_path: sentiment.db

alerts:
  telegram_bot_token: "your_telegram_bot_token"
  telegram_chat_id: 123456789
```

### 3. Start Services

**Terminal 1 — Sentiment service:**
```bash
cd sentiment
pip install -r requirements.txt
python main.py
# Will listen on http://localhost:8000
```

**Terminal 2 — Trading bot:**
```bash
go build -o bin/bot ./cmd/bot
./bin/bot -c config.yaml
```

### 4. Verify It Works

```bash
# Check sentiment endpoint
curl http://localhost:8000/sentiment/BTCUSDT

# Check historical data
curl "http://localhost:8000/sentiment/BTCUSDT/history?days=7&period=hourly"

# Health check
curl http://localhost:8000/health
```

**Expected output:**
```json
{
  "symbol": "BTCUSDT",
  "score_1h": 0.25,
  "score_24h": 0.18,
  "mentions": 342,
  "mentions_zscore": 1.5,
  "velocity": 0.12,
  "sources": ["reddit", "coingecko"],
  "timestamp": "2026-02-09T14:30:00Z"
}
```

## Sentiment Scores Explained

- **score_1h / score_24h**: Range -1 (very bearish) to +1 (very bullish)
- **mentions**: How many posts/articles about this crypto
- **mentions_zscore**: How unusual the mention count is (>1.5 = notable spike)
- **velocity**: Sentiment acceleration (positive = getting more bullish)
- **sources**: Which data sources were used (all active sources shown)

## Telegram Notifications

You'll receive messages like:

```
📊 Market Sentiment Report

📈 BTCUSDT ↗️
  Score: 0.25 (1h), 0.18 (24h)
  Mentions: 342 (z-score: 1.50)
  Sources: reddit, coingecko, newsapi

➡️ ETHUSDT →
  Score: 0.05 (1h), 0.08 (24h)
  Mentions: 215 (z-score: 0.80)
  Sources: reddit, cryptopanic

⏰ Updated: 08:00 UTC
```

**Automatic:** Scheduled at 08:00 and 16:00 UTC daily

**On-Demand:** Send `/markets` command to get instant sentiment insights anytime

**Emoji guide:**
- 📈 = Bullish (score > 0.3)
- 📉 = Bearish (score < -0.3)
- ➡️ = Neutral (-0.3 to 0.3)
- ↗️ = Improving sentiment
- ↘️ = Worsening sentiment

## Testing

### Unit tests (Python):
```bash
cd sentiment
pip install pytest pytest-asyncio
pytest test_sentiment.py -v
```

### Build test (Go):
```bash
go build ./cmd/bot
go test ./internal/sentiment -v
```

## Troubleshooting

### "Connection refused" on port 8000
```
Sentiment service not running. Start it first:
cd sentiment && python main.py
```

### "No sentiment data available"
```
Bot hasn't polled yet, or sentiment service is down.
Check: curl http://localhost:8000/health
Should return: {"status":"ok","model_loaded":true}
```

### Telegram messages not arriving
1. Verify `telegram_bot_token` is valid (get from @BotFather)
2. Verify `telegram_chat_id` is correct (send /start to your bot, check logs)
3. Check bot has permission to send messages in that chat
4. Verify `sentiment.enabled: true` in config.yaml

### Out of memory
```
FinBERT model is large (~2GB). Make sure you have:
- 4GB RAM minimum recommended
- GPU optional but recommended for inference speed
```

### Rate limit errors
```
If hitting API limits, increase polling interval:
sentiment:
  poll_interval_seconds: 300  # 5 minutes instead of 1
```

## What Happens Under the Hood

1. **Every 60 seconds** (configurable):
   - Sentiment service fetches from all enabled sources
   - FinBERT analyzes sentiment
   - Stores to SQLite
   - Bot caches latest data

2. **At 08:00 and 16:00 UTC** (configurable):
   - Scheduler fetches latest sentiment for all symbols
   - Builds markdown report
   - Sends via Telegram

3. **Automatically cleans up**:
   - Keeps last 7 days of hourly data
   - Keeps last 2 years of daily aggregates
   - Prunes old entries nightly

## Next Steps

1. **Get Reddit API credentials** (free):
   - Visit reddit.com/prefs/apps
   - Create app, get client ID + secret

2. **Get Telegram bot token** (free):
   - Chat with @BotFather on Telegram
   - Create bot, get token

3. **Optional: Add more news sources**:
   - CoinGecko: Sign up at coingecko.com/api (free)
   - CryptoPanic: Sign up at cryptopanic.com/api (free)
   - NewsAPI: Sign up at newsapi.org (free tier)

4. **Monitor sentiment trends**:
   - Check `/sentiment/{symbol}/history` endpoint
   - Plot trends over time
   - Use for timing entries/exits

## API Reference

### GET `/sentiment/{symbol}`
Real-time sentiment data

### GET `/sentiment/{symbol}/history`
- Query: `?days=N&period=hourly|daily`
- Hourly: last 7 days (N ≤ 7)
- Daily: last 90 days (N ≤ 90)

### GET `/health`
Service health check

## Files Modified

**Python (11 files):**
- sentiment/db.py (new)
- sentiment/fetchers/*.py (new × 4)
- sentiment/main.py
- sentiment/config.py
- sentiment/models/__init__.py
- sentiment/test_sentiment.py (new)
- sentiment/README.md (new)
- sentiment/requirements.txt

**Go (4 files):**
- internal/sentiment/client.go
- internal/sentiment/scheduler.go (new)
- internal/config/config.go
- cmd/bot/main.go

**Config (5 files):**
- config.yaml.example
- env.example
- docker-compose.yaml
- sentiment/.env.example

## Summary

✅ **Ready to use:**
- Multi-source sentiment fetching
- SQLite persistence
- Telegram notifications
- Full API with historical data
- Comprehensive tests and docs

🚀 **Next:** Enable in config.yaml and start receiving market sentiment reports!