"""
Detailed live test with verbose output to debug API responses.
"""

import asyncio
import os
import json
import ssl
from datetime import datetime
from dotenv import load_dotenv

import httpx
import aiohttp

load_dotenv()

# Disable SSL verification for testing (not recommended for production)
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


async def test_fmp_detailed():
    """Test FMP with detailed response logging."""
    print("\n" + "="*60)
    print("DETAILED FMP TEST")
    print("="*60)
    
    api_key = os.getenv("SENTIMENT_FMP_API_KEY", "")
    base_url = "https://financialmodelingprep.com/stable"
    
    print(f"API Key: {api_key[:10]}..." if api_key else "No API key")
    print(f"Base URL: {base_url}")
    print(f"Endpoint: /news/crypto-latest")
    
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        url = f"{base_url}/news/crypto-latest"
        params = {
            "apikey": api_key,
            "page": 0,
            "limit": 5,
        }
        
        print(f"\nRequest URL: {url}")
        print(f"Request params: {params}")
        
        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                print(f"\nResponse status: {response.status}")
                print(f"Response headers: {dict(response.headers)}")
                
                text = await response.text()
                print(f"\nResponse body (first 500 chars):")
                print(text[:500])
                
                if response.status == 200:
                    try:
                        data = json.loads(text)
                        print(f"\nParsed JSON type: {type(data)}")
                        if isinstance(data, list):
                            print(f"Number of articles: {len(data)}")
                            if len(data) > 0:
                                print(f"\nFirst article keys: {data[0].keys()}")
                                print(f"First article: {json.dumps(data[0], indent=2)[:500]}")
                        elif isinstance(data, dict):
                            print(f"Response keys: {data.keys()}")
                            print(f"Full response: {json.dumps(data, indent=2)[:500]}")
                    except json.JSONDecodeError as e:
                        print(f"Failed to parse JSON: {e}")
                        
        except Exception as e:
            print(f"❌ ERROR: {type(e).__name__}: {str(e)}")


async def test_finnhub_detailed():
    """Test Finnhub with detailed response logging."""
    print("\n" + "="*60)
    print("DETAILED FINNHUB TEST")
    print("="*60)
    
    api_key = os.getenv("SENTIMENT_FINNHUB_API_KEY", "")
    base_url = "https://finnhub.io/api/v1"
    
    print(f"API Key: {api_key[:10]}..." if api_key else "No API key")
    print(f"Base URL: {base_url}")
    print(f"Endpoint: /news")
    
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        url = f"{base_url}/news"
        params = {
            "token": api_key,
            "category": "crypto",
        }
        
        print(f"\nRequest URL: {url}")
        print(f"Request params: {params}")
        
        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                print(f"\nResponse status: {response.status}")
                
                text = await response.text()
                print(f"\nResponse body (first 500 chars):")
                print(text[:500])
                
                if response.status == 200:
                    try:
                        data = json.loads(text)
                        print(f"\nParsed JSON type: {type(data)}")
                        if isinstance(data, list):
                            print(f"Number of articles: {len(data)}")
                            if len(data) > 0:
                                print(f"\nFirst article: {json.dumps(data[0], indent=2)}")
                        elif isinstance(data, dict):
                            print(f"Response: {json.dumps(data, indent=2)[:500]}")
                    except json.JSONDecodeError as e:
                        print(f"Failed to parse JSON: {e}")
                        
        except Exception as e:
            print(f"❌ ERROR: {type(e).__name__}: {str(e)}")


async def test_cryptopanic_detailed():
    """Test CryptoPanic with detailed response logging."""
    print("\n" + "="*60)
    print("DETAILED CRYPTOPANIC TEST")
    print("="*60)
    
    api_key = os.getenv("SENTIMENT_CRYPTOPANIC_API_KEY", "")
    base_url = "https://cryptopanic.com/api/free/v1"
    
    print(f"API Key: {api_key[:10]}..." if api_key else "No API key")
    print(f"Base URL: {base_url}")
    print(f"Endpoint: /posts/")
    
    with httpx.Client(timeout=httpx.Timeout(10.0)) as client:
        url = f"{base_url}/posts/"
        params = {
            "auth_token": api_key,
            "currencies": "BTC",
            "filter": "news",  # Changed from 'kind' to 'filter'
        }
        
        print(f"\nRequest URL: {url}")
        print(f"Request params: {params}")
        
        try:
            response = client.get(url, params=params)
            print(f"\nResponse status: {response.status_code}")
            
            text = response.text
            print(f"\nResponse body (first 500 chars):")
            print(text[:500])
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    print(f"\nParsed JSON type: {type(data)}")
                    print(f"Response keys: {data.keys() if isinstance(data, dict) else 'not a dict'}")
                    if isinstance(data, dict) and "results" in data:
                        print(f"Number of results: {len(data['results'])}")
                        if len(data['results']) > 0:
                            print(f"\nFirst result: {json.dumps(data['results'][0], indent=2)[:500]}")
                except json.JSONDecodeError as e:
                    print(f"Failed to parse JSON: {e}")
                    
        except Exception as e:
            print(f"❌ ERROR: {type(e).__name__}: {str(e)}")


async def test_marketaux_detailed():
    """Test Marketaux with detailed response logging."""
    print("\n" + "="*60)
    print("DETAILED MARKETAUX TEST")
    print("="*60)
    
    api_key = os.getenv("SENTIMENT_MARKETAUX_API_KEY", "")
    base_url = "https://api.marketaux.com/v1"
    
    print(f"API Key: {api_key[:10]}..." if api_key else "No API key")
    print(f"Base URL: {base_url}")
    print(f"Endpoint: /news/all")
    
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        url = f"{base_url}/news/all"
        params = {
            "api_token": api_key,
            "symbols": "BTC",
            "filter_entities": "true",
            "language": "en",
            "limit": 5,
        }
        
        print(f"\nRequest URL: {url}")
        print(f"Request params: {params}")
        
        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                print(f"\nResponse status: {response.status}")
                
                text = await response.text()
                print(f"\nResponse body (first 1000 chars):")
                print(text[:1000])
                
                if response.status == 200:
                    try:
                        data = json.loads(text)
                        print(f"\nParsed JSON type: {type(data)}")
                        if isinstance(data, dict):
                            print(f"Response keys: {data.keys()}")
                            if "data" in data:
                                print(f"Number of articles: {len(data['data'])}")
                                if len(data['data']) > 0:
                                    print(f"\nFirst article: {json.dumps(data['data'][0], indent=2)[:500]}")
                    except json.JSONDecodeError as e:
                        print(f"Failed to parse JSON: {e}")
                        
        except Exception as e:
            print(f"❌ ERROR: {type(e).__name__}: {str(e)}")


async def main():
    """Run detailed tests."""
    print("\n" + "="*60)
    print("DETAILED API RESPONSE TESTS")
    print("="*60)
    
    await test_fmp_detailed()
    await test_finnhub_detailed()
    await test_cryptopanic_detailed()
    await test_marketaux_detailed()
    
    print("\n" + "="*60)
    print("TESTS COMPLETE")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
