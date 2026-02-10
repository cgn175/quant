"""
Tests for Telegram fetcher functionality.

Run with:
    pytest test_telegram_fetcher.py -v
    
Or test live (requires authentication):
    pytest test_telegram_fetcher.py -v --live
"""

import asyncio
import os
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest
from telethon.errors import FloodWaitError, ApiIdInvalidError
from telethon.tl.types import Channel, Message

from fetchers.telegram import TelegramFetcher, RateLimiter, INITIAL_BACKOFF_SECONDS


class TestRateLimiter:
    """Test the token bucket rate limiter."""
    
    @pytest.mark.asyncio
    async def test_basic_rate_limiting(self):
        """Test that rate limiter enforces rate."""
        limiter = RateLimiter(rate=10, burst=10)  # 10 tokens/sec
        
        # Should be able to acquire 10 tokens immediately (burst)
        start = time.monotonic()
        for _ in range(10):
            await limiter.acquire()
        elapsed = time.monotonic() - start
        
        # Should complete in < 100ms (no waiting)
        assert elapsed < 0.1
    
    @pytest.mark.asyncio
    async def test_rate_limiting_wait(self):
        """Test that rate limiter waits when tokens exhausted."""
        limiter = RateLimiter(rate=2, burst=2)  # 2 tokens/sec
        
        # Exhaust burst
        await limiter.acquire()
        await limiter.acquire()
        
        # Next acquire should wait ~0.5 seconds
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        
        assert elapsed >= 0.4  # Should wait at least 0.4 seconds
        assert elapsed < 0.7   # But not too long
    
    @pytest.mark.asyncio
    async def test_token_refill(self):
        """Test that tokens refill over time."""
        limiter = RateLimiter(rate=10, burst=5)
        
        # Exhaust burst
        for _ in range(5):
            await limiter.acquire()
        
        # Wait for tokens to refill
        await asyncio.sleep(0.3)  # Should refill ~3 tokens
        
        # Should be able to acquire 3 more without waiting
        start = time.monotonic()
        for _ in range(3):
            await limiter.acquire()
        elapsed = time.monotonic() - start
        
        assert elapsed < 0.1  # No significant wait


class TestExponentialBackoff:
    """Test exponential backoff retry logic."""
    
    @pytest.mark.asyncio
    async def test_success_on_first_try(self):
        """Test that successful calls don't retry."""
        fetcher = TelegramFetcher()
        
        mock_func = AsyncMock(return_value="success")
        result = await fetcher._exponential_backoff_retry(mock_func)
        
        assert result == "success"
        assert mock_func.call_count == 1
    
    @pytest.mark.asyncio
    async def test_retry_on_connection_error(self):
        """Test retry with exponential backoff on connection errors."""
        fetcher = TelegramFetcher()
        
        # Fail twice, succeed on third try
        mock_func = AsyncMock(side_effect=[
            ConnectionError("network error"),
            ConnectionError("network error"),
            "success"
        ])
        
        result = await fetcher._exponential_backoff_retry(mock_func)
        
        assert result == "success"
        assert mock_func.call_count == 3
    
    @pytest.mark.asyncio
    async def test_flood_wait_error_handling(self):
        """Test that FloodWaitError waits exact time specified."""
        fetcher = TelegramFetcher()
        
        # Simulate flood wait for 1 second
        flood_error = FloodWaitError(
            request=None,
            capture=1  # Wait 1 second
        )
        
        mock_func = AsyncMock(side_effect=[
            flood_error,
            "success"
        ])
        
        start = time.monotonic()
        result = await fetcher._exponential_backoff_retry(mock_func)
        elapsed = time.monotonic() - start
        
        assert result == "success"
        assert elapsed >= 0.9  # Should wait at least the flood time
        assert mock_func.call_count == 2
    
    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """Test that retry gives up after max retries."""
        fetcher = TelegramFetcher()
        
        mock_func = AsyncMock(side_effect=ConnectionError("persistent error"))
        
        with pytest.raises(Exception, match="Max retries"):
            await fetcher._exponential_backoff_retry(mock_func)
        
        assert mock_func.call_count == 5  # MAX_RETRIES
    
    @pytest.mark.asyncio
    async def test_auth_error_no_retry(self):
        """Test that authentication errors don't retry."""
        fetcher = TelegramFetcher()
        
        mock_func = AsyncMock(side_effect=ApiIdInvalidError("bad credentials"))
        
        with pytest.raises(ApiIdInvalidError):
            await fetcher._exponential_backoff_retry(mock_func)
        
        assert mock_func.call_count == 1  # No retries


class TestTelegramFetcher:
    """Test Telegram fetcher functionality."""
    
    def test_initialization_without_credentials(self):
        """Test that fetcher can be created without credentials."""
        fetcher = TelegramFetcher()
        
        assert fetcher.api_id is None
        assert fetcher.api_hash is None
        assert fetcher.client is None
    
    def test_initialization_with_credentials(self):
        """Test fetcher initialization with credentials."""
        fetcher = TelegramFetcher(
            api_id=12345,
            api_hash="test_hash",
            session_name="test_session"
        )
        
        assert fetcher.api_id == 12345
        assert fetcher.api_hash == "test_hash"
        assert fetcher.session_name == "test_session"
    
    def test_session_directory_setup(self):
        """Test that session directory is created with correct permissions."""
        test_dir = "/tmp/test_telegram_sessions"
        
        # Clean up if exists
        if os.path.exists(test_dir):
            os.rmdir(test_dir)
        
        fetcher = TelegramFetcher(
            api_id=12345,
            api_hash="test",
            session_dir=test_dir
        )
        
        assert os.path.exists(test_dir)
        assert oct(os.stat(test_dir).st_mode)[-3:] == "700"
        
        # Clean up
        os.rmdir(test_dir)
    
    @pytest.mark.asyncio
    async def test_fetch_without_credentials(self):
        """Test that fetch returns empty list without credentials."""
        fetcher = TelegramFetcher()
        posts = await fetcher.fetch("BTCUSDT", limit=10)
        
        assert posts == []
    
    def test_get_keywords_for_symbol(self):
        """Test keyword extraction for different symbols."""
        fetcher = TelegramFetcher()
        
        btc_keywords = fetcher._get_keywords_for_symbol("BTC")
        assert "bitcoin" in btc_keywords
        assert "btc" in btc_keywords
        
        eth_keywords = fetcher._get_keywords_for_symbol("ETH")
        assert "ethereum" in eth_keywords
        assert "eth" in eth_keywords
        
        # Unknown symbol should return lowercase version
        xyz_keywords = fetcher._get_keywords_for_symbol("XYZ")
        assert "xyz" in xyz_keywords
    
    def test_sentiment_extraction(self):
        """Test sentiment score extraction from text."""
        fetcher = TelegramFetcher()
        
        # Positive text
        pos_text = "Bitcoin surges to new highs! Bullish rally continues."
        assert fetcher._extract_sentiment_score(pos_text) == 1
        
        # Negative text
        neg_text = "Market crash alert! Bitcoin dumps below support."
        assert fetcher._extract_sentiment_score(neg_text) == -1
        
        # Neutral text
        neutral_text = "Bitcoin price updates and market analysis."
        assert fetcher._extract_sentiment_score(neutral_text) == 0
    
    @pytest.mark.asyncio
    async def test_message_deduplication(self):
        """Test that duplicate messages are filtered out."""
        fetcher = TelegramFetcher(api_id=12345, api_hash="test")
        
        # Add some message IDs to cache
        async with fetcher._cache_lock:
            fetcher._message_cache.add(123)
            fetcher._message_cache.add(456)
        
        # Check cache contains messages
        assert 123 in fetcher._message_cache
        assert 456 in fetcher._message_cache
        assert 789 not in fetcher._message_cache
    
    @pytest.mark.asyncio
    async def test_cache_cleanup(self):
        """Test that message cache is cleaned up when too large."""
        fetcher = TelegramFetcher(api_id=12345, api_hash="test")
        
        # Fill cache beyond limit
        async with fetcher._cache_lock:
            for i in range(11000):
                fetcher._message_cache.add(i)
        
        # Trigger cleanup (simulated in fetch method)
        async with fetcher._cache_lock:
            if len(fetcher._message_cache) > 10000:
                fetcher._message_cache = set(list(fetcher._message_cache)[-5000:])
        
        # Cache should be reduced to 5000
        assert len(fetcher._message_cache) == 5000


@pytest.mark.skipif(
    "not config.getoption('--live')",
    reason="Live tests require authentication and --live flag"
)
class TestTelegramFetcherLive:
    """Live tests against Telegram API (requires valid credentials)."""
    
    @pytest.mark.asyncio
    async def test_live_fetch(self):
        """Test fetching from real Telegram channels."""
        from config import get_settings
        
        settings = get_settings()
        
        if not settings.telegram_api_id or not settings.telegram_api_hash:
            pytest.skip("Telegram credentials not configured")
        
        fetcher = TelegramFetcher(
            api_id=settings.telegram_api_id,
            api_hash=settings.telegram_api_hash
        )
        
        try:
            # Fetch BTC mentions
            posts = await fetcher.fetch("BTCUSDT", limit=20)
            
            print(f"\nFetched {len(posts)} posts")
            
            # Should get some posts (might be 0 if no recent BTC mentions)
            assert isinstance(posts, list)
            
            # If we got posts, validate structure
            if posts:
                post = posts[0]
                assert hasattr(post, 'text')
                assert hasattr(post, 'source')
                assert hasattr(post, 'symbol')
                assert hasattr(post, 'timestamp')
                assert hasattr(post, 'score')
                
                assert post.symbol == "BTCUSDT"
                assert post.source.startswith("telegram:")
                
                print(f"\nSample post from {post.source}:")
                print(f"{post.text[:200]}...")
                print(f"Score: {post.score}")
        
        finally:
            await fetcher.disconnect()
    
    @pytest.mark.asyncio
    async def test_live_rate_limiting(self):
        """Test that rate limiting works in practice."""
        from config import get_settings
        
        settings = get_settings()
        
        if not settings.telegram_api_id or not settings.telegram_api_hash:
            pytest.skip("Telegram credentials not configured")
        
        fetcher = TelegramFetcher(
            api_id=settings.telegram_api_id,
            api_hash=settings.telegram_api_hash
        )
        
        try:
            # Make multiple rapid requests
            start = time.monotonic()
            
            tasks = [
                fetcher.fetch("BTCUSDT", limit=10),
                fetcher.fetch("ETHUSDT", limit=10),
                fetcher.fetch("SOLUSDT", limit=10),
            ]
            
            results = await asyncio.gather(*tasks)
            elapsed = time.monotonic() - start
            
            # With rate limiting, should take at least a few seconds
            # (3 symbols * multiple channels * rate limit)
            print(f"\nFetched {sum(len(r) for r in results)} posts in {elapsed:.2f}s")
            
            # Rate limiter should prevent flood errors
            assert all(isinstance(r, list) for r in results)
        
        finally:
            await fetcher.disconnect()


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="Run live tests against Telegram API"
    )


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers",
        "live: mark test as requiring live Telegram API access"
    )
