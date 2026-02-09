"""
Twitter/X news fetcher for crypto sentiment analysis.
Uses the Tweepy library to fetch tweets about crypto.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from .base import BaseFetcher, Post


class TwitterFetcher(BaseFetcher):
    """Fetch crypto sentiment from Twitter/X using v2 API."""

    def __init__(self, bearer_token: str = ""):
        """Initialize Twitter fetcher.

        Args:
            bearer_token: Twitter API v2 bearer token (requires paid tier)
        """
        self.bearer_token = bearer_token
        self.base_url = "https://api.twitter.com/2"
        self.timeout = httpx.Timeout(10.0)

    def _fetch_sync(self, symbol: str, limit: int = 100) -> list[Post]:
        """Synchronous fetch of tweets about crypto."""
        if not self.bearer_token:
            return []

        posts = []
        keywords = self._get_keywords(symbol)

        try:
            with httpx.Client(timeout=self.timeout) as client:
                headers = {"Authorization": f"Bearer {self.bearer_token}"}

                for keyword in keywords:
                    # Search tweets from last 7 days
                    params = {
                        "query": keyword,
                        "max_results": min(100, limit),
                        "tweet.fields": "created_at,public_metrics,lang",
                        "expansions": "author_id",
                        "user.fields": "username,verified",
                    }

                    response = client.get(
                        f"{self.base_url}/tweets/search/recent",
                        params=params,
                        headers=headers,
                    )

                    if response.status_code != 200:
                        continue

                    data = response.json()

                    for tweet in data.get("data", []):
                        # Only English tweets
                        if tweet.get("lang") and tweet["lang"] != "en":
                            continue

                        created_at = datetime.fromisoformat(
                            tweet["created_at"].replace("Z", "+00:00")
                        )

                        # Only recent tweets (last 24 hours)
                        if (
                            datetime.now(timezone.utc) - created_at
                        ).total_seconds() > 86400:
                            continue

                        metrics = tweet.get("public_metrics", {})
                        engagement_score = (
                            metrics.get("like_count", 0)
                            + metrics.get("retweet_count", 0) * 2
                            + metrics.get("reply_count", 0)
                        )

                        posts.append(
                            Post(
                                text=tweet.get("text", "")[:1000],
                                source="twitter",
                                symbol=symbol,
                                timestamp=created_at,
                                score=max(0, engagement_score),
                            )
                        )

        except Exception as e:
            # Silently fail
            pass

        return posts

    async def fetch(self, symbol: str, limit: int = 100) -> list[Post]:
        """Async wrapper for Twitter fetch."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_sync, symbol, limit)

    def _get_keywords(self, symbol: str) -> list[str]:
        """Generate search keywords for symbol."""
        mapping = {
            "BTCUSDT": ["bitcoin lang:en -is:retweet", "$BTC lang:en -is:retweet"],
            "ETHUSDT": ["ethereum lang:en -is:retweet", "$ETH lang:en -is:retweet"],
            "SOLUSDT": ["solana lang:en -is:retweet", "$SOL lang:en -is:retweet"],
            "BNBUSDT": ["binance lang:en -is:retweet", "$BNB lang:en -is:retweet"],
        }
        return mapping.get(symbol, [])
