"""Financial Modeling Prep (FMP) fetcher for crypto and stock news."""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiohttp

from .base import BaseFetcher, Post


class FMPFetcher(BaseFetcher):
    """Fetch news from Financial Modeling Prep API.
    
    Features: Crypto news, stock news, pagination support, sentiment indicators
    """

    BASE_URL = "https://financialmodelingprep.com/api/v3"

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
            limit: Maximum number of articles to fetch (API supports pagination)
            
        Returns:
            List of Post objects from news articles
        """
        if not self.api_key:
            return []

        # Convert BTCUSDT -> BTC for search
        base_symbol = symbol.replace("USDT", "").replace("BUSD", "").replace("USD", "")

        try:
            session = await self._get_session()
            
            # Fetch crypto news
            params = {
                "apikey": self.api_key,
                "limit": min(limit, 100),  # Reasonable limit per request
            }

            async with session.get(
                f"{self.BASE_URL}/crypto_news",
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

                for article in articles:
                    # Parse published date
                    published_str = article.get("publishedDate", "")
                    try:
                        # FMP format: "2024-02-09 14:30:00"
                        published_at = datetime.strptime(
                            published_str, "%Y-%m-%d %H:%M:%S"
                        ).replace(tzinfo=timezone.utc)
                    except (ValueError, AttributeError):
                        published_at = now

                    # Skip old articles
                    if published_at < cutoff:
                        continue

                    title = article.get("title", "")
                    text_content = article.get("text", "")
                    
                    # Combine title and text
                    text = f"{title}. {text_content}".strip()
                    if not text:
                        continue

                    # Check relevance to symbol
                    symbol_field = article.get("symbol", "")
                    tickers = article.get("tickers", "")
                    
                    # Must be relevant to our cryptocurrency
                    is_relevant = (
                        base_symbol.upper() in symbol_field.upper() or
                        base_symbol.upper() in tickers.upper() or
                        base_symbol.lower() in text.lower()
                    )
                    
                    if not is_relevant:
                        continue

                    # FMP provides sentiment field in some endpoints
                    sentiment = article.get("sentiment", "neutral").lower()
                    if sentiment == "positive" or sentiment == "bullish":
                        score = 70
                    elif sentiment == "negative" or sentiment == "bearish":
                        score = 30
                    else:
                        score = 50  # Neutral

                    # Site authority bonus (if from major outlet)
                    site = article.get("site", "").lower()
                    if any(source in site for source in ["bloomberg", "reuters", "coindesk", "cointelegraph"]):
                        score += 20

                    posts.append(Post(
                        text=text,
                        source="fmp",
                        symbol=symbol,
                        timestamp=published_at,
                        score=min(score, 100),  # Cap at 100
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
