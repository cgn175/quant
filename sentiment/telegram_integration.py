"""
Telegram Listener Integration for Sentiment Server.

This module provides optional integration of the Telegram listener
into the sentiment server as a background task.

Usage:
    # In main.py
    from telegram_integration import start_telegram_listener
    
    @app.on_event("startup")
    async def startup():
        if settings.telegram_listener_enabled:
            await start_telegram_listener()
"""

import asyncio
import logging
from typing import Optional

from config import get_settings
from telegram_listener import TelegramListener

logger = logging.getLogger(__name__)

# Global listener instance
_listener_instance: Optional[TelegramListener] = None
_listener_task: Optional[asyncio.Task] = None


async def start_telegram_listener() -> bool:
    """
    Start Telegram listener as a background task.
    
    Returns:
        True if started successfully, False otherwise
    """
    global _listener_instance, _listener_task
    
    settings = get_settings()
    
    # Check if already running
    if _listener_task and not _listener_task.done():
        logger.warning("Telegram listener already running")
        return True
    
    # Check credentials
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        logger.warning("Telegram API credentials not configured, skipping listener")
        return False
    
    logger.info("Starting integrated Telegram listener...")
    
    try:
        # Create listener instance
        _listener_instance = TelegramListener(
            api_id=settings.telegram_api_id,
            api_hash=settings.telegram_api_hash,
            session_name=settings.telegram_session_name,
            db_path="sentiment.db"
        )
        
        # Start as background task
        _listener_task = asyncio.create_task(_run_listener())
        
        logger.info("✓ Telegram listener started as background task")
        return True
        
    except Exception as e:
        logger.error(f"Failed to start Telegram listener: {e}", exc_info=True)
        return False


async def _run_listener():
    """Background task that runs the listener."""
    try:
        if _listener_instance:
            await _listener_instance.start()
    except asyncio.CancelledError:
        logger.info("Telegram listener task cancelled")
        if _listener_instance:
            await _listener_instance.stop()
    except Exception as e:
        logger.error(f"Telegram listener crashed: {e}", exc_info=True)


async def stop_telegram_listener():
    """Stop the Telegram listener if running."""
    global _listener_task, _listener_instance
    
    if _listener_task and not _listener_task.done():
        logger.info("Stopping Telegram listener...")
        _listener_task.cancel()
        
        try:
            await _listener_task
        except asyncio.CancelledError:
            pass
        
        if _listener_instance:
            await _listener_instance.stop()
        
        logger.info("Telegram listener stopped")


def is_listener_running() -> bool:
    """Check if Telegram listener is running."""
    return _listener_task is not None and not _listener_task.done()


def get_listener_stats() -> dict:
    """Get listener statistics."""
    if _listener_instance and is_listener_running():
        return {
            "running": True,
            "message_count": _listener_instance.message_count,
            "channels": len(_listener_instance.channel_ids),
        }
    else:
        return {
            "running": False,
            "message_count": 0,
            "channels": 0,
        }
