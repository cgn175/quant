***

## Implementation Prompt: Free Crypto & Finance News APIs

**Context:** Build a market data aggregation system for cryptocurrency and global finance monitoring. Target languages: Python, Go. Focus on free-tier endpoints with reliable uptime.

***

### 1. Crypto Market Data APIs

**CoinMarketCap API**
- Base URL: `https://pro-api.coinmarketcap.com/v1`
- Auth: `X-CMC_PRO_API_KEY` header required
- Key endpoints:
  - `GET /cryptocurrency/listings/latest` – All active coins with metrics
  - `GET /cryptocurrency/quotes/latest` – Latest quotes by symbol/ID
  - `GET /cryptocurrency/ohlcv/historical` – OHLCV historical data
- Free tier: 10,000 calls/month, 10 calls/second

**FreeCryptoAPI** (WebSocket priority)
- Base URL: `https://api.freecryptoapi.com/v1`
- Key endpoints:
  - `GET /getCoin` – Live price data for 3,000+ cryptos
  - `GET /getExchange` – Exchange rates (crypto-to-fiat/crypto)
  - WebSocket: Millisecond-latency streaming available
- Currencies: EUR, USD, GBP, TRY supported

***

### 3. Global Finance News APIs

**marketaux** (Best for free tier)
- Base URL: `https://api.marketaux.com/v1/news/all`
- Auth: `api_token` query parameter
- Key endpoints:
  - `GET /news/all` – All financial news
  - `GET /news/insights` – Sentiment analysis and entity extraction
  - Query params: `symbols=TSLA,AAPL`, `countries=us`, `language=en`
- Free tier: 3,000 requests/month, 100 requests/day
- Features: 5,000+ sources, 30 languages, 200+ markets

**Finnhub**
- Base URL: `https://finnhub.io/api/v1`
- Auth: `token` query parameter
- Key endpoints:
  - `GET /news` – General market news
  - `GET /company-news` – Company-specific news (by symbol and date range)
  - `GET /crypto-news` – Cryptocurrency news (distinct from stock news)
- Free tier: Real-time data, generous limits for personal use
- Features: WebSocket support for real-time trades

**Financial Modeling Prep (FMP)**
- Base URL: `https://financialmodelingprep.com/api/v3`
- Auth: `apikey` query parameter
- Key endpoints:
  - `GET /crypto_news` – Crypto news aggregation
  - `GET /stock_news` – Stock market news
  - `GET /fmp/articles` – FMP internal articles
- Features: Pagination support, sentiment indicators

***

### Implementation Requirements

1. **Rate limiting:** Implement exponential backoff and request queuing for all endpoints
2. **Caching:** Cache price data for 30-60 seconds; news data for 5-10 minutes
3. **Error handling:** Handle 429 (rate limit), 403 (auth), and network timeouts
4. **Data normalization:** Create unified interfaces for price objects (symbol, price, timestamp, source) and news objects (title, url, published_at, sentiment, source)
5. **Retry logic:** 3 retries with exponential backoff for transient failures

***
