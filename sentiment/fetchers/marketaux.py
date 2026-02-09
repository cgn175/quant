"""Marketaux fetcher for global finance news with sentiment analysis."""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiohttp

from .base import BaseFetcher, Post


class MarketauxFetcher(BaseFetcher):
    """Fetch finance news from Marketaux API.
    
    Free tier: 3,000 requests/month, 100 requests/day
    Features: 5,000+ sources, sentiment analysis, entity extraction
    """

    BASE_URL = "https://api.marketaux.com/v1"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def fetch(self, symbol: str, limit: int = 100) -> list[Post]:
        """Fetch news articles related to a symbol.
        
        Args:
            symbol: Trading symbol (e.g., BTCUSDT)
            limit: Maximum number of articles to fetch
            
        Returns:
            List of Post objects from news articles
        """
        if not self.api_key:
            return []

        # Convert BTCUSDT -> BTC for search
        base_symbol = symbol.replace("USDT", "").replace("BUSD", "").replace("USD", "")

        try:
            session = await self._get_session()
            
            # Search for news about the cryptocurrency
            params = {
                "api_token": self.api_key,
                "symbols": base_symbol,
                "filter_entities": "true",
                "language": "en",
                "limit": min(limit, 100),  # API max is 100
            }

            async with session.get(
                f"{self.BASE_URL}/news/all",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    return []

                data = await response.json()
                
                if "data" not in data:
                    return []

                posts = []
                now = datetime.now(timezone.utc)
                cutoff = now - timedelta(hours=48)

                for article in data["data"]:
                    # Parse published date
                    published_str = article.get("published_at", "")
                    try:
                        published_at = datetime.fromisoformat(
                            published_str.replace("Z", "+00:00")
                        )
                    except (ValueError, AttributeError):
                        published_at = now

                    # Skip old articles
                    if published_at < cutoff:
                        continue

                    title = article.get("title", "")
                    description = article.get("description", "")
                    
                    # Combine title and description for sentiment analysis
                    text = f"{title}. {description}".strip()
                    if not text:
                        continue

                    # Extract sentiment from API if available
                    entities = article.get("entities", [])
                    sentiment_score = 0
                    
                    # Marketaux provides sentiment in entities
                    for entity in entities:
                        if entity.get("symbol") == base_symbol:
                            sentiment = entity.get("sentiment_score")
                            if sentiment is not None:
                                try:
                                    sentiment_score = int(float(sentiment) * 100)
                                except (ValueError, TypeError):
                                    sentiment_score = 0
                            break

                    # If no explicit sentiment, use neutral score
                    if sentiment_score == 0:
                        sentiment_score = 50  # Neutral baseline

                    posts.append(Post(
                        text=text,
                        source="marketaux",
                        symbol=symbol,
                        timestamp=published_at,
                        score=sentiment_score,
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
