#!/usr/bin/env python3
"""
Test script for market sentiment endpoint.

Tests:
1. Market sentiment endpoint works
2. Returns expected fields
3. Compares with symbol-specific sentiment
"""

import asyncio
import httpx
from datetime import datetime


async def test_market_sentiment():
    """Test the /sentiment/market endpoint."""
    
    print("=" * 60)
    print("Testing Market Sentiment Endpoint")
    print("=" * 60)
    print()
    
    base_url = "http://localhost:8000"
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Test 1: Health check
        print("1. Testing health endpoint...")
        try:
            resp = await client.get(f"{base_url}/health")
            if resp.status_code == 200:
                print("   ✓ Sentiment server is running")
            else:
                print(f"   ✗ Health check failed: {resp.status_code}")
                return
        except Exception as e:
            print(f"   ✗ Cannot connect to server: {e}")
            print("   Make sure the sentiment server is running: python main.py")
            return
        
        print()
        
        # Test 2: Market sentiment
        print("2. Fetching market sentiment...")
        print("   (This may take 10-20 seconds to fetch from all sources)")
        print()
        
        try:
            resp = await client.get(f"{base_url}/sentiment/market")
            
            if resp.status_code == 200:
                data = resp.json()
                
                print("   ✓ Market sentiment endpoint works!")
                print()
                print("   Results:")
                print(f"   Market Sentiment: {data['market_sentiment']:.3f}")
                print(f"   Regime: {data['regime']}")
                print(f"   Fear & Greed Index: {data['fear_greed_index']:.1f}/100")
                print(f"   Mentions: {data['mentions']}")
                print(f"   Sources: {', '.join(data['sources'])}")
                print()
                print(f"   Sentiment Breakdown:")
                print(f"     Positive: {data['score_positive']:.3f}")
                print(f"     Negative: {data['score_negative']:.3f}")
                print(f"     Neutral: {data['score_neutral']:.3f}")
                print()
                print(f"   Category Sentiment:")
                print(f"     Regulatory: {data['regulatory_sentiment']:.3f}")
                print(f"     Institutional: {data['institutional_sentiment']:.3f}")
                print(f"     Technical: {data['technical_sentiment']:.3f}")
                print()
                
                if data['top_keywords']:
                    print(f"   Top Keywords:")
                    for word, count in data['top_keywords'][:5]:
                        print(f"     {word}: {count}")
                    print()
                
                if data['top_narratives']:
                    print(f"   Top Narratives: {', '.join(data['top_narratives'])}")
                    print()
            else:
                print(f"   ✗ Request failed: {resp.status_code}")
                print(f"   Error: {resp.text}")
                return
        
        except Exception as e:
            print(f"   ✗ Error: {e}")
            import traceback
            traceback.print_exc()
            return
        
        # Test 3: Compare with symbol-specific sentiment
        print()
        print("3. Comparing with BTC-specific sentiment...")
        print()
        
        try:
            resp = await client.get(f"{base_url}/sentiment/BTCUSDT")
            
            if resp.status_code == 200:
                btc_data = resp.json()
                
                print(f"   BTC Sentiment (1h): {btc_data['score_1h']:.3f}")
                print(f"   BTC Sentiment (24h): {btc_data['score_24h']:.3f}")
                print(f"   BTC Mentions: {btc_data['mentions']}")
                print(f"   BTC Sources: {', '.join(btc_data['sources'])}")
                print()
                
                # Interpretation
                market_sent = data['market_sentiment']
                btc_sent = btc_data['score_1h']
                
                print("   Analysis:")
                if market_sent > 0.2 and btc_sent > 0.2:
                    print("   ✓ Market bullish + BTC bullish → Strong buy signal")
                elif market_sent < -0.2 and btc_sent > 0.2:
                    print("   ⚠ Market bearish but BTC bullish → Cautious buy")
                elif market_sent > 0.2 and btc_sent < -0.2:
                    print("   ⚠ Market bullish but BTC bearish → Avoid BTC")
                elif market_sent < -0.2 and btc_sent < -0.2:
                    print("   ✗ Market bearish + BTC bearish → Strong sell signal")
                else:
                    print("   ○ Neutral signals → Wait for clarity")
            else:
                print(f"   ✗ BTC sentiment request failed: {resp.status_code}")
        
        except Exception as e:
            print(f"   ✗ Error fetching BTC sentiment: {e}")
        
        print()
        print("=" * 60)
        print("Test Complete!")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_market_sentiment())
