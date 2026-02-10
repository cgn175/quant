#!/usr/bin/env python3
"""
Quick test script for Telegram fetcher.

Tests basic functionality with timeout protection.
"""

import asyncio
import signal
from dotenv import load_dotenv
from config import get_settings
from fetchers import TelegramFetcher


async def test_with_timeout():
    """Test Telegram fetcher with 30 second timeout."""
    
    load_dotenv()
    settings = get_settings()
    
    print('Testing Telegram Fetcher (30 second timeout)')
    print('=' * 60)
    
    fetcher = TelegramFetcher(
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
        channels=['cointelegraph', 'coindesk']  # Only 2 channels for speed
    )
    
    try:
        # Test with 30 second timeout
        print('\nFetching BTC mentions from 2 channels...')
        posts = await asyncio.wait_for(
            fetcher.fetch('BTCUSDT', limit=10),
            timeout=30.0
        )
        
        print(f'✓ Success! Found {len(posts)} posts\n')
        
        if posts:
            print('Sample post:')
            post = posts[0]
            print(f'  Source: {post.source}')
            print(f'  Text: {post.text[:100]}...')
            print(f'  Sentiment: {post.score}')
        
        return True
        
    except asyncio.TimeoutError:
        print('✗ Timeout after 30 seconds')
        print('  This might indicate rate limiting or network issues')
        return False
        
    except Exception as e:
        print(f'✗ Error: {type(e).__name__}: {e}')
        return False
        
    finally:
        await fetcher.disconnect()
        print('\n✓ Disconnected')


def main():
    """Run test with signal handling."""
    
    # Allow Ctrl+C to cancel
    def signal_handler(sig, frame):
        print('\n\nTest cancelled by user')
        exit(1)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        success = asyncio.run(test_with_timeout())
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print('\n\nTest cancelled')
        exit(1)


if __name__ == '__main__':
    main()
