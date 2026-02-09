# Reddit OAuth 2.0 Documentation Update

## Problem Addressed

Reddit has deprecated their legacy app registration and now requires **OAuth 2.0 for all API access**. The old method of creating a "personal use script" app no longer works with a simple form - it now requires OAuth setup.

## Solution Implemented

Created comprehensive documentation for Reddit OAuth 2.0 setup and updated all guides to reference it.

## Files Created

### `docs/REDDIT_OAUTH_SETUP.md` (NEW)
Complete step-by-step guide for Reddit OAuth:
- How to create a Reddit account and access the app registration page
- Step-by-step instructions for creating an OAuth app
- Screenshots and field-by-field instructions
- How to copy credentials
- OAuth vs Legacy API comparison
- PRAW library details
- Troubleshooting common errors
- Alternative data sources (no Reddit needed)

## Files Updated

### 1. `SENTIMENT_QUICK_START.md`
- Added clear mention that Reddit now uses OAuth
- Reference to detailed OAuth guide
- Instructions to select "script" type (not "web app")
- Updated credential configuration section

### 2. `SENTIMENT_README.md`
- Updated quick start section with OAuth mention
- Link to Reddit OAuth setup guide
- Clear instructions about using script type
- Added environment variable names

### 3. `sentiment/README.md`
- Added Reddit OAuth setup section
- Link to detailed guide at `../docs/REDDIT_OAUTH_SETUP.md`
- Quick steps to create app and get credentials
- Environment variable configuration

## Key Information for Users

### Current State (2026)
```
✅ Reddit OAuth 2.0 is required
✅ Select "script" type when creating app
✅ PRAW library handles OAuth automatically
✅ No special code changes needed
✅ Credentials stored in .env (not committed)
```

### Setup Steps

1. **Visit Reddit App Portal**
   ```
   https://www.reddit.com/prefs/apps
   ```

2. **Create App**
   - Click "Create App" or "Create Another App"
   - Select type: **"script"** (not "web app")
   - Fill in name, description, redirect URI

3. **Get Credentials**
   - Client ID: String under app name (before "reddit")
   - Client Secret: String to the right of "secret"

4. **Configure Bot**
   ```bash
   # .env file
   SENTIMENT_REDDIT_CLIENT_ID=your_client_id
   SENTIMENT_REDDIT_CLIENT_SECRET=your_client_secret
   SENTIMENT_REDDIT_USER_AGENT=quant-bot-sentiment/1.0
   ```

5. **Test**
   ```bash
   cd sentiment && python main.py
   # Should see: ✅ Reddit fetcher initialized
   ```

## Why Script Type?

| App Type | Use Case | Notes |
|----------|----------|-------|
| **Script** | Our bot (personal use) | ✅ Read-only access, perfect for sentiment |
| **Web App** | Web-based apps | Requires redirect URI, more complex |
| **Mobile App** | Mobile apps | Not applicable |

## Security Notes

⚠️ **IMPORTANT:**
- Never share Client Secret publicly
- Keep in `.env` file (never commit to git)
- Treat like a password
- Can be revoked and recreated if compromised

## Error Handling

The documentation includes troubleshooting for common errors:

1. **"Invalid OAuth Scope"** → Wrong app type, create new as "script"
2. **"Unauthorized: invalid_grant"** → Wrong credentials copied
3. **"403 Forbidden"** → App not authorized, check status
4. **No posts found** → Rate limited or API down, wait and retry

## Alternative: No Reddit

If OAuth setup is too complex, users can use other data sources:

```bash
# Leave Reddit empty
# SENTIMENT_REDDIT_CLIENT_ID=
# SENTIMENT_REDDIT_CLIENT_SECRET=

# Use other free sources
SENTIMENT_COINGECKO_API_KEY=  # Free, no auth
SENTIMENT_CRYPTOPANIC_API_KEY=your_key  # Free tier
SENTIMENT_NEWSAPI_KEY=your_key  # Free tier
```

## Documentation Structure

```
User Guides:
├── SENTIMENT_QUICK_START.md          → Quick setup, mentions OAuth
├── SENTIMENT_README.md               → Full features, OAuth section
├── sentiment/README.md               → API docs, OAuth details
└── docs/REDDIT_OAUTH_SETUP.md        → Complete OAuth guide (NEW)

Changelog:
└── This file                          → What was updated and why
```

## Summary

✅ **Updated all documentation** to explain Reddit OAuth 2.0 requirement
✅ **Created detailed OAuth setup guide** with step-by-step instructions
✅ **Provided troubleshooting** for common OAuth errors
✅ **Included alternatives** for users who can't set up Reddit
✅ **Updated all relevant guides** to reference the OAuth documentation

**Status: COMPLETE**

Users can now:
1. Follow `docs/REDDIT_OAUTH_SETUP.md` for step-by-step OAuth setup
2. Or use alternative data sources (CoinGecko, CryptoPanic, NewsAPI)
3. Sentiment service works with or without Reddit data
