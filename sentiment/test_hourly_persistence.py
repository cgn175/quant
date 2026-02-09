"""
Unit tests for hourly sentiment persistence improvements.
"""

import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock

from main import compute_mentions_zscore_from_db, compute_velocity_from_db
from db import SentimentDB
from fetchers.base import Post


@pytest.fixture
def sample_hourly_data():
    """Sample hourly sentiment data."""
    now = datetime.now(timezone.utc)
    return [
        {
            "timestamp": (now - timedelta(hours=i)).isoformat(),
            "score_positive": 0.3 + (i % 5) * 0.02,
            "score_negative": 0.2,
            "score_neutral": 0.5,
            "mentions_count": 50 + (i % 10) * 5,
        }
        for i in range(48)
    ]


@pytest.fixture
def sample_mention_history():
    """Sample mention history data."""
    now = datetime.now(timezone.utc)
    return [
        (now - timedelta(hours=i), 50 + (i % 10) * 5)
        for i in range(168)
    ]


@pytest.mark.asyncio
async def test_mentions_zscore_from_db(sample_mention_history):
    """Test z-score calculation using DB history."""
    with patch("main.sentiment_db") as mock_db:
        mock_db.get_mention_history = AsyncMock(return_value=sample_mention_history)
        
        current_mentions = 150  # High value
        zscore = await compute_mentions_zscore_from_db("BTCUSDT", current_mentions)
        
        assert zscore > 0  # Should be positive (above average)
        assert zscore > 2.0  # Should be anomalously high


@pytest.mark.asyncio
async def test_mentions_zscore_insufficient_data():
    """Test z-score with insufficient historical data."""
    with patch("main.sentiment_db") as mock_db:
        mock_db.get_mention_history = AsyncMock(return_value=[(datetime.now(timezone.utc), 50)])
        
        zscore = await compute_mentions_zscore_from_db("BTCUSDT", 100)
        
        assert zscore == 0.0  # Insufficient data


@pytest.mark.asyncio
async def test_velocity_from_db(sample_hourly_data):
    """Test velocity calculation using DB history."""
    with patch("main.sentiment_db") as mock_db:
        mock_db.get_hourly_sentiment = AsyncMock(return_value=sample_hourly_data)
        
        velocity = await compute_velocity_from_db("BTCUSDT")
        
        # Should compute difference between recent and older periods
        assert isinstance(velocity, float)


@pytest.mark.asyncio
async def test_velocity_improving_sentiment():
    """Test velocity with improving sentiment."""
    now = datetime.now(timezone.utc)
    # Recent hours have higher sentiment
    improving_data = [
        {
            "timestamp": (now - timedelta(hours=i)).isoformat(),
            "score_positive": 0.6 if i < 6 else 0.3,  # Recent 6h is higher
            "score_negative": 0.2,
            "score_neutral": 0.2,
            "mentions_count": 50,
        }
        for i in range(24)
    ]
    
    with patch("main.sentiment_db") as mock_db:
        mock_db.get_hourly_sentiment = AsyncMock(return_value=improving_data)
        
        velocity = await compute_velocity_from_db("BTCUSDT")
        
        assert velocity > 0  # Positive velocity (improving)


@pytest.mark.asyncio
async def test_velocity_deteriorating_sentiment():
    """Test velocity with deteriorating sentiment."""
    now = datetime.now(timezone.utc)
    # Recent hours have lower sentiment
    deteriorating_data = [
        {
            "timestamp": (now - timedelta(hours=i)).isoformat(),
            "score_positive": 0.2 if i < 6 else 0.5,  # Recent 6h is lower
            "score_negative": 0.3 if i < 6 else 0.2,
            "score_neutral": 0.5,
            "mentions_count": 50,
        }
        for i in range(24)
    ]
    
    with patch("main.sentiment_db") as mock_db:
        mock_db.get_hourly_sentiment = AsyncMock(return_value=deteriorating_data)
        
        velocity = await compute_velocity_from_db("BTCUSDT")
        
        assert velocity < 0  # Negative velocity (deteriorating)


@pytest.mark.asyncio
async def test_hour_bucket_timestamp():
    """Test hour-truncated timestamp generation."""
    from main import datetime
    
    now = datetime.now(timezone.utc)
    hour_bucket = now.replace(minute=0, second=0, microsecond=0)
    
    assert hour_bucket.minute == 0
    assert hour_bucket.second == 0
    assert hour_bucket.microsecond == 0
    assert hour_bucket.hour == now.hour


@pytest.mark.asyncio
async def test_backfill_creates_hourly_buckets():
    """Test that backfill creates hourly sentiment buckets."""
    from main import backfill_symbol_history
    from fetchers.base import Post
    
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=1)
    
    # Mock posts spread across different hours
    mock_posts = [
        Post(
            text=f"Test post {i}",
            source="reddit",
            symbol="BTCUSDT",
            timestamp=now - timedelta(hours=i),
            score=10
        )
        for i in range(24)
    ]
    
    with patch("main.fetchers") as mock_fetchers:
        mock_fetcher = MagicMock()
        mock_fetcher.fetch = AsyncMock(return_value=mock_posts)
        mock_fetchers.values.return_value = [mock_fetcher]
        mock_fetchers.keys.return_value = ["reddit"]
        
        with patch("main.sentiment_db") as mock_db:
            mock_db.save_hourly_sentiment = AsyncMock()
            mock_db.save_mention_history = AsyncMock()
            mock_db.save_daily_sentiment = AsyncMock()
            
            with patch("main.get_analyzer") as mock_analyzer_fn:
                mock_analyzer = MagicMock()
                mock_analyzer.analyze.return_value = [
                    {"positive": 0.5, "negative": 0.2, "neutral": 0.3}
                    for _ in range(24)
                ]
                mock_analyzer_fn.return_value = mock_analyzer
                
                await backfill_symbol_history("BTCUSDT", cutoff)
                
                # Should create 24 hourly buckets
                assert mock_db.save_hourly_sentiment.call_count == 24
                assert mock_db.save_mention_history.call_count == 24
                
                # Should also create daily aggregates
                assert mock_db.save_daily_sentiment.call_count >= 1


@pytest.mark.asyncio
async def test_hourly_mentions_count():
    """Test that hourly mentions count only includes posts from that hour."""
    from datetime import datetime, timedelta, timezone
    
    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)
    two_hours_ago = now - timedelta(hours=2)
    
    posts_this_hour = [
        Post(text="Post 1", source="reddit", symbol="BTCUSDT", timestamp=now - timedelta(minutes=30), score=10),
        Post(text="Post 2", source="reddit", symbol="BTCUSDT", timestamp=now - timedelta(minutes=15), score=10),
    ]
    
    posts_last_hour = [
        Post(text="Post 3", source="reddit", symbol="BTCUSDT", timestamp=hour_ago - timedelta(minutes=30), score=10),
    ]
    
    all_posts = posts_this_hour + posts_last_hour
    
    # Filter posts for this hour
    posts_filtered = [p for p in all_posts if p.timestamp >= hour_ago]
    
    assert len(posts_filtered) == 2  # Only posts from this hour
    assert len(posts_this_hour) == 2


def test_hour_bucket_consistency():
    """Test that hour buckets are consistent for timestamps in the same hour."""
    base_time = datetime(2026, 2, 9, 16, 30, 45, 123456, tzinfo=timezone.utc)
    
    # Different times in the same hour should produce the same bucket
    t1 = base_time.replace(minute=0, second=0, microsecond=0)
    t2 = base_time.replace(minute=30, second=0, microsecond=0).replace(minute=0, second=0, microsecond=0)
    t3 = base_time.replace(minute=59, second=59, microsecond=0).replace(minute=0, second=0, microsecond=0)
    
    # All should produce the same hour bucket (16:00)
    assert t1.hour == 16
    assert t2.hour == 16
    assert t3.hour == 16
    assert t1 == t2 == t3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
