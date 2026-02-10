#!/usr/bin/env python3
"""
Debug script for Telegram connection issues.

This script helps diagnose why the listener gets stuck during startup.
"""

import asyncio
import logging
import os
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient, functions
from config import get_settings

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # DEBUG level for detailed output
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


async def test_telegram_connection():
    """Test Telegram connection step by step."""
    
    settings = get_settings()
    
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        logger.error("Missing Telegram API credentials!")
        return False
    
    session_path = ".telegram_sessions/sentiment_bot"
    
    logger.info("="*60)
    logger.info("Telegram Connection Diagnostics")
    logger.info("="*60)
    logger.info(f"API ID: {settings.telegram_api_id}")
    logger.info(f"API Hash: {settings.telegram_api_hash[:10]}...")
    logger.info(f"Session path: {session_path}")
    
    # Test 1: Create client
    logger.info("\nTest 1: Creating TelegramClient...")
    try:
        client = TelegramClient(
            session_path,
            settings.telegram_api_id,
            settings.telegram_api_hash,
            use_ipv6=False,
            timeout=10,
            connection_retries=2,
            retry_delay=1,
        )
        logger.info("✓ Client created")
    except Exception as e:
        logger.error(f"✗ Failed to create client: {e}")
        return False
    
    # Test 2: Connect with timeout
    logger.info("\nTest 2: Connecting to Telegram (30s timeout)...")
    try:
        start = datetime.now()
        await asyncio.wait_for(client.connect(), timeout=30.0)
        elapsed = (datetime.now() - start).total_seconds()
        logger.info(f"✓ Connected in {elapsed:.1f}s")
    except asyncio.TimeoutError:
        logger.error("✗ Connection timeout after 30s")
        return False
    except Exception as e:
        logger.error(f"✗ Connection failed: {e}")
        return False
    
    # Test 3: Check authorization
    logger.info("\nTest 3: Checking authorization (10s timeout)...")
    try:
        start = datetime.now()
        is_authorized = await asyncio.wait_for(
            client.is_user_authorized(),
            timeout=10.0
        )
        elapsed = (datetime.now() - start).total_seconds()
        logger.info(f"Authorization status: {is_authorized} (took {elapsed:.1f}s)")
        
        if not is_authorized:
            logger.error("✗ Not authorized - run setup_telegram.py")
            await client.disconnect()
            return False
        
        logger.info("✓ Authorized")
    except asyncio.TimeoutError:
        logger.error("✗ Authorization check timeout")
        await client.disconnect()
        return False
    except Exception as e:
        logger.error(f"✗ Authorization check failed: {e}")
        await client.disconnect()
        return False
    
    # Test 4: Get self user
    logger.info("\nTest 4: Getting user info (10s timeout)...")
    try:
        start = datetime.now()
        me = await asyncio.wait_for(client.get_me(), timeout=10.0)
        elapsed = (datetime.now() - start).total_seconds()
        logger.info(f"✓ User: {me.first_name} (ID: {me.id}) - took {elapsed:.1f}s")
    except asyncio.TimeoutError:
        logger.error("✗ get_me() timeout")
        await client.disconnect()
        return False
    except Exception as e:
        logger.error(f"✗ get_me() failed: {e}")
        await client.disconnect()
        return False
    
    # Test 5: Get state (keep-alive test)
    logger.info("\nTest 5: Getting updates state (10s timeout)...")
    try:
        start = datetime.now()
        state = await asyncio.wait_for(
            client(functions.updates.GetStateRequest()),
            timeout=10.0
        )
        elapsed = (datetime.now() - start).total_seconds()
        logger.info(f"✓ State pts={state.pts} - took {elapsed:.1f}s")
    except asyncio.TimeoutError:
        logger.error("✗ GetState timeout")
        await client.disconnect()
        return False
    except Exception as e:
        logger.error(f"✗ GetState failed: {e}")
        await client.disconnect()
        return False
    
    # Test 6: Resolve a channel (this is where it usually hangs)
    test_channel = "cointelegraph"
    logger.info(f"\nTest 6: Resolving channel @{test_channel} (15s timeout)...")
    try:
        start = datetime.now()
        entity = await asyncio.wait_for(
            client.get_entity(test_channel),
            timeout=15.0
        )
        elapsed = (datetime.now() - start).total_seconds()
        logger.info(f"✓ Channel resolved: {entity.title} (ID: {entity.id}) - took {elapsed:.1f}s")
    except asyncio.TimeoutError:
        logger.error(f"✗ get_entity(@{test_channel}) timeout after 15s")
        logger.error("This is likely where the listener gets stuck!")
        await client.disconnect()
        return False
    except Exception as e:
        logger.error(f"✗ get_entity(@{test_channel}) failed: {e}")
        await client.disconnect()
        return False
    
    # Success
    logger.info("\n" + "="*60)
    logger.info("All tests passed! ✓")
    logger.info("="*60)
    
    await client.disconnect()
    return True


if __name__ == "__main__":
    try:
        success = asyncio.run(test_telegram_connection())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
