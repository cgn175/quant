import asyncio
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import get_settings
from db import SentimentDB
from fastapi import FastAPI, HTTPException
from fetchers import (
    CoinGeckoFetcher,
    CoinMarketCapFetcher,
    CryptopanicFetcher,
    FinnhubFetcher,
    FMPFetcher,
    MarketauxFetcher,
    NewsAPIFetcher,
    Post,
    RedditFetcher,
    TwitterFetcher,
)
from pydantic import BaseModel

from models import FinBERTAnalyzer, get_analyzer
from insights import InsightsGenerator, InsightReport

app = FastAPI(title="Sentiment Microservice", version="1.0.0")

sentiment_cache: dict[str, dict] = {}
post_history: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
post_history_lock = asyncio.Lock()

# Initialize fetchers
settings = get_settings()
fetchers = {
    "reddit": RedditFetcher(),
    "coingecko": CoinGeckoFetcher(),
    "cryptopanic": CryptopanicFetcher(api_key=settings.cryptopanic_api_key),
    "twitter": TwitterFetcher(bearer_token=settings.twitter_bearer_token),
    "newsapi": NewsAPIFetcher(api_key=settings.newsapi_key),
    "coinmarketcap": CoinMarketCapFetcher(api_key=settings.coinmarketcap_api_key),
    "marketaux": MarketauxFetcher(api_key=settings.marketaux_api_key),
    "finnhub": FinnhubFetcher(api_key=settings.finnhub_api_key),
    "fmp": FMPFetcher(api_key=settings.fmp_api_key),
}

# Database
sentiment_db = SentimentDB(db_path="sentiment.db")

# Insights generator
insights_generator = InsightsGenerator()

DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]


class SentimentResponse(BaseModel):
    symbol: str
    score_1h: float
    score_24h: float
    mentions: int
    mentions_zscore: float
    velocity: float
    sources: list[str]
    timestamp: datetime


class SourceSentimentBreakdown(BaseModel):
    source: str
    score: float
    mentions_count: int


class DetailedSentimentResponse(BaseModel):
    symbol: str
    score_positive: float
    score_negative: float
    score_neutral: float
    mentions: int
    sources: list[SourceSentimentBreakdown]
    timestamp: datetime


class HistoricalSentimentResponse(BaseModel):
    symbol: str
    data: list[dict]  # list of hourly or daily sentiment data
    period: str  # "hourly" or "daily"


class InsightReportResponse(BaseModel):
    """Extended sentiment report with actionable insights."""
    
    symbol: str
    timestamp: datetime
    current_sentiment: float
    
    # Theme analysis
    top_keywords: list[tuple[str, int]]
    recurring_themes: list[str]
    sentiment_by_theme: dict[str, float]
    
    # Source diversity
    total_sources: int
    active_sources: list[str]
    source_types: dict[str, int]
    source_agreement: float
    dominant_source: str | None
    coverage_score: float
    
    # Trend analysis
    trend_direction: str
    trend_strength: float
    anomaly_detected: bool
    anomaly_description: str | None
    confidence_interval: tuple[float, float]
    volatility: float
    
    # Recommendation
    signal: str
    confidence: float
    reasoning: list[str]
    risk_level: str
    suggested_action: str


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool


@app.get("/health", response_model=HealthResponse)
async def health():
    try:
        analyzer = get_analyzer()
        return HealthResponse(status="ok", model_loaded=True)
    except Exception:
        return HealthResponse(status="degraded", model_loaded=False)


@app.get("/sentiment/{symbol}", response_model=SentimentResponse)
async def get_sentiment(symbol: str):
    symbol = symbol.upper()

    if symbol in sentiment_cache:
        cached = sentiment_cache[symbol]
        cache_age = datetime.now(timezone.utc) - cached["timestamp"]
        if cache_age < timedelta(seconds=get_settings().sentiment_update_interval):
            return SentimentResponse(**cached)

    try:
        result = await compute_sentiment(symbol)
        sentiment_cache[symbol] = result
        return SentimentResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sentiment/{symbol}/history", response_model=HistoricalSentimentResponse)
async def get_sentiment_history(symbol: str, days: int = 7, period: str = "hourly"):
    """Fetch historical sentiment data.

    Args:
        symbol: Trading symbol (e.g., BTCUSDT)
        days: Number of days to fetch (default 7 for hourly, max 90 for daily)
        period: "hourly" (last 7 days) or "daily" (last 90 days)
    """
    symbol = symbol.upper()

    try:
        if period == "daily":
            data = await sentiment_db.get_daily_sentiment(symbol, days=min(days, 90))
        else:
            data = await sentiment_db.get_hourly_sentiment(
                symbol, hours=min(days * 24, 168)
            )

        return HistoricalSentimentResponse(
            symbol=symbol,
            data=data,
            period=period,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sentiment/{symbol}/insights", response_model=InsightReportResponse)
async def get_sentiment_insights(symbol: str, lookback_hours: int = 24):
    """Generate actionable insights from aggregated sentiment data.
    
    This endpoint provides:
    - Theme extraction from news content
    - Source diversity analysis
    - Trend detection and anomaly alerts
    - Actionable trading recommendations
    
    Args:
        symbol: Trading symbol (e.g., BTCUSDT)
        lookback_hours: Hours of data to analyze (default 24, max 168)
    """
    symbol = symbol.upper()
    lookback_hours = min(lookback_hours, 168)  # Cap at 7 days
    
    try:
        # Fetch fresh sentiment data
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=lookback_hours)
        
        # Gather posts from all sources
        fetch_tasks = [fetcher.fetch(symbol, limit=100) for fetcher in fetchers.values()]
        all_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        
        posts = []
        for result in all_results:
            if isinstance(result, list) and result:
                posts.extend(result)
        
        # Filter to lookback window
        posts = [p for p in posts if p.timestamp >= cutoff]
        
        if not posts:
            raise HTTPException(
                status_code=404,
                detail=f"No sentiment data available for {symbol} in the last {lookback_hours} hours"
            )
        
        # Analyze sentiment
        analyzer = get_analyzer()
        texts = [p.text for p in posts]
        sentiments = analyzer.analyze(texts)
        
        # Calculate current aggregated score
        weighted_scores = []
        weights = []
        for post, sent in zip(posts, sentiments):
            score = sent["positive"] - sent["negative"]
            weight = max(1, post.score) if post.score > 0 else 1
            weighted_scores.append(score * weight)
            weights.append(weight)
        
        current_score = sum(weighted_scores) / sum(weights) if weights else 0.0
        
        # Get historical data for trend analysis
        hourly_data = await sentiment_db.get_hourly_sentiment(symbol, hours=lookback_hours)
        historical_scores = [
            (datetime.fromisoformat(row["timestamp"]), row.get("score_positive", 0) - row.get("score_negative", 0))
            for row in hourly_data
        ]
        
        # Get mention history
        historical_mentions = [
            (datetime.fromisoformat(row["timestamp"]), row.get("mentions_count", 0))
            for row in hourly_data
        ]
        
        # Prepare data for insights generator
        posts_with_scores = [(post, sent["positive"] - sent["negative"]) for post, sent in zip(posts, sentiments)]
        
        # Generate insights report
        report = insights_generator.generate_report(
            symbol=symbol,
            posts=posts_with_scores,
            sentiments=sentiments,
            current_score=current_score,
            historical_scores=historical_scores,
            historical_mentions=historical_mentions,
        )
        
        # Convert to response model
        return InsightReportResponse(
            symbol=report.symbol,
            timestamp=report.timestamp,
            current_sentiment=report.current_sentiment,
            top_keywords=report.themes.top_keywords,
            recurring_themes=report.themes.recurring_themes,
            sentiment_by_theme=report.themes.sentiment_by_theme,
            total_sources=report.source_diversity.total_sources,
            active_sources=report.source_diversity.active_sources,
            source_types=report.source_diversity.source_types,
            source_agreement=report.source_diversity.source_agreement,
            dominant_source=report.source_diversity.dominant_source,
            coverage_score=report.source_diversity.coverage_score,
            trend_direction=report.trend.trend_direction,
            trend_strength=report.trend.trend_strength,
            anomaly_detected=report.trend.anomaly_detected,
            anomaly_description=report.trend.anomaly_description,
            confidence_interval=report.trend.confidence_interval,
            volatility=report.trend.volatility,
            signal=report.recommendation.signal,
            confidence=report.recommendation.confidence,
            reasoning=report.recommendation.reasoning,
            risk_level=report.recommendation.risk_level,
            suggested_action=report.recommendation.suggested_action,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def compute_sentiment(symbol: str) -> dict:
    """Compute sentiment from multiple sources and persist to database."""
    now = datetime.now(timezone.utc)

    # Fetch from all available sources in parallel
    fetch_tasks = [fetcher.fetch(symbol, limit=50) for fetcher in fetchers.values()]
    all_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    # Collect posts from successful fetchers
    posts = []
    sources_used = []
    for fetcher_name, result in zip(fetchers.keys(), all_results):
        if isinstance(result, list) and result:
            posts.extend(result)
            sources_used.append(fetcher_name)

    if not posts:
        return {
            "symbol": symbol,
            "score_1h": 0.0,
            "score_24h": 0.0,
            "mentions": 0,
            "mentions_zscore": 0.0,
            "velocity": 0.0,
            "sources": [],
            "timestamp": now,
        }

    analyzer = get_analyzer()
    texts = [p.text for p in posts]
    sentiments = analyzer.analyze(texts)

    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(hours=24)

    posts_1h = []
    posts_24h = []
    weights_1h = []
    weights_24h = []

    # Accumulate per-source metrics
    source_scores = defaultdict(lambda: {"positive": 0, "negative": 0, "count": 0})

    for post, sent in zip(posts, sentiments):
        score = sent["positive"] - sent["negative"]
        weight = max(1, post.score) if post.score > 0 else 1

        # Track per-source sentiment
        source_scores[post.source]["positive"] += sent["positive"] * weight
        source_scores[post.source]["negative"] += sent["negative"] * weight
        source_scores[post.source]["count"] += 1

        if post.timestamp >= hour_ago:
            posts_1h.append(sent)
            weights_1h.append(weight)

        if post.timestamp >= day_ago:
            posts_24h.append(sent)
            weights_24h.append(weight)

    score_1h = analyzer.compute_score(posts_1h, weights_1h) if posts_1h else 0.0
    score_24h = analyzer.compute_score(posts_24h, weights_24h) if posts_24h else 0.0

    # Calculate aggregate sentiment
    total_positive = sum(s["positive"] for s in sentiments)
    total_negative = sum(s["negative"] for s in sentiments)
    total_neutral = sum(s["neutral"] for s in sentiments)
    total = len(sentiments)

    score_positive = total_positive / total if total > 0 else 0
    score_negative = total_negative / total if total > 0 else 0
    score_neutral = total_neutral / total if total > 0 else 0

    async with post_history_lock:
        for post, sent in zip(posts, sentiments):
            score = sent["positive"] - sent["negative"]
            if post.timestamp >= day_ago:
                post_history[symbol].append((post.timestamp, score))
        post_history[symbol] = [
            (ts, s) for ts, s in post_history[symbol] if ts >= day_ago
        ]

    mentions = len(posts_24h)
    mentions_zscore = compute_mentions_zscore(symbol, mentions)
    velocity = compute_velocity(symbol)

    # Persist to database
    await sentiment_db.save_hourly_sentiment(
        symbol=symbol,
        timestamp=now,
        score_positive=score_positive,
        score_negative=score_negative,
        score_neutral=score_neutral,
        mentions_count=mentions,
        sources=sources_used,
    )

    # Save daily aggregate at midnight UTC
    if now.hour == 0 and now.minute < 5:
        date_str = (now - timedelta(days=1)).date().isoformat()
        await sentiment_db.save_daily_sentiment(
            symbol=symbol,
            date=date_str,
            score_positive=score_positive,
            score_negative=score_negative,
            score_neutral=score_neutral,
            mentions_count=mentions,
            sources=sources_used,
        )

    # Save mention history for trend analysis
    await sentiment_db.save_mention_history(
        symbol=symbol,
        timestamp=now,
        count=mentions,
    )

    return {
        "symbol": symbol,
        "score_1h": round(score_1h, 4),
        "score_24h": round(score_24h, 4),
        "mentions": mentions,
        "mentions_zscore": round(mentions_zscore, 4),
        "velocity": round(velocity, 4),
        "sources": sources_used,
        "timestamp": now,
    }


def compute_mentions_zscore(symbol: str, current_mentions: int) -> float:
    history = post_history.get(symbol, [])
    if len(history) < 10:
        return 0.0

    hourly_counts = defaultdict(int)
    for ts, _ in history:
        hour_key = ts.replace(minute=0, second=0, microsecond=0)
        hourly_counts[hour_key] += 1

    counts = list(hourly_counts.values())
    if len(counts) < 2:
        return 0.0

    mean = statistics.mean(counts)
    stdev = statistics.stdev(counts)
    if stdev == 0:
        return 0.0

    return (current_mentions - mean) / stdev


def compute_velocity(symbol: str) -> float:
    history = post_history.get(symbol, [])
    if len(history) < 5:
        return 0.0

    now = datetime.now(timezone.utc)
    recent = [s for ts, s in history if ts >= now - timedelta(hours=1)]
    older = [
        s
        for ts, s in history
        if now - timedelta(hours=6) <= ts < now - timedelta(hours=1)
    ]

    if not recent or not older:
        return 0.0

    recent_avg = sum(recent) / len(recent)
    older_avg = sum(older) / len(older)

    return recent_avg - older_avg


@app.on_event("startup")
async def startup():
    get_analyzer()
    asyncio.create_task(cleanup_old_data())
    asyncio.create_task(cleanup_database())
    asyncio.create_task(backfill_history_if_empty())


async def cleanup_old_data():
    while True:
        await asyncio.sleep(300)  # 5 minutes
        async with post_history_lock:
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(hours=24)
            stale_cutoff = now - timedelta(hours=1)
            for symbol in list(post_history.keys()):
                post_history[symbol] = [
                    (ts, s) for ts, s in post_history[symbol] if ts >= cutoff
                ]
                if not post_history[symbol]:
                    del post_history[symbol]
            for symbol in list(sentiment_cache.keys()):
                if sentiment_cache[symbol]["timestamp"] < stale_cutoff:
                    del sentiment_cache[symbol]


async def cleanup_database():
    """Periodically clean up old sentiment data from database."""
    while True:
        await asyncio.sleep(3600)  # Every hour
        await sentiment_db.cleanup_old_data()


async def backfill_history_if_empty():
    """If the DB is empty, attempt to backfill up to 7 days of sentiment history."""
    try:
        if await sentiment_db.has_any_data():
            return

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=7)

        for symbol in DEFAULT_SYMBOLS:
            await backfill_symbol_history(symbol, cutoff)
    except Exception:
        # Best-effort only; skip on failure.
        return


async def backfill_symbol_history(symbol: str, cutoff: datetime):
    """Backfill daily sentiment for a symbol using any available posts."""
    fetch_tasks = [fetcher.fetch(symbol, limit=200) for fetcher in fetchers.values()]
    all_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    posts = []
    for result in all_results:
        if isinstance(result, list) and result:
            posts.extend(result)

    if not posts:
        return

    analyzer = get_analyzer()
    texts = [p.text for p in posts]
    sentiments = analyzer.analyze(texts)

    daily_buckets: dict[str, dict] = {}
    for post, sent in zip(posts, sentiments):
        if post.timestamp < cutoff:
            continue
        date_key = post.timestamp.date().isoformat()
        bucket = daily_buckets.setdefault(
            date_key,
            {
                "pos": 0.0,
                "neg": 0.0,
                "neu": 0.0,
                "weight": 0.0,
                "mentions": 0,
                "sources": set(),
            },
        )
        weight = max(1, post.score) if post.score > 0 else 1
        bucket["pos"] += sent["positive"] * weight
        bucket["neg"] += sent["negative"] * weight
        bucket["neu"] += sent["neutral"] * weight
        bucket["weight"] += weight
        bucket["mentions"] += 1
        bucket["sources"].add(post.source)

    for date_key, bucket in daily_buckets.items():
        total_weight = bucket["weight"] or 1.0
        await sentiment_db.save_daily_sentiment(
            symbol=symbol,
            date=date_key,
            score_positive=bucket["pos"] / total_weight,
            score_negative=bucket["neg"] / total_weight,
            score_neutral=bucket["neu"] / total_weight,
            mentions_count=bucket["mentions"],
            sources=sorted(bucket["sources"]),
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
