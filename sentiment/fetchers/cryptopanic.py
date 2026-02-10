"""
CryptoPanic news fetcher for crypto market sentiment.
Fetches news from CryptoPanic API (free tier available).
"""

import asyncio
from datetime import datetime, timezone

import httpx

from .base import BaseFetcher, Post


class CryptopanicFetcher(BaseFetcher):
    """Fetch crypto news from CryptoPanic."""

    def __init__(self, api_key: str = ""):
        """Initialize CryptoPanic fetcher.

        Args:
            api_key: CryptoPanic API key (free tier available)
        """
        self.api_key = api_key
        self.base_url = "https://cryptopanic.com/api/free/v1"
        self.timeout = httpx.Timeout(10.0)

    def _fetch_sync(self, symbol: str, limit: int = 100) -> list[Post]:
        """Synchronous fetch of news from CryptoPanic."""
        if not self.api_key:
            return []

        posts = []
        currencies = self._get_currency_codes(symbol)

        try:
            with httpx.Client(timeout=self.timeout) as client:
                # Build single request with comma-separated currencies
                params = {
                    "auth_token": self.api_key,
                    "currencies": ",".join(currencies),  # CryptoPanic accepts comma-separated values
                    "filter": "news",  # Use 'filter' not 'kind'
                }

                response = client.get(f"{self.base_url}/posts/", params=params)
                response.raise_for_status()
                data = response.json()

                for item in data.get("results", []):
                    # Only include recent news (last 48 hours)
                    posted_at = datetime.fromisoformat(
                        item["published_at"].replace("Z", "+00:00")
                    )
                    if (
                        datetime.now(timezone.utc) - posted_at
                    ).total_seconds() > 172800:
                        continue

                    title = item.get("title", "")
                    summary = item.get("summary", "")
                    text = f"{title}. {summary}" if summary else title

                    # Extract sentiment from title/summary
                    sentiment_score = self._extract_sentiment(text)

                    posts.append(
                        Post(
                            text=text[:1000],
                            source="cryptopanic",
                            symbol=symbol,
                            timestamp=posted_at,
                            score=sentiment_score,
                        )
                    )

        except Exception as e:
            # Silently fail
            pass

        return posts

    async def fetch(self, symbol: str, limit: int = 100) -> list[Post]:
        """Async wrapper for CryptoPanic fetch."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_sync, symbol, limit)

    def _get_currency_codes(self, symbol: str) -> list[str]:
        """Map trading symbol to CryptoPanic currency codes."""
        from .base import extract_base_token
        base_token = extract_base_token(symbol)
        mapping = {
            "BTC": ["BTC"],
            "ETH": ["ETH"],
            "SOL": ["SOL"],
            "BNB": ["BNB"],
        }
        return mapping.get(base_token, [base_token])

    def _extract_sentiment(self, text: str) -> int:
        """Simple sentiment extraction from news title/summary."""
        text_lower = text.lower()

        positive_words = [
            "surge",
            "rally",
            "bull",
            "gain",
            "profit",
            "up",
            "rise",
            "bullish",
            "strong",
            "growth",
            "pump",
            "moon",
            "surge",
        ]
        negative_words = [
            "crash",
            "dump",
            "bear",
            "loss",
            "down",
            "fall",
            "bearish",
            "weak",
            "decline",
            "risk",
            "concern",
            "drop",
        ]

        positive_count = sum(1 for word in positive_words if word in text_lower)
        negative_count = sum(1 for word in negative_words if word in text_lower)

        if positive_count > negative_count:
            return 1
        elif negative_count > positive_count:
            return -1
        return 0
