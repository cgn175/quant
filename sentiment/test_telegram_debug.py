#!/usr/bin/env python3
"""
Debug script to see what's taking so long.
"""

import asyncio
import time
from dotenv import load_dotenv
from config import get_settings
from fetchers import TelegramFetcher


async def debug_fetch():
    """Debug fetch with timing."""
    
    load_dotenv()
    settings = get_settings()
    
    print('Debug: Testing Telegram Fetcher')
    print('=' * 60)
    
    start = time.time()
    
    print(f'\n[{time.time() - start:.1f}s] Creating fetcher...')
    fetcher = TelegramFetcher(
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
        channels=['cointelegraph']  # Just 1 channel
    )
    
    print(f'[{time.time() - start:.1f}s] Fetcher created')
    
    try:
        print(f'[{time.time() - start:.1f}s] Starting fetch...')
        posts = await fetcher.fetch('BTCUSDT', limit=5)
        
        print(f'[{time.time() - start:.1f}s] Fetch complete!')
        print(f'\nFound {len(posts)} posts')
        
    except Exception as e:
        print(f'[{time.time() - start:.1f}s] Error: {e}')
        import traceback
        traceback.print_exc()
        
    finally:
        print(f'[{time.time() - start:.1f}s] Disconnecting...')
        await fetcher.disconnect()
        print(f'[{time.time() - start:.1f}s] Done')


if __name__ == '__main__':
    asyncio.run(debug_fetch())
