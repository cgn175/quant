from dataclasses import dataclass
from datetime import datetime
from abc import ABC, abstractmethod


@dataclass
class Post:
    text: str
    source: str
    symbol: str
    timestamp: datetime
    score: int = 0


def extract_base_token(symbol: str) -> str:
    """Extract base token from trading pair (e.g., BTCUSDT -> BTC)."""
    symbol = symbol.upper()
    # Remove common quote currencies
    for quote in ['USDT', 'USDC', 'USD', 'BTC', 'ETH', 'BUSD']:
        if symbol.endswith(quote) and symbol != quote:
            return symbol[:-len(quote)]
    return symbol


class BaseFetcher(ABC):
    @abstractmethod
    async def fetch(self, symbol: str, limit: int = 100) -> list[Post]:
        pass
