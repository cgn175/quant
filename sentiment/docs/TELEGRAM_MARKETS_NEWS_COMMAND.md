# Telegram /markets-news Command

## Overview

The `/markets-news` command provides instant market sentiment insights via Telegram by fetching and summarizing sentiment data from multiple news sources (Reddit, CoinGecko, CryptoPanic, NewsAPI, Twitter/X).

## Usage

Send the command to your bot:
```
/markets-news
```

## Response Example

```
📰 Market Sentiment News

📈 BTCUSDT
  Score: 0.25 | Mentions: 342 | Velocity: 0.12
  Sources: reddit, coingecko, newsapi

➡️ ETHUSDT
  Score: 0.05 | Mentions: 215 | Velocity: -0.03
  Sources: reddit, cryptopanic

📉 SOLUSDT
  Score: -0.15 | Mentions: 89 | Velocity: -0.08
  Sources: reddit

⏰ Updated: 14:30 UTC
```

## Data Displayed

For each configured trading symbol:

| Field | Description | Range |
|-------|-------------|-------|
| **Score** | Aggregate sentiment score from all sources | -1 to +1 |
| **Mentions** | Number of mentions/posts in last 24 hours | Integer |
| **Velocity** | Sentiment acceleration (recent vs older) | Float |
| **Sources** | News sources that contributed to sentiment | List |

## Sentiment Interpretation

| Emoji | Score | Meaning |
|-------|-------|---------|
| 📈 | > 0.3 | Bullish sentiment |
| ➡️ | -0.3 to 0.3 | Neutral sentiment |
| 📉 | < -0.3 | Bearish sentiment |

## Requirements

To use this command:

1. **Sentiment service must be enabled** in `config.yaml`:
   ```yaml
   sentiment:
     enabled: true
   ```

2. **At least one sentiment source configured** (requires API credentials):
   - Reddit (required) — Free
   - CoinGecko (optional) — Free
   - CryptoPanic (optional) — Free tier
   - NewsAPI (optional) — Free tier

3. **Bot has received sentiment data** — Wait for sentiment service to poll (default: every 60 seconds)

## Troubleshooting

### "Sentiment service not available"
**Solution:** Enable sentiment in config.yaml and ensure the sentiment microservice is running

```bash
# Start sentiment service
cd sentiment && python main.py

# Then start bot
go build ./cmd/bot && ./bin/bot -c config.yaml
```

### "No symbols configured"
**Solution:** Ensure your `config.yaml` has symbols defined:

```yaml
symbols:
  - BTCUSDT
  - ETHUSDT
  - SOLUSDT
  - BNBUSDT
```

### "No data available"
**Solution:** Wait for sentiment service to poll (default: 60 seconds after bot startup)

## Integration with Other Commands

| Command | Purpose |
|---------|---------|
| `/status` | Bot health and position status |
| `/markets-news` | Market sentiment from news sources |
| `/help` | List all available commands |

## Auto-Scheduled Reports

In addition to on-demand `/markets-news` queries, the bot can send automatic sentiment reports:

```yaml
sentiment:
  enabled: true
  schedule_times:
    - "08:00"  # 8 AM UTC
    - "16:00"  # 4 PM UTC
```

These scheduled reports are sent automatically without requiring a command.

## API Endpoints (Python Service)

The underlying sentiment service also exposes HTTP endpoints:

- `GET /sentiment/{symbol}` — Real-time sentiment
- `GET /sentiment/{symbol}/history?days=7&period=hourly` — Historical data
- `GET /health` — Service health

## Performance Notes

- **Response time:** 100-500ms (depends on sentiment service latency)
- **Data freshness:** As fresh as last sentiment service poll (default: 60 seconds)
- **Rate limit:** One request per 5 seconds (burst-safe for Telegram)

## Advanced: Filtering by Source

Currently, the `/markets-news` command shows all available sources. To filter by specific sources, you can:

1. **Configure sources in sentiment service** (`sentiment/.env`)
2. **Leave optional sources unconfigured** to exclude them

Example: Show only Reddit sentiment:
```bash
# sentiment/.env
SENTIMENT_REDDIT_CLIENT_ID=your_id
SENTIMENT_REDDIT_CLIENT_SECRET=your_secret

# Leave these empty:
# SENTIMENT_COINGECKO_API_KEY=
# SENTIMENT_CRYPTOPANIC_API_KEY=
# SENTIMENT_NEWSAPI_KEY=
```

---

**See also:** `SENTIMENT_QUICK_START.md` for sentiment service setup
