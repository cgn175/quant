# Sentiment Microservice

Market sentiment analysis microservice for the crypto trading bot. Aggregates sentiment data from multiple sources (Reddit, Twitter/X, CoinGecko, CryptoPanic, NewsAPI) and uses FinBERT to compute sentiment scores.

## Features

- **Multi-source sentiment aggregation**: Reddit, Twitter/X, CoinGecko, CryptoPanic, NewsAPI, Telegram channels
- **FinBERT-based sentiment analysis**: Fine-tuned BERT model for financial sentiment
- **Persistent storage**: SQLite database for hourly and daily sentiment history
- **Telegram integration**: Sends sentiment summaries twice daily (8 AM and 4 PM UTC)
- **Telegram channel monitoring**: Real-time crypto news from major Telegram channels (NEW)
- **Historical data endpoints**: Query sentiment trends over time
- **Per-source breakdown**: Track which sources are driving sentiment
- **Flood-resistant**: Exponential backoff retry logic for Telegram rate limits

## Quick Start

### 1. Install Dependencies

```bash
cd sentiment
pip install -r requirements.txt
```

### 2. Configure Credentials

Copy and configure `.env.example`:

```bash
cp .env.example .env
```

**Reddit OAuth Setup (Required):**

Reddit now requires OAuth 2.0. See detailed guide: **`docs/REDDIT_OAUTH_SETUP.md`**

Quick steps:
1. Visit https://www.reddit.com/prefs/apps
2. Create new app (select "script" type)
3. Copy Client ID and Secret
4. Add to `.env`:

```dotenv
# Reddit OAuth 2.0 (Required)
SENTIMENT_REDDIT_CLIENT_ID=your_client_id
SENTIMENT_REDDIT_CLIENT_SECRET=your_client_secret
SENTIMENT_REDDIT_USER_AGENT=quant-bot-sentiment/1.0

# Optional sources (free tiers available)
SENTIMENT_COINGECKO_API_KEY=your_coingecko_api_key
SENTIMENT_CRYPTOPANIC_API_KEY=your_cryptopanic_api_key
SENTIMENT_NEWSAPI_KEY=your_newsapi_key

# Optional (requires paid tier)
SENTIMENT_TWITTER_BEARER_TOKEN=your_twitter_api_token
```

### 3. Start the Microservice

```bash
python main.py
```

The API will be available at `http://localhost:8000`.

### 4. Enable in Bot Config

Update `config.yaml`:

```yaml
sentiment:
  enabled: true
  url: http://localhost:8000
  poll_interval_seconds: 60
  schedule_times:
    - "08:00"
    - "16:00"

alerts:
  telegram_bot_token: "your_bot_token"
  telegram_chat_id: 123456789
```

## API Endpoints

### `/sentiment/{symbol}`

Get current sentiment for a symbol.

**Example Request:**
```bash
curl http://localhost:8000/sentiment/BTCUSDT
```

**Response:**
```json
{
  "symbol": "BTCUSDT",
  "score_1h": 0.25,
  "score_24h": 0.18,
  "mentions": 342,
  "mentions_zscore": 1.5,
  "velocity": 0.12,
  "sources": ["reddit", "coingecko", "newsapi"],
  "timestamp": "2026-02-09T14:30:00Z"
}
```

**Fields:**
- `score_1h`: Sentiment over last hour (range: -1 to 1, >0 = bullish)
- `score_24h`: Sentiment over last 24 hours
- `mentions`: Number of mentions in last 24 hours
- `mentions_zscore`: How unusual the mention count is (>1.5 = very unusual)
- `velocity`: Rate of sentiment change (recent vs older)
- `sources`: Which data sources contributed to this sentiment

### `/sentiment/{symbol}/history`

Get historical sentiment data.

**Query Parameters:**
- `days`: Number of days to fetch (default: 7)
- `period`: `hourly` (last 7 days) or `daily` (last 90 days)

**Example Request:**
```bash
curl "http://localhost:8000/sentiment/BTCUSDT/history?days=7&period=hourly"
```

**Response:**
```json
{
  "symbol": "BTCUSDT",
  "period": "hourly",
  "data": [
    {
      "timestamp": "2026-02-09T14:00:00Z",
      "score_positive": 0.45,
      "score_negative": 0.20,
      "score_neutral": 0.35,
      "mentions_count": 342,
      "sources": ["reddit", "coingecko"]
    },
    ...
  ]
}
```

### `/health`

Health check endpoint.

**Response:**
```json
{
  "status": "ok",
  "model_loaded": true
}
```

## Data Sources

### Reddit (Free)
- **Subreddits**: r/CryptoCurrency, r/Bitcoin, r/ethereum, r/solana
- **Scoring**: Post upvotes weighted by recency
- **Rate limit**: Free tier (15 requests/minute)

### CoinGecko (Free)
- **Data**: Market data, sentiment votes, community metrics
- **Scoring**: Market change %, sentiment votes, community size
- **Rate limit**: Free tier (10-50 requests/minute depending on endpoint)

### CryptoPanic (Free tier available)
- **Data**: Crypto news from 150+ sources
- **Scoring**: Recent news classification (bullish/bearish/neutral)
- **Requires API key**: Free tier available at cryptopanic.com/api

### NewsAPI (Free tier available)
- **Data**: General finance/crypto news
- **Scoring**: Authority of news source (Reuters, Bloomberg, CoinDesk = higher weight)
- **Requires API key**: Free tier available at newsapi.org

### Twitter/X (Requires paid tier)
- **Data**: Real-time tweets about crypto
- **Scoring**: Tweet engagement (likes, retweets, replies)
- **Note**: Requires API v2 paid tier (not included by default)

### Telegram Channels (Free - NEW!)
- **Data**: Real-time messages from public crypto news channels
- **Channels**: CoinTelegraph, Binance Announcements, Bitcoin Magazine, CoinDesk, and more
- **Scoring**: Keyword-based sentiment extraction
- **Security**: Secure MTProto connection with session authentication
- **Requires**: Telegram API credentials (free from https://my.telegram.org/apps)
- **Rate limiting**: Built-in flood protection with exponential backoff
- **Setup guide**: See `docs/TELEGRAM_FETCHER.md`

## Sentiment Calculation

For each data source, the FinBERT model computes three probabilities:
- **Positive**: Bullish sentiment (0 to 1)
- **Negative**: Bearish sentiment (0 to 1)  
- **Neutral**: No directional signal (0 to 1)

**Aggregate sentiment score** = (Σ positive × weight - Σ negative × weight) / count

**Weighting by source** (configurable, current defaults):
- Reddit: 40%
- CoinGecko: 30%
- CryptoPanic: 20%
- NewsAPI: 10%
- Twitter: (disabled by default, requires paid tier)

## Database Schema

SQLite database with 4 tables:

### `sentiment_hourly`
Stores hourly sentiment aggregates (7 day retention):
- `symbol`: Trading symbol (e.g., BTCUSDT)
- `timestamp`: Unix timestamp
- `score_positive`, `score_negative`, `score_neutral`: Sentiment components
- `mentions_count`: Posts/mentions in that hour
- `sources`: Comma-separated list of sources used

### `sentiment_daily`
Stores daily sentiment aggregates (2 year retention):
- Same fields as hourly, but per-date

### `sentiment_source`
Granular per-source scores for analysis:
- `source`: Reddit, Twitter, CoinGecko, etc.
- `timestamp`: When the sentiment was computed
- `score`: Source-specific sentiment
- `mentions_count`: Mentions from this source

### `mention_history`
Hourly mention counts for zscore/velocity calculations:
- `symbol`: Trading symbol
- `timestamp`: Hour timestamp
- `count`: Mentions that hour

## Configuration

### Environment Variables

All sentiment env vars use the `SENTIMENT_` prefix:

```bash
SENTIMENT_REDDIT_CLIENT_ID=...
SENTIMENT_REDDIT_CLIENT_SECRET=...
SENTIMENT_TWITTER_BEARER_TOKEN=...
SENTIMENT_COINGECKO_API_KEY=...
SENTIMENT_CRYPTOPANIC_API_KEY=...
SENTIMENT_NEWSAPI_KEY=...
SENTIMENT_TELEGRAM_API_ID=...
SENTIMENT_TELEGRAM_API_HASH=...
SENTIMENT_UPDATE_INTERVAL=60
SENTIMENT_HISTORY_HOURS=24
SENTIMENT_MODEL_NAME=ProsusAI/finbert
```

### config.yaml Settings (Go Bot)

```yaml
sentiment:
  enabled: true                              # Enable sentiment feature
  url: http://localhost:8000                 # Microservice URL
  poll_interval_seconds: 60                  # How often to poll
  sentiment_threshold_long: 0.3              # Entry threshold for long
  sentiment_threshold_short: -0.3            # Entry threshold for short
  schedule_times:                            # Telegram notification times (UTC)
    - "08:00"
    - "16:00"
  use_database: true                         # Store historical data
  database_path: sentiment.db                # SQLite DB location
```

## Troubleshooting

### "Model not loaded" error
```
Solution: Check PyTorch installation and available disk space for model download
pip install --upgrade torch transformers
```

### API rate limiting
```
Solution: Increase SENTIMENT_UPDATE_INTERVAL or disable optional fetchers
SENTIMENT_UPDATE_INTERVAL=300  # Check every 5 minutes instead of 1
```

### Missing credentials for optional sources
```
Solution: These sources are optional. Leave empty to skip. Only Reddit is required.
The API will gracefully fall back to available sources.
```

### Database errors on startup
```
Solution: Ensure write permissions to sentiment.db location
chmod 666 sentiment.db
```

## Performance Notes

- Model loading: ~5-10 seconds on first startup (cached after)
- Per-request inference: ~100-200ms for 100 posts (GPU: ~20ms)
- Memory usage: ~2GB for model + ~500MB for batch inference
- Database size: ~10MB for 7 days hourly + 90 days daily

## Development

### Running Tests
```bash
pytest sentiment/
```

### Updating FinBERT Model
```bash
# Download latest FinBERT version
python -c "from transformers import AutoModel; AutoModel.from_pretrained('ProsusAI/finbert')"
```

### Debugging
```bash
# Verbose logging
LOGLEVEL=DEBUG python main.py

# Test individual fetcher
python -c "
from sentiment.fetchers import RedditFetcher
import asyncio
f = RedditFetcher()
posts = asyncio.run(f.fetch('BTCUSDT', 10))
print(f'Got {len(posts)} posts')
"
```

## Security Notes

- **Never commit `.env`** — it contains API keys
- **API keys in logs**: Truncate in production
- **Rate limit compliance**: All fetchers respect API rate limits
- **Request timeouts**: 10 second default, configurable per fetcher

## License

Same as main quant-bot project