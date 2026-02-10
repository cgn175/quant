"""
Telegram channel fetcher for crypto news using Telethon.

This fetcher connects to Telegram's MTProto API via Telethon to listen
for messages from public crypto news channels. It includes:
- Exponential backoff retry logic for flood limit handling
- Secure session management with file-based storage
- Rate limiting compliance with Telegram's API limits
- Security best practices for MTProto connections
"""

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Optional

from telethon import TelegramClient, events
from telethon.errors import (
    ApiIdInvalidError,
    ChannelPrivateError,
    ChatAdminRequiredError,
    FloodWaitError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)
from telethon.tl.types import Channel

from .base import BaseFetcher, Post, extract_base_token

# Exponential backoff configuration
INITIAL_BACKOFF_SECONDS = 1
MAX_BACKOFF_SECONDS = 300  # 5 minutes max
BACKOFF_MULTIPLIER = 2
MAX_RETRIES = 5

# Rate limiting configuration (Telegram MTProto limits)
MESSAGES_PER_SECOND = 1  # Conservative limit for message fetching
BURST_LIMIT = 20  # Max messages in burst before throttling


class RateLimiter:
    """Token bucket rate limiter for Telegram API calls."""

    def __init__(self, rate: float, burst: int):
        """
        Args:
            rate: Tokens per second
            burst: Maximum tokens in bucket
        """
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last_update = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self):
        """Acquire a token, waiting if necessary."""
        async with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_update

            # Refill tokens based on elapsed time
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_update = now

            # If no tokens available, wait for one
            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1


class TelegramFetcher(BaseFetcher):
    """
    Fetch crypto news from Telegram public channels.

    Security features:
    - Session files stored with restricted permissions (0600)
    - API credentials validated before use
    - No password storage (uses session persistence)
    - Connection errors handled gracefully
    - Rate limiting to prevent API abuse
    """

    # Popular crypto news Telegram channels (add more as needed)
    DEFAULT_CHANNELS = [
        "cointelegraph",  # CoinTelegraph official
        "crypto",  # Crypto.com News
        "bitcoinmagazine",  # Bitcoin Magazine
        "binance_announcements",  # Binance Official Announcements
        "coindesk",  # CoinDesk
        "the_block_crypto",
        "wublockchainenglish",
        "CTMarkets",  # Market-specific updates from Cointelegraph
    ]

    def __init__(
        self,
        api_id: Optional[int] = None,
        api_hash: Optional[str] = None,
        session_name: str = "sentiment_bot",
        session_dir: str = ".telegram_sessions",
        channels: Optional[list[str]] = None,
    ):
        """
        Initialize Telegram fetcher.

        Args:
            api_id: Telegram API ID (get from https://my.telegram.org/apps)
            api_hash: Telegram API hash
            session_name: Session file name (without extension)
            session_dir: Directory to store session files (will be created with 0700 permissions)
            channels: List of channel usernames to monitor (without @)

        Security Notes:
            - API credentials should be stored in environment variables, not hardcoded
            - Session files contain authentication data and should never be committed to git
            - Session directory will be created with restricted permissions (0700)
        """
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.session_dir = session_dir
        self.channels = channels or self.DEFAULT_CHANNELS

        self.client: Optional[TelegramClient] = None
        self.rate_limiter = RateLimiter(rate=MESSAGES_PER_SECOND, burst=BURST_LIMIT)

        # Message cache to avoid duplicates
        self._message_cache: set[int] = set()
        self._cache_lock = asyncio.Lock()

        # Ensure session directory exists with secure permissions
        if self.api_id and self.api_hash:
            self._setup_session_directory()

    def _setup_session_directory(self):
        """Create session directory with restricted permissions."""
        if not os.path.exists(self.session_dir):
            os.makedirs(self.session_dir, mode=0o700)
        else:
            # Ensure existing directory has correct permissions
            os.chmod(self.session_dir, 0o700)

    async def _exponential_backoff_retry(self, func, *args, **kwargs):
        """
        Execute function with exponential backoff retry logic.

        Handles Telegram FloodWaitError and other transient errors with
        exponential backoff between retries.

        Args:
            func: Async function to execute
            *args, **kwargs: Arguments to pass to func

        Returns:
            Result of func if successful

        Raises:
            Exception after max retries exceeded
        """
        backoff = INITIAL_BACKOFF_SECONDS
        last_exception = None

        for attempt in range(MAX_RETRIES):
            try:
                return await func(*args, **kwargs)

            except FloodWaitError as e:
                # Telegram explicitly tells us how long to wait
                wait_time = e.seconds
                print(
                    f"FloodWaitError: Must wait {wait_time} seconds (attempt {attempt + 1}/{MAX_RETRIES})"
                )

                # If wait time is too long, give up
                if wait_time > MAX_BACKOFF_SECONDS:
                    print(
                        f"Wait time {wait_time}s exceeds max backoff {MAX_BACKOFF_SECONDS}s, giving up"
                    )
                    raise

                await asyncio.sleep(wait_time)
                last_exception = e

            except (ConnectionError, TimeoutError, OSError) as e:
                # Network errors - use exponential backoff
                wait_time = min(backoff, MAX_BACKOFF_SECONDS)
                print(
                    f"Connection error: {type(e).__name__}, retrying in {wait_time}s (attempt {attempt + 1}/{MAX_RETRIES})"
                )

                await asyncio.sleep(wait_time)
                backoff *= BACKOFF_MULTIPLIER
                last_exception = e

            except (
                ApiIdInvalidError,
                SessionPasswordNeededError,
                PhoneCodeInvalidError,
            ) as e:
                # Authentication errors - don't retry
                print(f"Authentication error: {type(e).__name__}: {e}")
                raise

        # Max retries exceeded
        raise Exception(f"Max retries ({MAX_RETRIES}) exceeded") from last_exception

    async def _init_client(self):
        """Initialize Telegram client with security best practices."""
        if not self.api_id or not self.api_hash:
            return None

        session_path = os.path.join(self.session_dir, self.session_name)

        try:
            # Create client with secure session storage
            self.client = TelegramClient(
                session_path,
                self.api_id,
                self.api_hash,
                # Security: Use IPv6 when available for better privacy
                use_ipv6=False,  # Disable IPv6 for better compatibility
                # Connection settings
                timeout=10,  # Shorter timeout
                connection_retries=2,  # Fewer retries
                retry_delay=1,
                auto_reconnect=True,
            )

            # Connect with timeout protection
            await asyncio.wait_for(
                self.client.connect(),
                timeout=15.0  # 15 second timeout for connection
            )

            # Check if we need to authorize (first time setup)
            if not await self.client.is_user_authorized():
                print("Telegram session not authorized. Manual setup required.")
                print("Run the setup script to authenticate: python setup_telegram.py")
                await self.client.disconnect()
                return None

            # Set session file permissions to read/write owner only
            if os.path.exists(f"{session_path}.session"):
                os.chmod(f"{session_path}.session", 0o600)

            return self.client

        except Exception as e:
            print(f"Failed to initialize Telegram client: {type(e).__name__}: {e}")
            if self.client:
                await self.client.disconnect()
                self.client = None
            return None

    async def _fetch_channel_messages(
        self, channel_username: str, limit: int, symbol: str
    ) -> list[Post]:
        """
        Fetch messages from a specific channel with rate limiting.

        Args:
            channel_username: Channel username (without @)
            limit: Maximum messages to fetch
            symbol: Trading symbol to filter for

        Returns:
            List of Post objects
        """
        if not self.client:
            return []

        posts = []
        base_token = extract_base_token(symbol)
        keywords = self._get_keywords_for_symbol(base_token)

        try:
            # Get channel entity (cached by Telethon)
            channel = await self._exponential_backoff_retry(
                self.client.get_entity, channel_username
            )

            if not isinstance(channel, Channel):
                return []

            # Rate limit before fetching messages
            await self.rate_limiter.acquire()

            # Fetch messages with exponential backoff
            messages = await self._exponential_backoff_retry(
                self.client.get_messages, channel, limit=limit
            )

            for message in messages:
                if not message.text:
                    continue

                # Check if message is about our symbol
                text_lower = message.text.lower()
                if not any(kw in text_lower for kw in keywords):
                    continue

                # Check if we've already seen this message
                async with self._cache_lock:
                    if message.id in self._message_cache:
                        continue
                    self._message_cache.add(message.id)

                # Extract sentiment score (simple keyword-based)
                score = self._extract_sentiment_score(message.text)

                posts.append(
                    Post(
                        text=message.text[:1000],
                        source=f"telegram:{channel_username}",
                        symbol=symbol,
                        timestamp=message.date.replace(tzinfo=timezone.utc),
                        score=score,
                    )
                )

        except ChannelPrivateError:
            print(f"Channel @{channel_username} is private or doesn't exist")
        except ChatAdminRequiredError:
            print(f"Admin rights required for channel @{channel_username}")
        except FloodWaitError as e:
            print(
                f"Hit flood limit for channel @{channel_username}, need to wait {e.seconds}s"
            )
        except Exception as e:
            print(
                f"Error fetching from channel @{channel_username}: {type(e).__name__}: {e}"
            )

        return posts

    async def fetch(self, symbol: str, limit: int = 100) -> list[Post]:
        """
        Fetch posts from all configured Telegram channels.

        Args:
            symbol: Trading symbol (e.g., BTCUSDT)
            limit: Maximum posts to fetch per channel

        Returns:
            List of Post objects
        """
        if not self.api_id or not self.api_hash:
            return []

        # Initialize client if not already done
        if not self.client:
            await self._init_client()

        if not self.client:
            return []

        # Fetch from all channels with rate limiting
        all_posts = []
        per_channel_limit = max(1, limit // len(self.channels))

        for channel in self.channels:
            try:
                posts = await self._fetch_channel_messages(
                    channel, per_channel_limit, symbol
                )
                all_posts.extend(posts)
            except Exception as e:
                print(f"Failed to fetch from channel {channel}: {e}")
                continue

        # Clean up old messages from cache periodically
        async with self._cache_lock:
            if len(self._message_cache) > 10000:
                # Keep only most recent 5000 message IDs
                self._message_cache = set(list(self._message_cache)[-5000:])

        return all_posts

    async def disconnect(self):
        """Disconnect from Telegram and clean up resources."""
        if self.client:
            await self.client.disconnect()
            self.client = None

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

    def __del__(self):
        """Ensure client is disconnected on cleanup."""
        if self.client:
            try:
                asyncio.create_task(self.disconnect())
            except RuntimeError:
                # Event loop might already be closed
                pass
