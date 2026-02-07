import praw
from datetime import datetime, timezone
from .base import BaseFetcher, Post
from config import get_settings

SYMBOL_KEYWORDS = {
    "BTCUSDT": ["bitcoin", "btc", "$btc"],
    "ETHUSDT": ["ethereum", "eth", "$eth", "ether"],
    "SOLUSDT": ["solana", "sol", "$sol"],
    "BNBUSDT": ["bnb", "$bnb", "binance coin"],
    "ETHBTC": ["eth/btc", "ethbtc", "ethereum bitcoin"],
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

    async def fetch(self, symbol: str, limit: int = 100) -> list[Post]:
        if not self.reddit:
            return []

        keywords = SYMBOL_KEYWORDS.get(symbol, [symbol.lower().replace("usdt", "")])
        posts = []

        for subreddit_name in SUBREDDITS:
            try:
                subreddit = self.reddit.subreddit(subreddit_name)
                for submission in subreddit.hot(limit=limit // len(SUBREDDITS)):
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
