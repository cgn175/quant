"""
CoinGecko news fetcher for crypto market sentiment.
Uses the free CoinGecko API (no authentication required).
"""

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from .base import BaseFetcher, Post

logger = logging.getLogger(__name__)


class CoinGeckoFetcher(BaseFetcher):
    """Fetch trending news and market sentiment from CoinGecko."""

    def __init__(self, api_key: str = ""):
        """Initialize CoinGecko fetcher.

        Args:
            api_key: Optional API key for higher rate limits (not required for free tier)
        """
        self.base_url = "https://api.coingecko.com/api/v3"
        self.api_key = api_key
        self.timeout = httpx.Timeout(10.0)

    def _fetch_sync(self, symbol: str, limit: int = 100) -> list[Post]:
        """Synchronous fetch of trending coins and news from CoinGecko."""
        posts = []

        try:
            with httpx.Client(timeout=self.timeout) as client:
                # Map trading symbols to CoinGecko IDs
                coin_ids = self._get_coin_ids(symbol)

                for coin_id in coin_ids:
                    # Fetch market data + sentiment
                    market_url = f"{self.base_url}/coins/{coin_id}"
                    params = {
                        "localization": False,
                        "market_data": True,
                        "community_data": True,
                    }

                    if self.api_key:
                        params["x_cg_pro_api_key"] = self.api_key

                    response = client.get(market_url, params=params)
                    if response.status_code == 429:
                        logger.warning(
                            "CoinGecko rate limit hit; consider adding SENTIMENT_COINGECKO_API_KEY for higher limits"
                        )
                        continue
                    response.raise_for_status()
                    data = response.json()

                    # Extract sentiment-related data
                    if data.get("community_data"):
                        sentiment_text = self._extract_sentiment(data, coin_id)
                        if sentiment_text:
                            posts.append(
                                Post(
                                    text=sentiment_text,
                                    source="coingecko",
                                    symbol=symbol,
                                    timestamp=datetime.now(timezone.utc),
                                    score=0,
                                )
                            )

                    # Fetch trending coins to track mention velocity
                    if coin_id in ["bitcoin", "ethereum"]:
                        trending_url = f"{self.base_url}/search/trending"
                        trending_response = client.get(trending_url, params=params)
                        if trending_response.status_code == 429:
                            logger.warning(
                                "CoinGecko rate limit hit on trending endpoint; consider adding SENTIMENT_COINGECKO_API_KEY"
                            )
                            continue
                        if trending_response.status_code == 200:
                            trending_data = trending_response.json()
                            if self._is_in_trending(trending_data, coin_id):
                                posts.append(
                                    Post(
                                        text=f"{coin_id.capitalize()} is in CoinGecko trending coins",
                                        source="coingecko_trending",
                                        symbol=symbol,
                                        timestamp=datetime.now(timezone.utc),
                                        score=1,
                                    )
                                )

        except Exception as e:
            # Silently fail - other fetchers will still work
            pass

        return posts

    async def fetch(self, symbol: str, limit: int = 100) -> list[Post]:
        """Async wrapper for CoinGecko fetch."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_sync, symbol, limit)

    def _get_coin_ids(self, symbol: str) -> list[str]:
        """Map trading symbol to CoinGecko coin IDs."""
        mapping = {
            "BTCUSDT": ["bitcoin"],
            "ETHUSDT": ["ethereum"],
            "SOLUSDT": ["solana"],
            "BNBUSDT": ["binancecoin"],
        }
        return mapping.get(symbol, [])

    def _extract_sentiment(self, data: dict, coin_id: str) -> str:
        """Extract sentiment indicators from CoinGecko market data."""
        parts = []

        # Price change indicators
        market_data = data.get("market_data", {})
        if market_data.get("price_change_percentage_24h"):
            change = market_data["price_change_percentage_24h"]
            parts.append(f"{coin_id} 24h change: {change:.2f}%")

        # Sentiment votes
        if data.get("sentiment_votes_up_percentage"):
            sentiment = data["sentiment_votes_up_percentage"]
            parts.append(f"{coin_id} sentiment {sentiment:.1f}% bullish")

        # Community metrics
        community = data.get("community_data", {})
        if community.get("twitter_followers"):
            parts.append(
                f"{coin_id} has {community['twitter_followers']} Twitter followers"
            )

        return " | ".join(parts) if parts else None

    def _is_in_trending(self, trending_data: dict, coin_id: str) -> bool:
        """Check if coin is in CoinGecko trending list."""
        coins = trending_data.get("coins", [])
        return any(c.get("item", {}).get("id") == coin_id for c in coins)
