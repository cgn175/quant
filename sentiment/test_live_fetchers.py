"""
Live test of fetcher APIs with real API keys from .env file.
Tests actual API communication to verify endpoints and authentication work.
"""

import asyncio
import os
from datetime import datetime
from dotenv import load_dotenv

from fetchers import (
    CoinGeckoFetcher,
    CoinMarketCapFetcher,
    FinnhubFetcher,
    FMPFetcher,
    MarketauxFetcher,
    CryptopanicFetcher,
    NewsAPIFetcher,
)

# Load environment variables
load_dotenv()


async def test_coingecko():
    """Test CoinGecko API with real requests."""
    print("\n" + "="*60)
    print("Testing CoinGecko API")
    print("="*60)
    
    api_key = os.getenv("SENTIMENT_COINGECKO_API_KEY", "")
    fetcher = CoinGeckoFetcher(api_key=api_key)
    
    print(f"API Key configured: {bool(api_key)}")
    print(f"Base URL: {fetcher.base_url}")
    
    try:
        posts = await fetcher.fetch("BTCUSDT", limit=5)
        print(f"✅ SUCCESS: Fetched {len(posts)} posts")
        
        for i, post in enumerate(posts[:2], 1):
            print(f"\n  Post {i}:")
            print(f"    Source: {post.source}")
            print(f"    Text: {post.text[:100]}...")
            print(f"    Score: {post.score}")
            
    except Exception as e:
        print(f"❌ ERROR: {type(e).__name__}: {str(e)}")


async def test_coinmarketcap():
    """Test CoinMarketCap API with real requests."""
    print("\n" + "="*60)
    print("Testing CoinMarketCap API")
    print("="*60)
    
    api_key = os.getenv("SENTIMENT_COINMARKETCAP_API_KEY", "")
    fetcher = CoinMarketCapFetcher(api_key=api_key)
    
    print(f"API Key configured: {bool(api_key)}")
    print(f"Base URL: {fetcher.BASE_URL}")
    
    if not api_key:
        print("⚠️  SKIPPED: No API key configured")
        return
    
    try:
        posts = await fetcher.fetch("BTCUSDT", limit=5)
        print(f"✅ SUCCESS: Fetched {len(posts)} posts")
        
        for i, post in enumerate(posts[:2], 1):
            print(f"\n  Post {i}:")
            print(f"    Source: {post.source}")
            print(f"    Text: {post.text[:100]}...")
            print(f"    Score: {post.score}")
            
    except Exception as e:
        print(f"❌ ERROR: {type(e).__name__}: {str(e)}")
    finally:
        await fetcher.close()


async def test_finnhub():
    """Test Finnhub API with real requests."""
    print("\n" + "="*60)
    print("Testing Finnhub API")
    print("="*60)
    
    api_key = os.getenv("SENTIMENT_FINNHUB_API_KEY", "")
    fetcher = FinnhubFetcher(api_key=api_key)
    
    print(f"API Key configured: {bool(api_key)}")
    print(f"Base URL: {fetcher.BASE_URL}")
    
    if not api_key:
        print("⚠️  SKIPPED: No API key configured")
        return
    
    try:
        posts = await fetcher.fetch("BTCUSDT", limit=5)
        print(f"✅ SUCCESS: Fetched {len(posts)} posts")
        
        for i, post in enumerate(posts[:2], 1):
            print(f"\n  Post {i}:")
            print(f"    Source: {post.source}")
            print(f"    Text: {post.text[:100]}...")
            print(f"    Score: {post.score}")
            
    except Exception as e:
        print(f"❌ ERROR: {type(e).__name__}: {str(e)}")
    finally:
        await fetcher.close()


async def test_fmp():
    """Test FMP API with real requests."""
    print("\n" + "="*60)
    print("Testing FMP (Financial Modeling Prep) API")
    print("="*60)
    
    api_key = os.getenv("SENTIMENT_FMP_API_KEY", "")
    fetcher = FMPFetcher(api_key=api_key)
    
    print(f"API Key configured: {bool(api_key)}")
    print(f"Base URL: {fetcher.BASE_URL}")
    print(f"Endpoint: /news/crypto-latest")
    
    if not api_key:
        print("⚠️  SKIPPED: No API key configured")
        return
    
    try:
        posts = await fetcher.fetch("BTCUSDT", limit=5)
        print(f"✅ SUCCESS: Fetched {len(posts)} posts")
        
        for i, post in enumerate(posts[:2], 1):
            print(f"\n  Post {i}:")
            print(f"    Source: {post.source}")
            print(f"    Text: {post.text[:100]}...")
            print(f"    Score: {post.score}")
            
    except Exception as e:
        print(f"❌ ERROR: {type(e).__name__}: {str(e)}")
    finally:
        await fetcher.close()


async def test_marketaux():
    """Test Marketaux API with real requests."""
    print("\n" + "="*60)
    print("Testing Marketaux API")
    print("="*60)
    
    api_key = os.getenv("SENTIMENT_MARKETAUX_API_KEY", "")
    fetcher = MarketauxFetcher(api_key=api_key)
    
    print(f"API Key configured: {bool(api_key)}")
    print(f"Base URL: {fetcher.BASE_URL}")
    
    if not api_key:
        print("⚠️  SKIPPED: No API key configured")
        return
    
    try:
        posts = await fetcher.fetch("BTCUSDT", limit=5)
        print(f"✅ SUCCESS: Fetched {len(posts)} posts")
        
        for i, post in enumerate(posts[:2], 1):
            print(f"\n  Post {i}:")
            print(f"    Source: {post.source}")
            print(f"    Text: {post.text[:100]}...")
            print(f"    Score: {post.score}")
            
    except Exception as e:
        print(f"❌ ERROR: {type(e).__name__}: {str(e)}")
    finally:
        await fetcher.close()


async def test_cryptopanic():
    """Test CryptoPanic API with real requests."""
    print("\n" + "="*60)
    print("Testing CryptoPanic API")
    print("="*60)
    
    api_key = os.getenv("SENTIMENT_CRYPTOPANIC_API_KEY", "")
    fetcher = CryptopanicFetcher(api_key=api_key)
    
    print(f"API Key configured: {bool(api_key)}")
    print(f"Base URL: {fetcher.base_url}")
    
    if not api_key:
        print("⚠️  SKIPPED: No API key configured")
        return
    
    try:
        posts = await fetcher.fetch("BTCUSDT", limit=5)
        print(f"✅ SUCCESS: Fetched {len(posts)} posts")
        
        for i, post in enumerate(posts[:2], 1):
            print(f"\n  Post {i}:")
            print(f"    Source: {post.source}")
            print(f"    Text: {post.text[:100]}...")
            print(f"    Score: {post.score}")
            
    except Exception as e:
        print(f"❌ ERROR: {type(e).__name__}: {str(e)}")


async def test_newsapi():
    """Test NewsAPI.org with real requests."""
    print("\n" + "="*60)
    print("Testing NewsAPI.org API")
    print("="*60)
    
    api_key = os.getenv("SENTIMENT_NEWSAPI_KEY", "")  # Changed from SENTIMENT_NEWSAPI_API_KEY
    fetcher = NewsAPIFetcher(api_key=api_key)
    
    print(f"API Key configured: {bool(api_key)}")
    print(f"Base URL: {fetcher.base_url}")
    
    if not api_key:
        print("⚠️  SKIPPED: No API key configured")
        return
    
    try:
        posts = await fetcher.fetch("BTCUSDT", limit=5)
        print(f"✅ SUCCESS: Fetched {len(posts)} posts")
        
        for i, post in enumerate(posts[:2], 1):
            print(f"\n  Post {i}:")
            print(f"    Source: {post.source}")
            print(f"    Text: {post.text[:100]}...")
            print(f"    Score: {post.score}")
            
    except Exception as e:
        print(f"❌ ERROR: {type(e).__name__}: {str(e)}")


async def main():
    """Run all fetcher tests."""
    print("\n" + "="*60)
    print("LIVE FETCHER API TESTS")
    print("Testing actual API communication with real API keys")
    print("="*60)
    
    # Test all fetchers
    await test_coingecko()
    await test_coinmarketcap()
    await test_finnhub()
    await test_fmp()
    await test_marketaux()
    await test_cryptopanic()
    await test_newsapi()
    
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print("\nCheck results above for each fetcher.")
    print("✅ = Success, ❌ = Error, ⚠️ = Skipped (no API key)")
    print("\n" + "="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
