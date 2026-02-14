"""
General market news fetcher - fetches crypto news without symbol filtering.

This module provides functions to fetch general cryptocurrency market news
from various sources. Used for market-wide sentiment analysis.
"""

from typing import List
from .base import Post


GENERAL_CRYPTO_KEYWORDS = [
    "cryptocurrency",
    "crypto market",
    "bitcoin",
    "ethereum",
    "blockchain",
    "digital assets",
    "crypto",
]


async def fetch_market_telegram(fetcher, limit: int = 50) -> List[Post]:
    """
    Fetch general crypto news from Telegram messages in database.
    
    The new TelegramFetcher reads from telegram_messages table populated
    by the telegram_listener.py service. This function fetches all unprocessed
    crypto-related messages regardless of symbol.
    
    Args:
        fetcher: TelegramFetcher instance (database-backed)
        limit: Max messages to fetch
        
    Returns:
        List of Post objects with symbol="MARKET"
    """
    from .telegram import TelegramFetcher
    
    if not isinstance(fetcher, TelegramFetcher):
        return []
    
    # Get unprocessed messages from database
    messages = await fetcher.db.get_unprocessed_telegram_messages(limit=limit * 2)
    
    if not messages:
        return []
    
    all_posts = []
    
    for msg in messages:
        text_lower = msg['text'].lower()
        
        # Extract sentiment score
        score = fetcher._extract_sentiment_score(msg['text'])
        
        # Convert timestamp
        from datetime import datetime, timezone
        timestamp = datetime.fromtimestamp(msg['timestamp'], tz=timezone.utc)
        
        all_posts.append(
            Post(
                text=msg['text'][:1000],
                source=f"telegram:{msg['channel_username']}",
                symbol="MARKET",  # Special symbol for market-wide news
                timestamp=timestamp,
                score=score,
            )
        )
        
        # Mark as processed
        await fetcher.db.mark_telegram_message_processed(msg['id'])
    
    return all_posts


async def fetch_market_cryptopanic(fetcher, limit: int = 100) -> List[Post]:
    """
    Fetch general crypto news from CryptoPanic without currency filtering.
    
    Args:
        fetcher: CryptopanicFetcher instance
        limit: Max results
        
    Returns:
        List of Post objects with symbol="MARKET"
    """
    import httpx
    from datetime import datetime, timezone
    
    if not fetcher.api_key:
        return []
    
    posts = []
    
    try:
        async with httpx.AsyncClient(timeout=fetcher.timeout) as client:
            # No currency filter → get all crypto news
            params = {
                "auth_token": fetcher.api_key,
                "filter": "news",
                "public": "true",
            }
            
            response = await client.get(f"{fetcher.base_url}/posts/", params=params)
            response.raise_for_status()
            data = response.json()
            
            for item in data.get("results", [])[:limit]:
                posted_at = datetime.fromisoformat(
                    item["published_at"].replace("Z", "+00:00")
                )
                
                # Only recent news (last 48 hours)
                if (datetime.now(timezone.utc) - posted_at).total_seconds() > 172800:
                    continue
                
                title = item.get("title", "")
                summary = item.get("summary", "")
                text = f"{title}. {summary}" if summary else title
                
                sentiment_score = fetcher._extract_sentiment(text)
                
                posts.append(
                    Post(
                        text=text[:1000],
                        source="cryptopanic",
                        symbol="MARKET",
                        timestamp=posted_at,
                        score=sentiment_score,
                    )
                )
    
    except Exception as e:
        print(f"Error fetching market news from CryptoPanic: {e}")
    
    return posts


async def fetch_market_newsapi(fetcher, limit: int = 100) -> List[Post]:
    """
    Fetch general crypto news from NewsAPI.
    
    Args:
        fetcher: NewsAPIFetcher instance
        limit: Max results
        
    Returns:
        List of Post objects with symbol="MARKET"
    """
    import httpx
    from datetime import datetime
    
    if not fetcher.api_key:
        return []
    
    posts = []
    
    # General crypto market keywords
    keywords = [
        "cryptocurrency market",
        "crypto regulation",
        "bitcoin institutional",
        "crypto adoption",
    ]
    
    try:
        async with httpx.AsyncClient(timeout=fetcher.timeout) as client:
            for keyword in keywords:
                params = {
                    "q": keyword,
                    "apiKey": fetcher.api_key,
                    "sortBy": "publishedAt",
                    "language": "en",
                    "pageSize": min(25, limit // len(keywords)),
                }
                
                response = await client.get(
                    f"{fetcher.base_url}/everything",
                    params=params
                )
                response.raise_for_status()
                data = response.json()
                
                for article in data.get("articles", []):
                    published_at = datetime.fromisoformat(
                        article["publishedAt"].replace("Z", "+00:00")
                    )
                    
                    title = article.get("title", "")
                    description = article.get("description", "")
                    text = f"{title}. {description}" if description else title
                    
                    # Source authority scoring
                    source_name = article.get("source", {}).get("name", "")
                    is_major = any(
                        major in source_name
                        for major in ["Reuters", "Bloomberg", "CNBC", "CoinDesk", "The Block"]
                    )
                    score = 1 if is_major else 0
                    
                    posts.append(
                        Post(
                            text=text[:1000],
                            source="newsapi",
                            symbol="MARKET",
                            timestamp=published_at,
                            score=score,
                        )
                    )
    
    except Exception as e:
        print(f"Error fetching market news from NewsAPI: {e}")
    
    return posts


async def fetch_market_reddit(fetcher, limit: int = 50) -> List[Post]:
    """
    Fetch general crypto discussions from Reddit.
    
    Args:
        fetcher: RedditFetcher instance
        limit: Max posts
        
    Returns:
        List of Post objects with symbol="MARKET"
    """
    import asyncio
    from datetime import datetime, timezone
    
    if not fetcher.reddit:
        return []
    
    def _fetch_sync() -> List[Post]:
        posts = []
        subreddits = ["CryptoCurrency", "CryptoMarkets"]
        per_sub_limit = max(1, limit // len(subreddits))
        
        for subreddit_name in subreddits:
            try:
                subreddit = fetcher.reddit.subreddit(subreddit_name)
                for submission in subreddit.hot(limit=per_sub_limit):
                    posts.append(
                        Post(
                            text=f"{submission.title} {submission.selftext}"[:1000],
                            source="reddit",
                            symbol="MARKET",
                            timestamp=datetime.fromtimestamp(
                                submission.created_utc,
                                tz=timezone.utc
                            ),
                            score=submission.score,
                        )
                    )
            except Exception:
                continue
        
        return posts
    
    return await asyncio.to_thread(_fetch_sync)
