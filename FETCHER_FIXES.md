# Sentiment Fetcher Issues & Fixes

## Summary
The sentiment service is only getting data from CoinGecko because other fetchers have issues with API endpoints or authentication.

## Issues Found:

### 1. Reddit Fetcher
- **Problem**: Getting 401 Unauthorized error
- **Root Cause**: The Reddit API credentials are invalid or the app is not configured correctly
- **Solution**: User needs to:
  1. Go to https://www.reddit.com/prefs/apps
  2. Create a new "script" app (not web app)
  3. Use the client_id and client_secret from there
  4. Make sure the app type is "script" not "web"

### 2. CryptoPanic Fetcher  
- **Problem**: Using wrong API endpoint (404 error)
- **Current**: `https://cryptopanic.com/api/free/v1/posts/`
- **Correct**: `https://cryptopanic.com/api/v1/posts/`
- **Fixed**: Updated to use correct endpoint

### 3. NewsAPI Fetcher
- **Problem**: Getting 401 error - invalid API key
- **Root Cause**: The API key in .env is invalid
- **Solution**: User needs to:
  1. Go to https://newsapi.org/register
  2. Get a valid API key
  3. Update SENTIMENT_NEWSAPI_KEY in .env file

### 4. Base Token Extraction
- **Problem**: All fetchers were searching for full trading pair (e.g., "BTCUSDT") instead of base token (e.g., "BTC")
- **Fixed**: Added `extract_base_token()` function to extract BTC from BTCUSDT, ETH from ETHUSDT, etc.

## Changes Made:

1. ✅ Added `extract_base_token()` function in `base.py`
2. ✅ Updated Reddit fetcher to use base tokens
3. ✅ Fixed CryptoPanic API endpoint
4. ✅ Updated NewsAPI keyword mapping to use base tokens
5. ✅ Fixed asyncio event loop issues in db.py

## Testing Required:

User should verify:
1. Reddit API credentials are correct
2. NewsAPI key is valid  
3. CryptoPanic API key is valid
4. All fetchers now return news articles
