# Reddit OAuth Setup Guide (2026)

Reddit has deprecated traditional app registration and now requires OAuth 2.0 for all API access. This guide walks you through getting your Reddit OAuth credentials.

## Step-by-Step: Reddit OAuth Setup

### Step 1: Visit Reddit App Registration

1. Go to **https://www.reddit.com/prefs/apps**
2. Login to your Reddit account (create one if needed at reddit.com)

### Step 2: Create New App

1. Scroll down to "Developed applications"
2. Click **"Create App"** or **"Create Another App"** button

### Step 3: Fill in App Details

Fill in the form with the following:

| Field | Value | Notes |
|-------|-------|-------|
| **name** | `quant-bot-sentiment` | Any name you want |
| **App type** | **script** | Select "script" for personal use |
| **description** | `Crypto trading bot sentiment analysis` | Optional |
| **redirect URI** | `http://localhost:8000` | Leave as is (not used for script type) |

**Important:** For the bot, use **"script"** type (not "web app")

### Step 4: Copy Credentials

After creation, you'll see your app credentials:

```
                              web app
personal use script  refresh token   password grant
                                     oauth2 credentials
```

You need:
- **Client ID** — The long string under your app name (before "reddit")
- **Client Secret** — The secret string to the right of "secret"

Example (these are fake):
```
Client ID:     a1b2c3d4e5f6g7h8
Client Secret: AbCdEfGhIjKlMnOpQrStUv
```

### Step 5: Configure Your Bot

Create or update `.env` file in the project root:

```bash
# Reddit OAuth Credentials
SENTIMENT_REDDIT_CLIENT_ID=a1b2c3d4e5f6g7h8
SENTIMENT_REDDIT_CLIENT_SECRET=AbCdEfGhIjKlMnOpQrStUv

# User agent (required by Reddit API, use your username or app name)
SENTIMENT_REDDIT_USER_AGENT=quant-bot-sentiment/1.0
```

### Step 6: Test Connection

Start the sentiment service and check logs:

```bash
cd sentiment
python main.py
```

Check for successful Reddit connection:
```
✅ Reddit fetcher initialized
Fetching from: r/CryptoCurrency, r/Bitcoin, r/ethereum, r/solana
```

## OAuth vs Legacy API

| Method | Status | How It Works |
|--------|--------|-------------|
| **OAuth 2.0** | ✅ Current (2026) | Use app credentials + PRAW library |
| **Personal Script** | ✅ Still works | No app registration needed for read-only |
| **Web App** | ⚠️ Different flow | For web-based apps, not our use case |
| **Legacy** | ❌ Deprecated | Old method no longer works |

## PRAW Library Details

The bot uses **PRAW** (Python Reddit API Wrapper), which handles OAuth automatically:

```python
import praw

reddit = praw.Reddit(
    client_id='your_client_id',
    client_secret='your_client_secret',
    user_agent='quant-bot-sentiment/1.0'
)
```

PRAW automatically:
- ✅ Handles OAuth token refresh
- ✅ Manages rate limiting
- ✅ Provides easy access to posts/comments
- ✅ Works with script-type apps

## Important Notes

⚠️ **Never share your Client Secret!**
- Keep it in `.env` (never commit to git)
- Don't paste it in chat, email, or public places
- Treat it like a password

✅ **Rate Limits**
- 60 requests per minute per IP
- Our bot is well within limits
- PRAW handles rate limiting automatically

✅ **Read-Only Access**
- Script apps have read-only access (perfect for sentiment analysis)
- Can read posts, comments, subreddit data
- Cannot post or modify content

## Troubleshooting

### "Invalid OAuth Scope"
- **Cause**: Wrong app type selected during creation
- **Solution**: Delete app and create new one with "script" type

### "Unauthorized: invalid_grant"
- **Cause**: Wrong client ID or secret copied
- **Solution**: Double-check credentials from Reddit apps page

### "403 Forbidden"
- **Cause**: Subreddit access restricted or app not authorized
- **Solution**: Make sure app status is "installed"

### "No posts found"
- **Cause**: Reddit API not returning data (rate limited or API down)
- **Solution**: Check Reddit status, wait a few minutes, try again

### Sentiment service starts but no Reddit data
- **Cause**: Reddit credentials not configured
- **Solution**: Verify `.env` has `SENTIMENT_REDDIT_CLIENT_ID` and `SENTIMENT_REDDIT_CLIENT_SECRET`

## Alternative: No Reddit (Use Other Sources)

If you can't set up Reddit OAuth, the sentiment service still works with:
- ✅ CoinGecko (free, no auth)
- ✅ CryptoPanic (free tier)
- ✅ NewsAPI (free tier)
- ✅ Twitter/X (requires paid tier)

Just leave Reddit credentials empty in `.env`:
```bash
# Leave these empty
# SENTIMENT_REDDIT_CLIENT_ID=
# SENTIMENT_REDDIT_CLIENT_SECRET=

# But configure other sources
SENTIMENT_COINGECKO_API_KEY=  # Leave empty for free tier
SENTIMENT_CRYPTOPANIC_API_KEY=your_key
SENTIMENT_NEWSAPI_KEY=your_key
```

## Reddit Developer Portal (Advanced)

For more control, visit the developer portal:
- **URL**: https://www.reddit.com/wiki/oauth2
- **Quick Start**: https://github.com/reddit-archive/reddit/wiki/OAuth2

## Quick Checklist

- [ ] Have Reddit account
- [ ] Visited https://www.reddit.com/prefs/apps
- [ ] Created app (type: "script")
- [ ] Copied Client ID
- [ ] Copied Client Secret
- [ ] Added to `.env` file
- [ ] Test: `cd sentiment && python main.py`
- [ ] Verify Reddit data appears in logs

---

## Summary

1. **Create Reddit app** → https://www.reddit.com/prefs/apps
2. **Select "script" type**
3. **Copy credentials** → `.env`
4. **Start sentiment service** → `cd sentiment && python main.py`
5. **Done!** ✅ Reddit sentiment data will now be fetched

Questions? See the full sentiment setup guide at `SENTIMENT_QUICK_START.md`
