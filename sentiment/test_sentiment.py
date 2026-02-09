"""
Unit tests for sentiment module.

Run with: pytest sentiment/ -v
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest

from sentiment.db import SentimentDB
from sentiment.fetchers.base import Post
from sentiment.fetchers.coingecko import CoinGeckoFetcher
from sentiment.fetchers.reddit import RedditFetcher


@pytest.fixture
def temp_db(tmp_path):
    """Fixture for temporary SQLite database."""
    db_path = tmp_path / "test_sentiment.db"
    return SentimentDB(db_path=str(db_path))


@pytest.mark.asyncio
async def test_save_and_retrieve_hourly_sentiment(temp_db):
    """Test saving and retrieving hourly sentiment."""
    now = datetime.now(timezone.utc)

    # Save hourly sentiment
    result = await temp_db.save_hourly_sentiment(
        symbol="BTCUSDT",
        timestamp=now,
        score_positive=0.6,
        score_negative=0.2,
        score_neutral=0.2,
        mentions_count=100,
        sources=["reddit", "coingecko"],
    )
    assert result is True

    # Retrieve hourly sentiment
    data = await temp_db.get_hourly_sentiment("BTCUSDT", hours=24)
    assert len(data) > 0
    assert data[0]["score_positive"] == 0.6
    assert data[0]["score_negative"] == 0.2
    assert "reddit" in data[0]["sources"]


@pytest.mark.asyncio
async def test_save_and_retrieve_daily_sentiment(temp_db):
    """Test saving and retrieving daily sentiment."""
    date_str = "2026-02-09"

    # Save daily sentiment
    result = await temp_db.save_daily_sentiment(
        symbol="ETHUSDT",
        date=date_str,
        score_positive=0.5,
        score_negative=0.3,
        score_neutral=0.2,
        mentions_count=250,
        sources=["reddit", "newsapi"],
    )
    assert result is True

    # Retrieve daily sentiment
    data = await temp_db.get_daily_sentiment("ETHUSDT", days=30)
    assert len(data) > 0
    assert data[0]["date"] == date_str
    assert data[0]["mentions_count"] == 250


@pytest.mark.asyncio
async def test_save_and_retrieve_mention_history(temp_db):
    """Test saving and retrieving mention history."""
    now = datetime.now(timezone.utc)

    # Save mention history
    result = await temp_db.save_mention_history(
        symbol="SOLUSDT",
        timestamp=now,
        count=50,
    )
    assert result is True

    # Retrieve mention history
    data = await temp_db.get_mention_history("SOLUSDT", hours=24)
    assert len(data) > 0
    assert data[0][1] == 50  # count


@pytest.mark.asyncio
async def test_cleanup_old_data(temp_db):
    """Test database cleanup of old data."""
    old_time = datetime.now(timezone.utc) - timedelta(days=10)
    recent_time = datetime.now(timezone.utc) - timedelta(hours=1)

    # Save old and recent data
    await temp_db.save_hourly_sentiment(
        symbol="BTCUSDT",
        timestamp=old_time,
        score_positive=0.5,
        score_negative=0.3,
        score_neutral=0.2,
        mentions_count=100,
        sources=["reddit"],
    )

    await temp_db.save_hourly_sentiment(
        symbol="BTCUSDT",
        timestamp=recent_time,
        score_positive=0.6,
        score_negative=0.2,
        score_neutral=0.2,
        mentions_count=150,
        sources=["reddit"],
    )

    # Cleanup
    await temp_db.cleanup_old_data()

    # Verify old data is gone
    old_data = await temp_db.get_hourly_sentiment("BTCUSDT", hours=240)  # 10 days
    # Old data should be cleaned up, only recent data remains
    assert all(d["mentions_count"] == 150 for d in old_data)


def test_post_creation():
    """Test creating Post objects."""
    now = datetime.now(timezone.utc)
    post = Post(
        text="Bitcoin to the moon!",
        source="reddit",
        symbol="BTCUSDT",
        timestamp=now,
        score=5,
    )

    assert post.text == "Bitcoin to the moon!"
    assert post.source == "reddit"
    assert post.symbol == "BTCUSDT"
    assert post.score == 5


@pytest.mark.asyncio
async def test_reddit_fetcher_initialization():
    """Test Reddit fetcher initialization."""
    with patch.dict(
        "os.environ",
        {
            "SENTIMENT_REDDIT_CLIENT_ID": "test_id",
            "SENTIMENT_REDDIT_CLIENT_SECRET": "test_secret",
        },
    ):
        fetcher = RedditFetcher()
        assert fetcher.reddit is None or hasattr(fetcher, "reddit")


@pytest.mark.asyncio
async def test_coingecko_fetcher_mapping():
    """Test CoinGecko fetcher coin ID mapping."""
    fetcher = CoinGeckoFetcher()

    assert fetcher._get_coin_ids("BTCUSDT") == ["bitcoin"]
    assert fetcher._get_coin_ids("ETHUSDT") == ["ethereum"]
    assert fetcher._get_coin_ids("SOLUSDT") == ["solana"]
    assert fetcher._get_coin_ids("BNBUSDT") == ["binancecoin"]


def test_coingecko_sentiment_extraction():
    """Test sentiment extraction from CoinGecko data."""
    fetcher = CoinGeckoFetcher()

    data = {
        "market_data": {
            "price_change_percentage_24h": 5.2,
        },
        "sentiment_votes_up_percentage": 75.5,
        "community_data": {
            "twitter_followers": 10000,
        },
    }

    sentiment = fetcher._extract_sentiment(data, "bitcoin")
    assert sentiment is not None
    assert "5.20%" in sentiment
    assert "75.5%" in sentiment
    assert "10000" in sentiment


@pytest.fixture
def sentiment_data():
    """Sample sentiment data for testing."""
    return {
        "symbol": "BTCUSDT",
        "score_1h": 0.25,
        "score_24h": 0.18,
        "mentions": 342,
        "mentions_zscore": 1.5,
        "velocity": 0.12,
        "sources": ["reddit", "coingecko"],
        "timestamp": datetime.now(timezone.utc),
    }


def test_sentiment_response_model(sentiment_data):
    """Test SentimentResponse Pydantic model."""
    from sentiment.main import SentimentResponse

    response = SentimentResponse(**sentiment_data)
    assert response.symbol == "BTCUSDT"
    assert response.score_24h == 0.18
    assert len(response.sources) == 2


def test_historical_response_model():
    """Test HistoricalSentimentResponse model."""
    from sentiment.main import HistoricalSentimentResponse

    data = {
        "symbol": "ETHUSDT",
        "data": [
            {
                "date": "2026-02-09",
                "score_positive": 0.5,
                "score_negative": 0.3,
                "score_neutral": 0.2,
                "mentions_count": 100,
                "sources": ["reddit"],
            }
        ],
        "period": "daily",
    }

    response = HistoricalSentimentResponse(**data)
    assert response.symbol == "ETHUSDT"
    assert response.period == "daily"
    assert len(response.data) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
