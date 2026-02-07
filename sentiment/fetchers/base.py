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


class BaseFetcher(ABC):
    @abstractmethod
    async def fetch(self, symbol: str, limit: int = 100) -> list[Post]:
        pass
