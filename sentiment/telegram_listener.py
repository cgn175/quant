"""
Telegram Message Listener - Event-driven message collection.

Instead of polling for messages, this service listens to Telegram channels
in real-time using Telethon's event system. Messages are processed and
saved to the database immediately as they arrive.

Architecture:
- Uses @events.NewMessage decorator for real-time updates
- Runs as a long-lived background process (not a fetcher)
- Saves messages to database for later sentiment analysis
- Handles connection issues with automatic reconnection
- Implements keep-alive mechanism to prevent update timeouts
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional, Set

from telethon import TelegramClient, events, functions
from telethon.errors import (
    ApiIdInvalidError,
    ChannelPrivateError,
    ChatAdminRequiredError,
    FloodWaitError,
    SessionPasswordNeededError,
)
from telethon.tl.types import Channel

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sentiment.config import get_settings
from sentiment.db import SentimentDB

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("telegram_listener.log"),
    ],
)
logger = logging.getLogger(__name__)

# Crypto news channels to monitor
DEFAULT_CHANNELS = [
    "cointelegraph",  # CoinTelegraph official
    "crypto",  # Crypto.com News
    "binance_announcements",  # Binance Official Announcements
    "CoinDeskGlobal",  # CoinDesk
    "the_block_crypto",
    "wublockchainenglish",
    ### global finance news ###
    "bloomberg",
    "TheFinancialExpressOnline",
    "WatcherGuru",
]

KEEP_ALIVE_INTERVAL = 30  # seconds


class TelegramListener:
    """
    Event-driven Telegram message listener.

    Connects to Telegram and listens for new messages from configured channels.
    Messages are saved to database for later sentiment analysis.
    """

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_name: str = "sentiment_listener",
        session_dir: str = ".telegram_sessions",
        channels: Optional[list[str]] = None,
        db_path: str = "sentiment.db",
    ):
        """
        Initialize Telegram listener.

        Args:
            api_id: Telegram API ID
            api_hash: Telegram API hash
            session_name: Session file name
            session_dir: Directory for session files
            channels: List of channel usernames to monitor
            db_path: Path to sentiment database
        """
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.session_dir = session_dir
        self.channels = channels or DEFAULT_CHANNELS
        self.db = SentimentDB(db_path=db_path)

        self.client: Optional[TelegramClient] = None
        self.running = False
        self.message_count = 0
        self.channel_ids: Set[int] = set()

        # Ensure session directory exists
        if not os.path.exists(self.session_dir):
            os.makedirs(self.session_dir, mode=0o700)
        else:
            os.chmod(self.session_dir, 0o700)

    async def start(self):
        """Start the Telegram listener service."""
        if self.running:
            logger.warning("Listener already running")
            return

        logger.info("=" * 60)
        logger.info("Starting Telegram Message Listener")
        logger.info("=" * 60)
        logger.info(
            f"Monitoring {len(self.channels)} channels: {', '.join(self.channels)}"
        )

        # Initialize Telegram client
        session_path = os.path.join(self.session_dir, self.session_name)

        self.client = TelegramClient(
            session_path,
            self.api_id,
            self.api_hash,
            use_ipv6=False,
            timeout=15,  # Reduced from 30 to 15 seconds
            connection_retries=3,  # Reduced from 5 to 3
            retry_delay=1,
            auto_reconnect=True,
            flood_sleep_threshold=0,  # Don't auto-sleep on flood, raise error instead
        )

        try:
            # Connect to Telegram with timeout
            logger.info("Connecting to Telegram...")
            try:
                await asyncio.wait_for(
                    self.client.connect(),
                    timeout=45.0,  # 45 second timeout for connection
                )
                logger.info("Connection established")
            except asyncio.TimeoutError:
                logger.error("Connection timeout after 45 seconds!")
                return

            # Check authorization with timeout
            logger.info("Checking authorization...")
            try:
                is_authorized = await asyncio.wait_for(
                    self.client.is_user_authorized(),
                    timeout=30.0,  # 30 second timeout for auth check
                )
                logger.info(f"Authorization check complete: {is_authorized}")
            except asyncio.TimeoutError:
                logger.error("Authorization check timeout after 30 seconds!")
                await self.client.disconnect()
                return

            if not is_authorized:
                logger.error("Telegram session not authorized!")
                logger.error("Run setup_telegram.py first to authenticate")
                await self.client.disconnect()
                return

            logger.info("✓ Connected and authorized")

            # Set session file permissions
            if os.path.exists(f"{session_path}.session"):
                os.chmod(f"{session_path}.session", 0o600)

            # Join/resolve channels and collect their IDs
            logger.info("Resolving channel entities...")
            try:
                await asyncio.wait_for(
                    self._resolve_channels(),
                    timeout=180.0,  # 3 minute timeout for all channels
                )
            except asyncio.TimeoutError:
                logger.error("Channel resolution timed out after 3 minutes!")
                if not self.channel_ids:
                    logger.error("No channels resolved, cannot continue")
                    await self.client.disconnect()
                    return
                logger.warning(
                    f"Continuing with {len(self.channel_ids)} resolved channels..."
                )

            if not self.channel_ids:
                logger.error("No valid channels found!")
                await self.client.disconnect()
                return

            logger.info(f"✓ Monitoring {len(self.channel_ids)} channels")

            # Register event handlers
            self._register_event_handlers()

            # Start keep-alive task
            self.running = True
            asyncio.create_task(self._keep_alive())

            logger.info("=" * 60)
            logger.info("Telegram Listener is now running!")
            logger.info("Press Ctrl+C to stop")
            logger.info("=" * 60)

            # Run until stopped
            await self.client.run_until_disconnected()

        except Exception as e:
            logger.error(f"Failed to start listener: {e}", exc_info=True)
            if self.client:
                await self.client.disconnect()

    async def stop(self):
        """Stop the listener service."""
        logger.info("Stopping Telegram listener...")
        self.running = False

        if self.client:
            await self.client.disconnect()

        logger.info(f"Total messages processed: {self.message_count}")
        logger.info("Listener stopped")

    async def _resolve_channels(self):
        """Resolve channel entities and collect their IDs."""
        self.channel_ids.clear()
        logger.info(f"Attempting to resolve {len(self.channels)} channels...")

        for i, channel_username in enumerate(self.channels, 1):
            logger.info(
                f"  [{i}/{len(self.channels)}] Resolving @{channel_username}..."
            )
            try:
                # Add timeout to prevent hanging
                entity = await asyncio.wait_for(
                    self.client.get_entity(channel_username),
                    timeout=15.0,  # 15 second timeout per channel
                )

                if isinstance(entity, Channel):
                    self.channel_ids.add(entity.id)
                    logger.info(f"  ✓ {channel_username} (ID: {entity.id})")
                else:
                    logger.warning(f"  ✗ {channel_username} is not a channel")

            except asyncio.TimeoutError:
                logger.error(f"  ✗ {channel_username}: Timeout after 15s (skipping)")
            except ChannelPrivateError:
                logger.error(
                    f"  ✗ {channel_username}: Channel is private or doesn't exist"
                )
            except ChatAdminRequiredError:
                logger.error(f"  ✗ {channel_username}: Admin rights required")
            except FloodWaitError as e:
                logger.error(f"  ✗ {channel_username}: FloodWait {e.seconds}s")
                # Wait if FloodWait is short
                if e.seconds < 60:
                    logger.info(f"  Waiting {e.seconds}s due to FloodWait...")
                    await asyncio.sleep(e.seconds)
            except Exception as e:
                logger.error(f"  ✗ {channel_username}: {type(e).__name__}: {e}")

        logger.info(
            f"Successfully resolved {len(self.channel_ids)} out of {len(self.channels)} channels"
        )

    def _register_event_handlers(self):
        """Register event handlers for new messages."""

        @self.client.on(events.NewMessage(chats=list(self.channel_ids)))
        async def handle_new_message(event):
            """Handle new message from monitored channels."""
            try:
                message = event.message

                # Skip non-text messages
                if not message.text:
                    return

                # Get channel info
                chat = await event.get_chat()
                channel_username = getattr(chat, "username", "unknown")
                source = f"telegram:{channel_username}"

                # Extract message metadata
                text = message.text[:2000]  # Limit text length
                timestamp = message.date.replace(tzinfo=timezone.utc)
                message_id = message.id

                # Log the message
                logger.info(f"New message from @{channel_username}")
                logger.info(f"  Text: {text[:100]}{'...' if len(text) > 100 else ''}")
                logger.info(f"  Timestamp: {timestamp.isoformat()}")

                # Save raw message to database
                # We'll categorize by symbol later during sentiment analysis
                await self._save_message(
                    text=text, source=source, timestamp=timestamp, message_id=message_id
                )

                self.message_count += 1

                if self.message_count % 10 == 0:
                    logger.info(f"Total messages processed: {self.message_count}")

            except Exception as e:
                logger.error(f"Error handling message: {e}", exc_info=True)

    async def _save_message(
        self, text: str, source: str, timestamp: datetime, message_id: int
    ):
        """
        Save raw message to database.

        Messages are saved to telegram_messages table and will be processed
        later during sentiment analysis by the fetcher_manager.
        """
        try:
            # Extract channel username from source (format: "telegram:username")
            channel_username = source.split(":")[1] if ":" in source else "unknown"

            # Save to telegram_messages table
            saved = await self.db.save_telegram_message(
                message_id=message_id,
                channel_username=channel_username,
                text=text,
                timestamp=timestamp,
            )

            if saved:
                logger.debug(f"✓ Saved message {message_id} from @{channel_username}")
            else:
                logger.debug(f"Message {message_id} already exists (duplicate)")

        except Exception as e:
            logger.error(f"Error saving message to database: {e}", exc_info=True)

    async def _keep_alive(self):
        """
        Keep-alive mechanism to prevent update timeouts.

        Calls getState() every 30 seconds to keep the connection alive
        and ensure updates continue to flow.
        """
        logger.info("Keep-alive task started")

        while self.running:
            try:
                await asyncio.sleep(KEEP_ALIVE_INTERVAL)

                if self.client and self.client.is_connected():
                    # Send a ping to keep connection alive
                    state = await self.client(functions.updates.GetStateRequest())
                    logger.debug(f"Keep-alive: connection OK (state pts={state.pts})")
                else:
                    logger.warning(
                        "Keep-alive: client not connected, attempting reconnect..."
                    )
                    if self.client:
                        await self.client.connect()

            except Exception as e:
                logger.error(f"Keep-alive error: {e}")
                # Don't crash the keep-alive loop
                await asyncio.sleep(5)

        logger.info("Keep-alive task stopped")


async def main():
    """Main entry point for the listener service."""
    import signal

    # Load settings
    settings = get_settings()

    if not settings.telegram_api_id or not settings.telegram_api_hash:
        logger.error("Missing Telegram API credentials!")
        logger.error(
            "Set SENTIMENT_TELEGRAM_API_ID and SENTIMENT_TELEGRAM_API_HASH in .env"
        )
        return 1

    # Create listener
    listener = TelegramListener(
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
        session_name=settings.telegram_session_name,
        channels=DEFAULT_CHANNELS,
        db_path="sentiment.db",
    )

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()

    def signal_handler(sig):
        logger.info(f"Received signal {sig.name}, initiating shutdown...")
        listener.running = False
        if listener.client:
            loop.create_task(listener.stop())

    # Register signal handlers
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))

    # Start listening
    try:
        await listener.start()
        return 0
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        await listener.stop()
        return 0
    except Exception as e:
        logger.error(f"Listener crashed: {e}", exc_info=True)
        return 1
    finally:
        # Ensure cleanup
        if listener.running:
            await listener.stop()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
