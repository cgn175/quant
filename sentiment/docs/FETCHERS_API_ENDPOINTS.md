Based on my verification of the latest documentation, here are the **corrected and updated** implementation instructions for your Claude agent:

***

## UPDATED Implementation Prompt: Multi-Provider Crypto & Finance API Interface

**Verified with latest documentation as of February 2026**

***

### 1. CoinGecko (VERIFIED)

```typescript
// Base: https://api.coingecko.com/api/v3
// NEW: WebSocket available on paid plans (Analyst+) - wss://wss.coingecko.com
// Auth: None (anonymous IP-based) OR x_cg_demo_api_key header for higher limits
// Rate Limits: 10-30 req/min (anonymous), 50 req/min (with free demo key)
// Coverage: 10M+ coins across 243 networks, 1,700+ DEXes

ENDPOINTS = {
  // Price & Market Data
  coinsMarkets: "GET /coins/markets?vs_currency={currency}&ids={comma_separated_ids}&order=market_cap_desc&per_page=250&page=1&sparkline=false",
  simplePrice: "GET /simple/price?ids={comma_separated_ids}&vs_currencies={comma_separated_currencies}&include_24hr_change=true",
  simpleTokenPrice: "GET /simple/token_price/{asset_platform_id}?contract_addresses={}&vs_currencies={}",
  
  // Coin Details
  coinData: "GET /coins/{id}?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false",
  coinHistory: "GET /coins/{id}/market_chart?vs_currency={currency}&days={days}",
  coinOHLC: "GET /coins/{id}/ohlc?vs_currency={currency}&days={1|7|14|30|90|180|365}",
  
  // Exchange & Trending
  exchanges: "GET /exchanges?per_page=100",
  exchangeTickers: "GET /exchanges/{id}/tickers?page=1",
  trending: "GET /search/trending",
  
  // Search
  search: "GET /search?query={query}"
}

// Response normalization:
interface CoinGeckoPrice {
  id: string;
  symbol: string;
  name: string;
  current_price: number;
  market_cap: number;
  price_change_24h: number;
  price_change_percentage_24h: number;
  total_volume: number;
  last_updated: string; // ISO 8601
}
```

**Important Corrections:**
- CoinGecko now tracks **10M+ coins** across **243 networks** [coingecko](https://www.coingecko.com/en/api)
- **WebSocket API is NEW** but only on paid plans (Analyst+) [eakdigital](https://eakdigital.com/top-10-crypto-news-apis-real-time-data-for-trading/)
- Free tier: 10-30 calls/minute without key, **50 calls/minute with free API key** [coingecko](https://www.coingecko.com/en/api)
- Use `x_cg_demo_api_key` header for authenticated requests (not query param)

***

### 2. CoinMarketCap (VERIFIED)

```typescript
// Base: https://pro-api.coinmarketcap.com/v1
// Auth: X-CMC_PRO_API_KEY header (REQUIRED)
// Rate Limits: 10,000 calls/month, 10 calls/second (free plan)

ENDPOINTS = {
  // Crypto Data
  map: "GET /cryptocurrency/map", // Get ID mappings
  listingsLatest: "GET /cryptocurrency/listings/latest?start=1&limit=5000&convert={currency}",
  quotesLatest: "GET /cryptocurrency/quotes/latest?id={ids}&symbol={symbols}&convert={currency}",
  ohlcvLatest: "GET /cryptocurrency/ohlcv/latest?id={id}&convert={currency}",
  ohlcvHistorical: "GET /cryptocurrency/ohlcv/historical?id={id}&convert={currency}&time_start={unix_ts}&time_end={unix_ts}",
  pricePerformance: "GET /cryptocurrency/price-performance-stats?id={id}&time_period={24h|7d|30d|60d|90d}",
  
  // Metadata
  info: "GET /cryptocurrency/info?id={ids}&symbol={symbols}",
  categories: "GET /cryptocurrency/categories",
  category: "GET /cryptocurrency/category?id={category_id}",
  
  // Exchange & Global
  exchangeMap: "GET /exchange/map",
  exchangeListings: "GET /exchange/listings/latest",
  globalMetrics: "GET /global-metrics/quotes/latest"
}

// Response normalization:
interface CMCPrice {
  id: number;
  name: string;
  symbol: string;
  quote: {
    [currency: string]: {
      price: number;
      volume_24h: number;
      percent_change_24h: number;
      market_cap: number;
      last_updated: string;
    }
  }
}
```

**Important Corrections:**
- **Header authentication ONLY**: `X-CMC_PRO_API_KEY: YOUR_API_KEY` [publicapis](https://publicapis.io/coin-market-cap-api)
- Free tier: **10,000 calls/month**, 10 calls/second [publicapis](https://publicapis.io/coin-market-cap-api)

***

### 3. Finnhub (VERIFIED)

```typescript
// Base: https://finnhub.io/api/v1
// Auth: token query parameter (REQUIRED)
// Rate Limits: 60 calls/minute (free tier)
// HARD LIMIT: 30 calls/second across ALL plans (including paid) [web:63]

ENDPOINTS = {
  // Stock Price Data
  quote: "GET /quote?symbol={symbol}&token={token}",
  candles: "GET /stock/candle?symbol={symbol}&resolution={1|5|15|30|60|D|W|M}&from={unix_ts}&to={unix_ts}&token={token}",
  tick: "GET /stock/tick?symbol={symbol}&date={YYYY-MM-DD}&token={token}",
  
  // Company Info
  companyProfile: "GET /stock/profile2?symbol={symbol}&token={token}",
  companyProfileISIN: "GET /stock/profile2?isin={isin}&token={token}",
  basicFinancials: "GET /stock/metric?symbol={symbol}&metric=all&token={token}",
  
  // News
  companyNews: "GET /company-news?symbol={symbol}&from={YYYY-MM-DD}&to={YYYY-MM-DD}&token={token}",
  generalNews: "GET /news?category={general|forex|crypto|merger}&token={token}",
  
  // Forex & Crypto
  forexCandles: "GET /forex/candle?symbol={symbol}&resolution={}&from={}&to={}&token={token}",
  forexRates: "GET /forex/rates?base={currency}&token={token}",
  cryptoCandles: "GET /crypto/candle?symbol={symbol}&resolution={}&from={}&to={}&token={token}",
  cryptoExchanges: "GET /crypto/exchange?token={token}",
  cryptoSymbols: "GET /crypto/symbol?exchange={exchange}&token={token}",
  
  // Alternative Data
  socialSentiment: "GET /stock/social-sentiment?symbol={symbol}&token={token}",
  newsSentiment: "GET /news-sentiment?symbol={symbol}&token={token}",
  
  // WebSocket (available on free tier)
  websocket: "wss://ws.finnhub.io?token={token}"
}

// WebSocket subscription message:
// {"type":"subscribe","symbol":"AAPL"}
// {"type":"subscribe","symbol":"BINANCE:BTCUSDT"}
```

**Critical Corrections:**
- **30 calls/second hard limit** applies to ALL plans (free and paid) [finnhub](https://finnhub.io/docs/api/rate-limit)
- Free tier: **60 calls/minute** [reddit](https://www.reddit.com/r/algotrading/comments/xxm5c8/finnhub_keep_getting_too_many_requests_even_with/?tl=zh-hant)
- Token passed as **query parameter**: `?token=YOUR_API_KEY` [pypi](https://pypi.org/project/finnhub-python/1.1.1/)
- WebSocket available on **free tier** [pypi](https://pypi.org/project/finnhub-python/1.1.1/)

***

### 4. Financial Modeling Prep (FMP) (VERIFIED)

```typescript
// Base: https://financialmodelingprep.com/stable
// Auth: apikey header OR query parameter
// Rate Limits: 250 calls/day (free tier), 300 calls/minute

// Header: apikey: YOUR_API_KEY
// OR Query: ?apikey=YOUR_API_KEY

ENDPOINTS = {
  // Prices & Quotes
  quote: "GET /quote?symbol={symbol}&apikey={key}",
  batchQuote: "GET /batch-quote?symbols={AAPL,MSFT,GOOG}&apikey={key}",
  quoteShort: "GET /quote-short?symbol={symbol}&apikey={key}",
  stockPriceChange: "GET /stock-price-change?symbol={symbol}&apikey={key}",
  
  // Historical Data
  historicalChart: "GET /historical-chart/{1min|5min|15min|30min|1hour|4hour}?symbol={symbol}&apikey={key}",
  historicalPriceFull: "GET /historical-price-eod/full?symbol={symbol}&apikey={key}",
  
  // Crypto
  cryptoList: "GET /cryptocurrency-list?apikey={key}",
  cryptoQuote: "GET /batch-crypto-quotes?apikey={key}",
  
  // News
  cryptoNews: "GET /news/crypto-latest?page=0&limit=20&apikey={key}",
  stockNews: "GET /news/stock-latest?page=0&limit=20&apikey={key}",
  generalNews: "GET /news/general-latest?page=0&limit=20&apikey={key}",
  forexNews: "GET /news/forex-latest?page=0&limit=20&apikey={key}",
  pressReleases: "GET /news/press-releases-latest?page=0&limit=20&apikey={key}",
  fmpArticles: "GET /fmp-articles?page=0&limit=20&apikey={key}",
  
  // Search News
  searchCryptoNews: "GET /news/crypto?symbols=BTCUSD&page=0&apikey={key}",
  searchStockNews: "GET /news/stock?symbols=AAPL&page=0&apikey={key}",
  
  // Company Profile
  profile: "GET /profile?symbol={symbol}&apikey={key}",
  stockPeers: "GET /stock-peers?symbol={symbol}&apikey={key}",
  
  // Financial Statements
  incomeStatement: "GET /income-statement?symbol={symbol}&period=annual&apikey={key}",
  balanceSheet: "GET /balance-sheet-statement?symbol={symbol}&apikey={key}",
  cashFlow: "GET /cash-flow-statement?symbol={symbol}&apikey={key}"
}
```

**Important Corrections:**
- New API structure uses `/stable/` path prefix (not `/api/v3/`) [cryptonews-api](https://cryptonews-api.com)
- Authorization: **Header** `apikey: YOUR_API_KEY` OR **query param** `?apikey=YOUR_API_KEY` [cryptonews-api](https://cryptonews-api.com)
- Use `&apikey=` if other query params exist, `?apikey=` if first param [cryptonews-api](https://cryptonews-api.com)
- Free tier: **250 calls/day** [stackoverflow](https://stackoverflow.com/questions/65780978/accessing-all-historical-crypto-data-with-specified-time-interval-using-financia/66773333)

***

### 5. Marketaux (VERIFIED)

```typescript
// Base: https://api.marketaux.com/v1
// Auth: api_token query parameter (REQUIRED)
// Rate Limits: 3,000 requests/month, 100/day (free tier) [web:3]

ENDPOINTS = {
  // News Endpoints
  newsAll: "GET /news/all?api_token={token}&symbols={symbols}&filter_entities={bool}&language={lang}&sentiment_gte={-1_to_1}",
  similarNews: "GET /news/similar/{uuid}?api_token={token}",
  newsByUuid: "GET /news/uuid/{uuid}?api_token={token}",
  
  // Entity Stats (Standard plan+)
  entityStatsIntraday: "GET /entity/stats/intraday?api_token={token}&symbols={symbols}&interval={minute|hour|day|week|month|quarter|year}",
  entityStatsAggregation: "GET /entity/stats/aggregation?api_token={token}&symbols={symbols}&group_by={symbol|exchange|industry|country}",
  trendingEntities: "GET /entity/trending/aggregation?api_token={token}",
  
  // Metadata
  sources: "GET /news/sources?api_token={token}",
  entities: "GET /entity/search?api_token={token}&search={query}",
  entityTypes: "GET /entity/types?api_token={token}",
  industries: "GET /entity/industries?api_token={token}",
  exchanges: "GET /entity/exchanges?api_token={token}",
  countries: "GET /entity/countries?api_token={token}"
}

// Response structure for /news/all:
interface MarketauxNews {
  meta: {
    found: number;
    returned: number;
    limit: number;
    page: number;
  };
  data: {
    uuid: string;
    title: string;
    description: string;
    keywords: string;
    snippet: string;
    url: string;
    image_url: string;
    language: string;
    published_at: string; // ISO 8601 UTC
    source: string;
    relevance_score: number | null;
    entities: {
      symbol: string;
      name: string;
      exchange: string | null;
      exchange_long: string | null;
      country: string;
      type: string; // equity, cryptocurrency, etc.
      industry: string;
      match_score: number;
      sentiment_score: number;
      highlights: {
        highlight: string;
        sentiment: number;
        highlighted_in: "title" | "main_text";
      }[];
    }[];
    similar: string[]; // UUIDs of similar articles
  }[];
}
```

**Important Corrections:**
- Free tier: **100/day, 3,000/month** [marketaux](https://www.marketaux.com)
- **Entity sentiment analysis** included - sentiment_score per entity (-1 to +1) [marketaux](https://www.marketaux.com)
- Date formats accepted: `Y-m-d\TH:i:s`, `Y-m-d\TH:i`, `Y-m-d\TH`, `Y-m-d`, `Y-m`, `Y` [marketaux](https://www.marketaux.com)
- All dates returned in **UTC** [marketaux](https://www.marketaux.com)
- Advanced search syntax: `+` (AND), `|` (OR), `-` (negate), `"` (phrase), `*` (prefix), `()` (precedence)  [marketaux](https://www.marketaux.com)

***

### 6. CryptoPanic (VERIFIED)

```typescript
// Base: https://cryptopanic.com/api/v1
// Auth: auth_token query parameter (REQUIRED)
// Rate Limits: Not explicitly documented, implement conservative rate limiting

ENDPOINTS = {
  posts: "GET /posts/?auth_token={token}&currencies={symbols}&filter={filter}&regions={regions}",
  portfolio: "GET /portfolio/?auth_token={token}",
  social: "GET /social/?auth_token={token}"
}

// Query Parameters:
// - currencies: Comma-separated, e.g., "BTC,ETH,XRP"
// - filter: rising|hot|bullish|bearish|important|saved|lol
// - regions: en|de|es|it|pt|ru (can be multiple)
// - kind: news|media

// Response structure:
interface CryptoPanicPost {
  id: number;
  kind: string; // "news"
  domain: string;
  source: {
    title: string;
    region: string;
    domain: string;
  };
  title: string;
  published_at: string; // ISO 8601
  slug: string;
  currencies: {
    code: string;
    title: string;
    slug: string;
    url: string;
  }[];
  url: string;
  votes: {
    negative: number;
    positive: number;
    important: number;
    liked: number;
    disliked: number;
    lol: number;
    toxic: number;
    saved: number;
    comments: number;
  };
}
```

**Important Corrections:**
- Authentication via `auth_token` query parameter [github](https://github.com/roccomuso/cryptopanic)
- Multiple regions can be specified
- Community voting data included (positive, negative, important, etc.) [github](https://github.com/roccomuso/cryptopanic)

***

### 7. NewsAPI.ai (NOT NewsAPI.org) - CLARIFIED

**Important Distinction:** There are TWO different services:
1. **NewsAPI.org** (`newsapi.org`) - General news API
2. **NewsAPI.ai** (`newsapi.ai`) - Different provider (by AYLIEN/Quantexa)

You asked for **NewsAPI.ai** which is the AYLIEN/Quantexa service. Documentation shows it uses POST requests with complex query bodies for article search.

```typescript
// Note: NewsAPI.ai requires different authentication and POST-based queries
// Base: https://api.newsapi.ai/api/v1 (or similar - enterprise service)
// Auth: API key (varies by implementation)

// This is a DIFFERENT service than NewsAPI.org
// For most use cases, NewsAPI.org may be more accessible:
```

**Alternative: NewsAPI.org** (Simpler, has free tier)

```typescript
// Base: https://newsapi.org/v2
// Auth: apiKey query parameter OR header
// Rate Limits: 100 requests/day
