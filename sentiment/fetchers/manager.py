"""
Fetcher Manager - Unified interface for general market fetching.

This module provides a high-level interface that:
1. Fetches general crypto news from all available sources (once per cycle)
2. Categorizes posts by symbol using NLP/keyword matching
3. Caches results to reduce API calls
4. Handles rate limiting and error recovery
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .base import Post
from .categorizer import categorize_posts, deduplicate_posts


logger = logging.getLogger(__name__)


class FetcherManager:
    """
    Manages all news fetchers with unified general market fetching.
    
    Instead of fetching per-symbol (4 symbols x 10 fetchers = 40 API calls),
    this manager fetches general crypto news once and categorizes it
    (10 fetchers = 10 API calls total).
    """
    
    def __init__(
        self,
        fetchers: Dict[str, any],
        cache_ttl_seconds: int = 300,  # 5 minute cache
        target_symbols: List[str] = None
    ):
        """
        Initialize fetcher manager.
        
        Args:
            fetchers: Dictionary mapping fetcher names to fetcher instances
            cache_ttl_seconds: How long to cache general market news
            target_symbols: List of trading symbols to categorize into
        """
        self.fetchers = fetchers
        self.cache_ttl_seconds = cache_ttl_seconds
        self.target_symbols = target_symbols or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
        
        # Cache for general market posts
        self._general_posts_cache: List[Post] = []
        self._cache_timestamp: Optional[datetime] = None
        self._cache_lock = asyncio.Lock()
        
        # Cache for categorized posts by symbol
        self._categorized_cache: Dict[str, List[Post]] = {}
        
    async def fetch_general_news(self, limit_per_source: int = 100) -> List[Post]:
        """
        Fetch general crypto news from all available sources.
        
        This method fetches news once and caches it for cache_ttl_seconds.
        
        Args:
            limit_per_source: Maximum posts to fetch per source
            
        Returns:
            List of all posts from all sources (not categorized by symbol)
        """
        async with self._cache_lock:
            # Check cache validity
            if self._cache_timestamp:
                cache_age = datetime.now(timezone.utc) - self._cache_timestamp
                if cache_age < timedelta(seconds=self.cache_ttl_seconds):
                    logger.info(
                        f"Returning cached general news ({len(self._general_posts_cache)} posts, "
                        f"age: {cache_age.total_seconds():.1f}s)"
                    )
                    return self._general_posts_cache
            
            logger.info("General news cache expired, fetching from all sources...")
            
            # Fetch from all sources in parallel
            fetch_tasks = []
            
            # Use market.py functions for sources that have them
            from . import market
            
            if "telegram" in self.fetchers:
                logger.info("Fetching general news from Telegram...")
                fetch_tasks.append(
                    self._safe_fetch(
                        market.fetch_market_telegram(self.fetchers["telegram"], limit=limit_per_source),
                        "telegram"
                    )
                )
            
            if "cryptopanic" in self.fetchers:
                logger.info("Fetching general news from CryptoPanic...")
                fetch_tasks.append(
                    self._safe_fetch(
                        market.fetch_market_cryptopanic(self.fetchers["cryptopanic"], limit=limit_per_source),
                        "cryptopanic"
                    )
                )
            
            if "newsapi" in self.fetchers:
                logger.info("Fetching general news from NewsAPI...")
                fetch_tasks.append(
                    self._safe_fetch(
                        market.fetch_market_newsapi(self.fetchers["newsapi"], limit=limit_per_source),
                        "newsapi"
                    )
                )
            
            if "reddit" in self.fetchers:
                logger.info("Fetching general news from Reddit...")
                fetch_tasks.append(
                    self._safe_fetch(
                        market.fetch_market_reddit(self.fetchers["reddit"], limit=limit_per_source),
                        "reddit"
                    )
                )
            
            # For other fetchers, create general market fetch functions
            # These fetchers will fetch crypto news without symbol filtering
            
            if "coingecko" in self.fetchers:
                logger.info("Fetching general news from CoinGecko...")
                fetch_tasks.append(
                    self._safe_fetch(
                        self._fetch_coingecko_general(limit_per_source),
                        "coingecko"
                    )
                )
            
            if "coinmarketcap" in self.fetchers:
                logger.info("Fetching general news from CoinMarketCap...")
                fetch_tasks.append(
                    self._safe_fetch(
                        self._fetch_coinmarketcap_general(limit_per_source),
                        "coinmarketcap"
                    )
                )
            
            if "marketaux" in self.fetchers:
                logger.info("Fetching general news from Marketaux...")
                fetch_tasks.append(
                    self._safe_fetch(
                        self._fetch_marketaux_general(limit_per_source),
                        "marketaux"
                    )
                )
            
            if "finnhub" in self.fetchers:
                logger.info("Fetching general news from Finnhub...")
                fetch_tasks.append(
                    self._safe_fetch(
                        self._fetch_finnhub_general(limit_per_source),
                        "finnhub"
                    )
                )
            
            if "fmp" in self.fetchers:
                logger.info("Fetching general news from FMP...")
                fetch_tasks.append(
                    self._safe_fetch(
                        self._fetch_fmp_general(limit_per_source),
                        "fmp"
                    )
                )
            
            if "twitter" in self.fetchers:
                logger.info("Fetching general news from Twitter...")
                fetch_tasks.append(
                    self._safe_fetch(
                        self._fetch_twitter_general(limit_per_source),
                        "twitter"
                    )
                )
            
            # Gather all results
            all_results = await asyncio.gather(*fetch_tasks)
            
            # Collect posts
            all_posts = []
            for result in all_results:
                if isinstance(result, list):
                    all_posts.extend(result)
            
            logger.info(f"Fetched {len(all_posts)} total posts from {len(fetch_tasks)} sources")
            
            # Deduplicate posts
            all_posts = deduplicate_posts(all_posts)
            logger.info(f"After deduplication: {len(all_posts)} unique posts")
            
            # Update cache
            self._general_posts_cache = all_posts
            self._cache_timestamp = datetime.now(timezone.utc)
            
            return all_posts
    
    async def fetch_for_symbol(self, symbol: str, limit: int = 100) -> List[Post]:
        """
        Fetch news relevant to a specific symbol.
        
        This method:
        1. Fetches general news (using cache if available)
        2. Categorizes posts by symbol
        3. Returns only posts relevant to the requested symbol
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            limit: Maximum posts to return (after categorization)
            
        Returns:
            List of posts relevant to the symbol
        """
        logger.info(f"Fetching news for {symbol}...")
        
        # Fetch general news (will use cache if fresh)
        general_posts = await self.fetch_general_news()
        
        # Categorize posts
        categorized = categorize_posts(general_posts, self.target_symbols)
        
        # Get posts for requested symbol
        symbol_posts = categorized.get(symbol, [])
        logger.info(f"Found {len(symbol_posts)} posts relevant to {symbol}")
        
        # Sort by timestamp (newest first) and limit
        symbol_posts.sort(key=lambda p: p.timestamp, reverse=True)
        return symbol_posts[:limit]
    
    async def fetch_market_sentiment(self) -> List[Post]:
        """
        Fetch general market sentiment posts (not symbol-specific).
        
        Returns:
            List of posts with symbol="MARKET"
        """
        logger.info("Fetching general market sentiment...")
        
        # Fetch general news
        general_posts = await self.fetch_general_news()
        
        # Categorize posts
        categorized = categorize_posts(general_posts, self.target_symbols)
        
        # Get market-wide posts
        market_posts = categorized.get("MARKET", [])
        logger.info(f"Found {len(market_posts)} general market posts")
        
        return market_posts
    
    async def _safe_fetch(self, coroutine, source_name: str) -> List[Post]:
        """
        Safely execute a fetch coroutine with error handling.
        
        Args:
            coroutine: Async function to execute
            source_name: Name of the source (for logging)
            
        Returns:
            List of posts, or empty list on error
        """
        try:
            result = await coroutine
            logger.info(f"{source_name}: Fetched {len(result) if result else 0} posts")
            return result if result else []
        except Exception as e:
            logger.error(f"{source_name}: Fetch failed with error: {e}", exc_info=True)
            return []
    
    # General fetch methods for fetchers without market.py functions
    
    async def _fetch_coingecko_general(self, limit: int) -> List[Post]:
        """Fetch general crypto trending data from CoinGecko."""
        fetcher = self.fetchers["coingecko"]
        posts = []
        
        # Fetch trending for major coins
        for symbol in self.target_symbols:
            try:
                symbol_posts = await fetcher.fetch(symbol, limit=10)
                posts.extend(symbol_posts)
            except Exception:
                continue
        
        return posts
    
    async def _fetch_coinmarketcap_general(self, limit: int) -> List[Post]:
        """Fetch market data from CoinMarketCap for all major coins."""
        fetcher = self.fetchers["coinmarketcap"]
        posts = []
        
        for symbol in self.target_symbols:
            try:
                symbol_posts = await fetcher.fetch(symbol, limit=10)
                posts.extend(symbol_posts)
            except Exception:
                continue
        
        return posts
    
    async def _fetch_marketaux_general(self, limit: int) -> List[Post]:
        """Fetch general crypto news from Marketaux."""
        fetcher = self.fetchers["marketaux"]
        posts = []
        
        # Marketaux supports multiple symbols in one request
        # Fetch for all major coins
        for symbol in self.target_symbols:
            try:
                symbol_posts = await fetcher.fetch(symbol, limit=25)
                posts.extend(symbol_posts)
            except Exception:
                continue
        
        return posts
    
    async def _fetch_finnhub_general(self, limit: int) -> List[Post]:
        """Fetch general crypto news from Finnhub."""
        fetcher = self.fetchers["finnhub"]
        
        # Finnhub crypto news endpoint returns all crypto news
        # Just fetch once with BTC as placeholder
        try:
            posts = await fetcher.fetch("BTCUSDT", limit=limit)
            return posts
        except Exception:
            return []
    
    async def _fetch_fmp_general(self, limit: int) -> List[Post]:
        """Fetch general crypto news from FMP."""
        fetcher = self.fetchers["fmp"]
        posts = []
        
        for symbol in self.target_symbols:
            try:
                symbol_posts = await fetcher.fetch(symbol, limit=25)
                posts.extend(symbol_posts)
            except Exception:
                continue
        
        return posts
    
    async def _fetch_twitter_general(self, limit: int) -> List[Post]:
        """Fetch general crypto tweets."""
        fetcher = self.fetchers["twitter"]
        posts = []
        
        for symbol in self.target_symbols:
            try:
                symbol_posts = await fetcher.fetch(symbol, limit=25)
                posts.extend(symbol_posts)
            except Exception:
                continue
        
        return posts
    
    def clear_cache(self):
        """Clear the cache to force fresh fetch on next request."""
        self._general_posts_cache = []
        self._cache_timestamp = None
        self._categorized_cache = {}
        logger.info("Cache cleared")
