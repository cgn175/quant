import asyncio
from datetime import datetime, timezone

import praw
from config import get_settings

from .base import BaseFetcher, Post, extract_base_token

SYMBOL_KEYWORDS = {
    "BTC": ["bitcoin", "btc", "$btc"],
    "ETH": ["ethereum", "eth", "$eth", "ether"],
    "SOL": ["solana", "sol", "$sol"],
    "BNB": ["bnb", "$bnb", "binance coin"],
}

SUBREDDITS = ["CryptoCurrency", "Bitcoin", "ethereum", "solana"]


class RedditFetcher(BaseFetcher):
    def __init__(self):
        settings = get_settings()
        self.reddit = None
        if settings.reddit_client_id and settings.reddit_client_secret:
            self.reddit = praw.Reddit(
                client_id=settings.reddit_client_id,
                client_secret=settings.reddit_client_secret,
                user_agent=settings.reddit_user_agent,
            )

    def _fetch_sync(self, symbol: str, limit: int) -> list[Post]:
        """Synchronous fetch using praw. Meant to be called via
        asyncio.to_thread so the event loop is never blocked."""
        if not self.reddit:
            return []

        # Extract base token (e.g., BTCUSDT -> BTC)
        base_token = extract_base_token(symbol)
        keywords = SYMBOL_KEYWORDS.get(base_token, [base_token.lower()])
        posts: list[Post] = []
        per_sub_limit = max(1, limit // len(SUBREDDITS))

        for subreddit_name in SUBREDDITS:
            try:
                subreddit = self.reddit.subreddit(subreddit_name)
                for submission in subreddit.hot(limit=per_sub_limit):
                    text = f"{submission.title} {submission.selftext}".lower()
                    if any(kw in text for kw in keywords):
                        posts.append(
                            Post(
                                text=f"{submission.title} {submission.selftext}"[:1000],
                                source="reddit",
                                symbol=symbol,
                                timestamp=datetime.fromtimestamp(
                                    submission.created_utc, tz=timezone.utc
                                ),
                                score=submission.score,
                            )
                        )
            except Exception:
                continue

        return posts

    async def fetch(self, symbol: str, limit: int = 100) -> list[Post]:
        """Fetch posts without blocking the async event loop.

        praw is a synchronous library so all Reddit API calls are
        offloaded to a thread via ``asyncio.to_thread``.  This keeps the
        FastAPI server responsive while the (potentially slow) Reddit
        requests are in flight.
        """
        if not self.reddit:
            return []

        return await asyncio.to_thread(self._fetch_sync, symbol, limit)
