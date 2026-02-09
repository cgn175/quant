"""Finnhub fetcher for market and crypto news."""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiohttp

from .base import BaseFetcher, Post


class FinnhubFetcher(BaseFetcher):
    """Fetch news from Finnhub API.
    
    Free tier: Real-time data with generous limits
    Provides general market news, company news, and crypto-specific news
    """

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def fetch(self, symbol: str, limit: int = 100) -> list[Post]:
        """Fetch crypto news for a symbol.
        
        Args:
            symbol: Trading symbol (e.g., BTCUSDT)
            limit: Maximum number of articles to fetch
            
        Returns:
            List of Post objects from news articles
        """
        if not self.api_key:
            return []

        # Convert BTCUSDT -> BTC
        base_symbol = symbol.replace("USDT", "").replace("BUSD", "").replace("USD", "")

        try:
            session = await self._get_session()
            
            # Fetch crypto-specific news
            # Finnhub uses category=crypto for cryptocurrency news
            params = {
                "token": self.api_key,
                "category": "crypto",
            }

            async with session.get(
                f"{self.BASE_URL}/news",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    return []

                articles = await response.json()
                
                if not isinstance(articles, list):
                    return []

                posts = []
                now = datetime.now(timezone.utc)
                cutoff = now - timedelta(hours=48)

                for article in articles[:limit]:
                    # Parse timestamp (Finnhub returns Unix timestamp)
                    timestamp = article.get("datetime", 0)
                    try:
                        published_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                    except (ValueError, OSError):
                        published_at = now

                    # Skip old articles
                    if published_at < cutoff:
                        continue

                    headline = article.get("headline", "")
                    summary = article.get("summary", "")
                    
                    # Check if article is relevant to our symbol
                    text = f"{headline}. {summary}".strip()
                    if not text:
                        continue

                    # Simple relevance check - article must mention the symbol
                    if base_symbol.lower() not in text.lower():
                        continue

                    # Finnhub doesn't provide sentiment, so we use neutral scoring
                    # FinBERT will analyze the actual text
                    score = 10  # Base score for relevant news

                    # Related symbols indicate higher relevance
                    related = article.get("related", "")
                    if base_symbol in related:
                        score = 50

                    posts.append(Post(
                        text=text,
                        source="finnhub",
                        symbol=symbol,
                        timestamp=published_at,
                        score=score,
                    ))

                return posts

        except asyncio.TimeoutError:
            return []
        except Exception:
            return []

    async def close(self):
        """Close the aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()

    def __del__(self):
        """Cleanup on deletion."""
        if self.session and not self.session.closed:
            try:
                asyncio.get_event_loop().create_task(self.close())
            except RuntimeError:
                pass
