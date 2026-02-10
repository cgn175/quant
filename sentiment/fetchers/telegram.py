"""
Telegram channel fetcher for crypto news using Telethon.

This fetcher now reads from the telegram_messages database table
populated by the telegram_listener.py service, instead of polling
Telegram directly. This avoids rate limiting issues and provides
better real-time message collection.

Architecture:
- telegram_listener.py: Event-driven listener (runs as daemon)
- telegram.py (this file): Fetcher that reads from database
"""

import asyncio
import os
from datetime import datetime, timezone
from typing import Optional

from .base import BaseFetcher, Post, extract_base_token

# Import SentimentDB for reading telegram_messages
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import SentimentDB


class TelegramFetcher(BaseFetcher):
    """
    Fetch crypto news from Telegram messages stored in database.
    
    This fetcher reads from telegram_messages table populated by
    the telegram_listener.py service. No direct Telegram API calls.
    """

    def __init__(self, db_path: str = "sentiment.db"):
        """
        Initialize Telegram fetcher.

        Args:
            db_path: Path to sentiment database
        """
        self.db = SentimentDB(db_path=db_path)

    async def fetch(self, symbol: str, limit: int = 100) -> list[Post]:
        """
        Fetch posts from telegram_messages database (populated by listener service).
        
        This method now reads from the database instead of polling Telegram directly.
        The telegram_listener.py service handles real-time message collection.

        Args:
            symbol: Trading symbol (e.g., BTCUSDT)
            limit: Maximum posts to fetch

        Returns:
            List of Post objects
        """
        # Get unprocessed messages from database
        messages = await self.db.get_unprocessed_telegram_messages(limit=limit * 2)
        
        if not messages:
            return []
        
        posts = []
        base_token = extract_base_token(symbol)
        keywords = self._get_keywords_for_symbol(base_token)
        
        for msg in messages:
            text_lower = msg['text'].lower()
            
            # Check if message is about our symbol
            if not any(kw in text_lower for kw in keywords):
                continue
            
            # Extract sentiment score
            score = self._extract_sentiment_score(msg['text'])
            
            # Convert timestamp
            timestamp = datetime.fromtimestamp(msg['timestamp'], tz=timezone.utc)
            
            posts.append(
                Post(
                    text=msg['text'][:1000],
                    source=f"telegram:{msg['channel_username']}",
                    symbol=symbol,
                    timestamp=timestamp,
                    score=score,
                )
            )
            
            # Mark as processed
            await self.db.mark_telegram_message_processed(msg['id'])
        
        return posts

    def _get_keywords_for_symbol(self, base_token: str) -> list[str]:
        """Get search keywords for a given token symbol."""
        keywords_map = {
            "BTC": ["bitcoin", "btc", "$btc"],
            "ETH": ["ethereum", "eth", "$eth", "ether"],
            "SOL": ["solana", "sol", "$sol"],
            "BNB": ["bnb", "$bnb", "binance"],
        }
        return keywords_map.get(base_token, [base_token.lower()])

    def _extract_sentiment_score(self, text: str) -> int:
        """
        Extract simple sentiment score from message text.

        Returns:
            1 for positive, -1 for negative, 0 for neutral
        """
        text_lower = text.lower()

        positive_words = [
            "surge",
            "rally",
            "bull",
            "gain",
            "profit",
            "up",
            "rise",
            "bullish",
            "strong",
            "growth",
            "pump",
            "moon",
            "breakthrough",
            "adoption",
            "partnership",
            "launch",
            "upgrade",
            "milestone",
        ]
        negative_words = [
            "crash",
            "dump",
            "bear",
            "loss",
            "down",
            "fall",
            "bearish",
            "weak",
            "decline",
            "risk",
            "concern",
            "drop",
            "hack",
            "scam",
            "regulation",
            "ban",
            "lawsuit",
            "fraud",
        ]

        positive_count = sum(1 for word in positive_words if word in text_lower)
        negative_count = sum(1 for word in negative_words if word in text_lower)

        if positive_count > negative_count:
            return 1
        elif negative_count > positive_count:
            return -1
        return 0
