from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from typing import Optional
import asyncio
from collections import defaultdict
import statistics

from config import get_settings
from fetchers import RedditFetcher, Post
from models import FinBERTAnalyzer, get_analyzer

app = FastAPI(title="Sentiment Microservice", version="1.0.0")

sentiment_cache: dict[str, dict] = {}
post_history: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
post_history_lock = asyncio.Lock()
fetcher = RedditFetcher()


class SentimentResponse(BaseModel):
    symbol: str
    score_1h: float
    score_24h: float
    mentions: int
    mentions_zscore: float
    velocity: float
    timestamp: datetime


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


async def compute_sentiment(symbol: str) -> dict:
    posts = await fetcher.fetch(symbol, limit=100)
    now = datetime.now(timezone.utc)
    
    if not posts:
        return {
            "symbol": symbol,
            "score_1h": 0.0,
            "score_24h": 0.0,
            "mentions": 0,
            "mentions_zscore": 0.0,
            "velocity": 0.0,
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

    for post, sent in zip(posts, sentiments):
        score = sent["positive"] - sent["negative"]
        weight = max(1, post.score) if post.score > 0 else 1

        if post.timestamp >= hour_ago:
            posts_1h.append(sent)
            weights_1h.append(weight)

        if post.timestamp >= day_ago:
            posts_24h.append(sent)
            weights_24h.append(weight)

    score_1h = analyzer.compute_score(posts_1h, weights_1h) if posts_1h else 0.0
    score_24h = analyzer.compute_score(posts_24h, weights_24h) if posts_24h else 0.0

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

    return {
        "symbol": symbol,
        "score_1h": round(score_1h, 4),
        "score_24h": round(score_24h, 4),
        "mentions": mentions,
        "mentions_zscore": round(mentions_zscore, 4),
        "velocity": round(velocity, 4),
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
    older = [s for ts, s in history if now - timedelta(hours=6) <= ts < now - timedelta(hours=1)]

    if not recent or not older:
        return 0.0

    recent_avg = sum(recent) / len(recent)
    older_avg = sum(older) / len(older)

    return recent_avg - older_avg


@app.on_event("startup")
async def startup():
    get_analyzer()
    asyncio.create_task(cleanup_old_data())


async def cleanup_old_data():
    while True:
        await asyncio.sleep(300)  # 5 minutes
        async with post_history_lock:
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(hours=24)
            stale_cutoff = now - timedelta(hours=1)
            for symbol in list(post_history.keys()):
                post_history[symbol] = [(ts, s) for ts, s in post_history[symbol] if ts >= cutoff]
                if not post_history[symbol]:
                    del post_history[symbol]
            for symbol in list(sentiment_cache.keys()):
                if sentiment_cache[symbol]["timestamp"] < stale_cutoff:
                    del sentiment_cache[symbol]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
