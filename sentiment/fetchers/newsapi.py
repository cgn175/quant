"""
NewsAPI fetcher for general crypto and finance news.
Uses NewsAPI.org to fetch breaking news about crypto markets.
"""

import asyncio
from datetime import datetime, timezone

import httpx

from .base import BaseFetcher, Post


class NewsAPIFetcher(BaseFetcher):
    """Fetch crypto news from NewsAPI.org."""

    def __init__(self, api_key: str = ""):
        """Initialize NewsAPI fetcher.

        Args:
            api_key: NewsAPI.org API key (free tier available)
        """
        self.api_key = api_key
        self.base_url = "https://newsapi.org/v2"
        self.timeout = httpx.Timeout(10.0)

    def _fetch_sync(self, symbol: str, limit: int = 100) -> list[Post]:
        """Synchronous fetch of news from NewsAPI."""
        if not self.api_key:
            return []

        posts = []
        keywords = self._get_keywords(symbol)

        try:
            with httpx.Client(timeout=self.timeout) as client:
                for keyword in keywords:
                    params = {
                        "q": keyword,
                        "apiKey": self.api_key,
                        "sortBy": "publishedAt",
                        "language": "en",
                        "pageSize": min(100, limit),
                    }

                    response = client.get(f"{self.base_url}/everything", params=params)
                    response.raise_for_status()
                    data = response.json()

                    for article in data.get("articles", []):
                        published_at = datetime.fromisoformat(
                            article["publishedAt"].replace("Z", "+00:00")
                        )

                        title = article.get("title", "")
                        description = article.get("description", "")
                        text = f"{title}. {description}" if description else title

                        # Simple source authority scoring
                        source_name = article.get("source", {}).get("name", "")
                        is_major = any(
                            major in source_name
                            for major in [
                                "Reuters",
                                "Bloomberg",
                                "CNBC",
                                "CoinDesk",
                                "The Block",
                            ]
                        )
                        score = 1 if is_major else 0

                        posts.append(
                            Post(
                                text=text[:1000],
                                source="newsapi",
                                symbol=symbol,
                                timestamp=published_at,
                                score=score,
                            )
                        )

        except Exception as e:
            # Silently fail
            pass

        return posts

    async def fetch(self, symbol: str, limit: int = 100) -> list[Post]:
        """Async wrapper for NewsAPI fetch."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_sync, symbol, limit)

    def _get_keywords(self, symbol: str) -> list[str]:
        """Generate search keywords for symbol."""
        from .base import extract_base_token
        base_token = extract_base_token(symbol)
        
        mapping = {
            "BTC": ["bitcoin crypto", "bitcoin news"],
            "ETH": ["ethereum crypto", "ethereum news"],
            "SOL": ["solana crypto", "solana news"],
            "BNB": ["binance crypto", "bnb news"],
        }
        
        if base_token in mapping:
            return mapping[base_token]
        
        # Default: search for the token name
        return [f"{base_token.lower()} crypto"]
