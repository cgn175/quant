"""CoinMarketCap fetcher for crypto market data and sentiment."""

import asyncio
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from .base import BaseFetcher, Post


class CoinMarketCapFetcher(BaseFetcher):
    """Fetch crypto market data from CoinMarketCap API.
    
    Free tier: 10,000 calls/month, 10 calls/second
    Provides price data, market cap, volume, and percent changes.
    """

    BASE_URL = "https://pro-api.coinmarketcap.com/v1"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def fetch(self, symbol: str, limit: int = 100) -> list[Post]:
        """Fetch latest market data for a symbol.
        
        Args:
            symbol: Trading symbol (e.g., BTCUSDT)
            limit: Not used for this API (always returns latest data)
            
        Returns:
            List of Post objects with market sentiment derived from price changes
        """
        if not self.api_key:
            return []

        # Convert BTCUSDT -> BTC
        base_symbol = symbol.replace("USDT", "").replace("BUSD", "").replace("USD", "")

        try:
            session = await self._get_session()
            headers = {
                "X-CMC_PRO_API_KEY": self.api_key,
                "Accept": "application/json"
            }

            async with session.get(
                f"{self.BASE_URL}/cryptocurrency/quotes/latest",
                params={"symbol": base_symbol},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    return []

                data = await response.json()
                
                if "data" not in data or base_symbol not in data["data"]:
                    return []

                coin_data = data["data"][base_symbol]
                quote = coin_data.get("quote", {}).get("USD", {})

                # Extract market data
                price = quote.get("price", 0)
                percent_change_1h = quote.get("percent_change_1h", 0)
                percent_change_24h = quote.get("percent_change_24h", 0)
                percent_change_7d = quote.get("percent_change_7d", 0)
                volume_24h = quote.get("volume_24h", 0)
                market_cap = quote.get("market_cap", 0)

                posts = []
                now = datetime.now(timezone.utc)

                # Create sentiment post based on price action
                # Strong movements generate more confident sentiment
                if abs(percent_change_1h) > 2:
                    direction = "surging" if percent_change_1h > 0 else "plunging"
                    text = (
                        f"{base_symbol} {direction} {abs(percent_change_1h):.2f}% in the last hour. "
                        f"24h change: {percent_change_24h:.2f}%, 7d: {percent_change_7d:.2f}%. "
                        f"Current price: ${price:.2f}, Market cap: ${market_cap/1e9:.2f}B"
                    )
                    score = int(abs(percent_change_1h) * 10)  # Weight by magnitude
                    posts.append(Post(
                        text=text,
                        source="coinmarketcap",
                        symbol=symbol,
                        timestamp=now,
                        score=score,
                    ))

                # 24h trend sentiment
                if abs(percent_change_24h) > 5:
                    trend = "bullish rally" if percent_change_24h > 0 else "bearish decline"
                    text = (
                        f"{base_symbol} showing {trend} with {abs(percent_change_24h):.2f}% change over 24 hours. "
                        f"Trading volume: ${volume_24h/1e9:.2f}B"
                    )
                    score = int(abs(percent_change_24h) * 5)
                    posts.append(Post(
                        text=text,
                        source="coinmarketcap",
                        symbol=symbol,
                        timestamp=now,
                        score=score,
                    ))

                # Weekly trend
                if abs(percent_change_7d) > 10:
                    movement = "strong uptrend" if percent_change_7d > 0 else "significant downtrend"
                    text = (
                        f"{base_symbol} in {movement} with {abs(percent_change_7d):.2f}% weekly change. "
                        f"Market sentiment shifting based on price action."
                    )
                    score = int(abs(percent_change_7d) * 3)
                    posts.append(Post(
                        text=text,
                        source="coinmarketcap",
                        symbol=symbol,
                        timestamp=now,
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
