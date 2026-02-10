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
    
    # 7-day baseline metrics
    sentiment_zscore_7d: float
    mentions_zscore_7d: float
    sentiment_percentile_7d: float
    sentiment_momentum_6h: float
    sentiment_momentum_24h: float
    attention_momentum: float
    regime: str
    regime_confidence: float
    
    # Alerts
    alerts: list[dict]  # List of alert objects


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

        # Persist raw predictions (best-effort)
        try:
            raw_preds = []
            for post, sent in zip(posts, sentiments):
                pred_label = max(sent, key=sent.get)
                pred_confidence = sent[pred_label]
                raw_preds.append({
                    "text": post.text[:2000],
                    "source": post.source,
                    "fetched_at": datetime.now(timezone.utc),
                    "published_at": post.timestamp,
                    "pred_positive": sent["positive"],
                    "pred_negative": sent["negative"],
                    "pred_neutral": sent["neutral"],
                    "pred_label": pred_label,
                    "pred_confidence": pred_confidence,
                })
            await sentiment_db.save_raw_predictions(symbol, raw_preds)
        except Exception:
            pass  # Best-effort, don't break main flow

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
            (row["timestamp"], row.get("score_positive", 0) - row.get("score_negative", 0))
            for row in hourly_data
        ]
        
        # Get mention history
        historical_mentions = [
            (row["timestamp"], row.get("mentions_count", 0))
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
            sentiment_zscore_7d=report.baseline_metrics.sentiment_zscore_7d,
            mentions_zscore_7d=report.baseline_metrics.mentions_zscore_7d,
            sentiment_percentile_7d=report.baseline_metrics.sentiment_percentile_7d,
            sentiment_momentum_6h=report.baseline_metrics.sentiment_momentum_6h,
            sentiment_momentum_24h=report.baseline_metrics.sentiment_momentum_24h,
            attention_momentum=report.baseline_metrics.attention_momentum,
            regime=report.baseline_metrics.regime,
            regime_confidence=report.baseline_metrics.regime_confidence,
            alerts=[
                {
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "trigger_value": alert.trigger_value,
                    "threshold": alert.threshold,
                    "description": alert.description,
                    "suggested_action": alert.suggested_action,
                }
                for alert in report.alerts
            ],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/predictions/{symbol}")
async def get_predictions(symbol: str, hours: int = 24, source: Optional[str] = None):
    """Get raw predictions with FinBERT scores for a symbol."""
    predictions = await sentiment_db.get_raw_predictions(symbol, hours=hours, source=source)
    return {"symbol": symbol, "count": len(predictions), "predictions": predictions}


@app.get("/accuracy/{symbol}")
async def get_accuracy(symbol: str, days: int = 7):
    """Get prediction accuracy by comparing FinBERT predictions vs actual price movement."""
    accuracy = await sentiment_db.get_prediction_accuracy(symbol, days=days)
    return {"symbol": symbol, "days": days, **accuracy}


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
    
    # For true hourly persistence (this hour only)
    posts_this_hour = []
    weights_this_hour = []

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
            # Also collect for this hour's true aggregate
            posts_this_hour.append(sent)
            weights_this_hour.append(weight)

        if post.timestamp >= day_ago:
            posts_24h.append(sent)
            weights_24h.append(weight)

    score_1h = analyzer.compute_score(posts_1h, weights_1h) if posts_1h else 0.0
    score_24h = analyzer.compute_score(posts_24h, weights_24h) if posts_24h else 0.0

    # Calculate hourly aggregate (for this specific hour)
    if posts_this_hour:
        hourly_positive = sum(s["positive"] * w for s, w in zip(posts_this_hour, weights_this_hour))
        hourly_negative = sum(s["negative"] * w for s, w in zip(posts_this_hour, weights_this_hour))
        hourly_neutral = sum(s["neutral"] * w for s, w in zip(posts_this_hour, weights_this_hour))
        total_weight = sum(weights_this_hour)
        
        score_positive = hourly_positive / total_weight
        score_negative = hourly_negative / total_weight
        score_neutral = hourly_neutral / total_weight
    else:
        score_positive = 0.0
        score_negative = 0.0
        score_neutral = 0.0

    async with post_history_lock:
        for post, sent in zip(posts, sentiments):
            score = sent["positive"] - sent["negative"]
            if post.timestamp >= day_ago:
                post_history[symbol].append((post.timestamp, score))
        post_history[symbol] = [
            (ts, s) for ts, s in post_history[symbol] if ts >= day_ago
        ]

    mentions = len(posts_24h)
    
    # Use DB-backed calculations for better historical context
    mentions_zscore = await compute_mentions_zscore_from_db(symbol, mentions)
    velocity = await compute_velocity_from_db(symbol)
    
    # True hourly mentions count (this hour only)
    hourly_mentions = len(posts_this_hour)
    
    # Use hour-truncated timestamp for bucketing
    hour_bucket = now.replace(minute=0, second=0, microsecond=0)

    # Persist to database with hour-specific data
    await sentiment_db.save_hourly_sentiment(
        symbol=symbol,
        timestamp=hour_bucket,  # Hour-truncated timestamp
        score_positive=score_positive,
        score_negative=score_negative,
        score_neutral=score_neutral,
        mentions_count=hourly_mentions,  # This hour only
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

    # Save mention history for trend analysis (hourly count)
    await sentiment_db.save_mention_history(
        symbol=symbol,
        timestamp=hour_bucket,  # Hour-truncated timestamp
        count=hourly_mentions,  # This hour only
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


async def compute_mentions_zscore_from_db(
    symbol: str, current_mentions: int
) -> float:
    """Calculate z-score using 7-day DB history."""
    try:
        history = await sentiment_db.get_mention_history(symbol, hours=168)
        
        if len(history) < 10:
            return 0.0
        
        counts = [count for _, count in history]
        
        if len(counts) < 2:
            return 0.0
        
        mean = statistics.mean(counts)
        stdev = statistics.stdev(counts)
        
        if stdev == 0:
            return 0.0
        
        return (current_mentions - mean) / stdev
    except Exception:
        # Fallback to in-memory calculation
        return compute_mentions_zscore(symbol, current_mentions)


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


async def compute_velocity_from_db(symbol: str) -> float:
    """Calculate velocity using 7-day DB history."""
    try:
        history = await sentiment_db.get_hourly_sentiment(symbol, hours=24)
        
        if len(history) < 10:
            return 0.0
        
        # Calculate sentiment scores from DB rows
        scores = [
            (
                datetime.fromisoformat(row["timestamp"]),
                row.get("score_positive", 0) - row.get("score_negative", 0)
            )
            for row in history
        ]
        
        if not scores:
            return 0.0
        
        now = datetime.now(timezone.utc)
        recent = [s for ts, s in scores if ts >= now - timedelta(hours=6)]
        older = [
            s 
            for ts, s in scores 
            if now - timedelta(hours=24) <= ts < now - timedelta(hours=6)
        ]
        
        if not recent or not older:
            return 0.0
        
        recent_avg = statistics.mean(recent)
        older_avg = statistics.mean(older)
        
        return recent_avg - older_avg
    except Exception:
        # Fallback to in-memory calculation
        return compute_velocity(symbol)


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


async def save_market_snapshot_for_symbol(symbol: str):
    """Fetch current price from CoinGecko and save a market snapshot."""
    import httpx

    coin_map = {
        "BTCUSDT": "bitcoin",
        "ETHUSDT": "ethereum",
        "SOLUSDT": "solana",
        "BNBUSDT": "binancecoin",
    }

    coin_id = coin_map.get(symbol)
    if not coin_id:
        return

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": coin_id, "vs_currencies": "usd"},
            )
            if resp.status_code == 200:
                data = resp.json()
                price = data.get(coin_id, {}).get("usd")
                if price:
                    await sentiment_db.save_market_snapshot(
                        symbol=symbol,
                        timestamp=datetime.now(timezone.utc),
                        price_close=price,
                    )
    except Exception:
        pass


async def backfill_symbol_history(symbol: str, cutoff: datetime):
    """Backfill hourly and daily sentiment for a symbol using any available posts."""
    fetch_tasks = [fetcher.fetch(symbol, limit=200) for fetcher in fetchers.values()]
    all_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    posts = []
    sources_used = set()
    for result in all_results:
        if isinstance(result, list) and result:
            posts.extend(result)

    if not posts:
        return

    analyzer = get_analyzer()
    texts = [p.text for p in posts]
    sentiments = analyzer.analyze(texts)

    # Persist raw predictions (best-effort)
    try:
        raw_preds = []
        for post, sent in zip(posts, sentiments):
            pred_label = max(sent, key=sent.get)
            pred_confidence = sent[pred_label]
            raw_preds.append({
                "text": post.text[:2000],
                "source": post.source,
                "fetched_at": datetime.now(timezone.utc),
                "published_at": post.timestamp,
                "pred_positive": sent["positive"],
                "pred_negative": sent["negative"],
                "pred_neutral": sent["neutral"],
                "pred_label": pred_label,
                "pred_confidence": pred_confidence,
            })
        await sentiment_db.save_raw_predictions(symbol, raw_preds)
    except Exception:
        pass  # Best-effort, don't break main flow

    # Collect sources
    for post in posts:
        if post.timestamp >= cutoff:
            sources_used.add(post.source)

    # Bucket by hour for hourly aggregates
    hourly_buckets: dict[str, dict] = {}
    daily_buckets: dict[str, dict] = {}
    
    for post, sent in zip(posts, sentiments):
        if post.timestamp < cutoff:
            continue
        
        # Hourly bucket
        hour_bucket = post.timestamp.replace(minute=0, second=0, microsecond=0)
        hour_key = hour_bucket.isoformat()
        
        hourly_bucket = hourly_buckets.setdefault(
            hour_key,
            {
                "pos": 0.0,
                "neg": 0.0,
                "neu": 0.0,
                "weight": 0.0,
                "mentions": 0,
                "sources": set(),
                "timestamp": hour_bucket,
            },
        )
        weight = max(1, post.score) if post.score > 0 else 1
        hourly_bucket["pos"] += sent["positive"] * weight
        hourly_bucket["neg"] += sent["negative"] * weight
        hourly_bucket["neu"] += sent["neutral"] * weight
        hourly_bucket["weight"] += weight
        hourly_bucket["mentions"] += 1
        hourly_bucket["sources"].add(post.source)
        
        # Daily bucket (for long-term storage)
        date_key = post.timestamp.date().isoformat()
        daily_bucket = daily_buckets.setdefault(
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
        daily_bucket["pos"] += sent["positive"] * weight
        daily_bucket["neg"] += sent["negative"] * weight
        daily_bucket["neu"] += sent["neutral"] * weight
        daily_bucket["weight"] += weight
        daily_bucket["mentions"] += 1
        daily_bucket["sources"].add(post.source)

    # Save hourly aggregates
    for hour_key, bucket in hourly_buckets.items():
        total_weight = bucket["weight"] or 1.0
        await sentiment_db.save_hourly_sentiment(
            symbol=symbol,
            timestamp=bucket["timestamp"],
            score_positive=bucket["pos"] / total_weight,
            score_negative=bucket["neg"] / total_weight,
            score_neutral=bucket["neu"] / total_weight,
            mentions_count=bucket["mentions"],
            sources=sorted(bucket["sources"]),
        )
        
        # Also save mention history
        await sentiment_db.save_mention_history(
            symbol=symbol,
            timestamp=bucket["timestamp"],
            count=bucket["mentions"],
        )

    # Save daily aggregates
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

    # Save market snapshot (best-effort)
    try:
        await save_market_snapshot_for_symbol(symbol)
    except Exception:
        pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
