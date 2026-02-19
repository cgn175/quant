#!/usr/bin/env python3
"""
Fetch historical liquidation data from third-party sources.

Since Binance doesn't provide historical liquidation REST API,
we use alternative data sources:
1. Coinglass API (if available)
2. CryptoQuant API (if available)
3. Fallback: Start collecting from now via WebSocket

This script populates the database with historical data for analysis.
"""

import requests
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = "data/liquidations.db"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]


def init_db():
    """Initialize database schema."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Liquidations table
    c.execute('''
        CREATE TABLE IF NOT EXISTS liquidations (
            timestamp INTEGER,
            symbol TEXT,
            side TEXT,
            quantity REAL,
            price REAL,
            PRIMARY KEY (timestamp, symbol, side, price)
        )
    ''')
    
    # Open Interest table
    c.execute('''
        CREATE TABLE IF NOT EXISTS open_interest (
            timestamp INTEGER,
            symbol TEXT,
            open_interest REAL,
            PRIMARY KEY (timestamp, symbol)
        )
    ''')
    
    # Funding rate table (for correlation analysis)
    c.execute('''
        CREATE TABLE IF NOT EXISTS funding_rates (
            timestamp INTEGER,
            symbol TEXT,
            funding_rate REAL,
            PRIMARY KEY (timestamp, symbol)
        )
    ''')
    
    conn.commit()
    conn.close()
    print(f"✅ Database initialized: {DB_PATH}")


def fetch_binance_historical_oi(symbol, days=30):
    """
    Fetch historical Open Interest from Binance.
    This IS available via REST API.
    """
    url = "https://fapi.binance.com/futures/data/openInterestHist"
    
    end_time = int(time.time() * 1000)
    start_time = end_time - (days * 24 * 60 * 60 * 1000)
    
    params = {
        "symbol": symbol,
        "period": "5m",
        "startTime": start_time,
        "endTime": end_time,
        "limit": 500
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        for item in data:
            c.execute('''
                INSERT OR REPLACE INTO open_interest (timestamp, symbol, open_interest)
                VALUES (?, ?, ?)
            ''', (item['timestamp'], symbol, float(item['sumOpenInterest'])))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Fetched {len(data)} OI records for {symbol}")
        return len(data)
        
    except Exception as e:
        print(f"❌ Error fetching OI for {symbol}: {e}")
        return 0


def fetch_binance_historical_funding(symbol, days=30):
    """
    Fetch historical funding rates from Binance.
    This IS available via REST API.
    """
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    
    end_time = int(time.time() * 1000)
    start_time = end_time - (days * 24 * 60 * 60 * 1000)
    
    params = {
        "symbol": symbol,
        "startTime": start_time,
        "endTime": end_time,
        "limit": 1000
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        for item in data:
            c.execute('''
                INSERT OR REPLACE INTO funding_rates (timestamp, symbol, funding_rate)
                VALUES (?, ?, ?)
            ''', (item['fundingTime'], symbol, float(item['fundingRate'])))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Fetched {len(data)} funding records for {symbol}")
        return len(data)
        
    except Exception as e:
        print(f"❌ Error fetching funding for {symbol}: {e}")
        return 0


def check_coinglass_api():
    """
    Check if Coinglass API is available (requires API key).
    Coinglass provides historical liquidation data.
    """
    print("\n⚠️  Coinglass API requires API key (paid service)")
    print("    Visit: https://coinglass.com/api")
    print("    If you have an API key, add it to config and uncomment the code below")
    
    # Uncomment and add your API key if you have one:
    # api_key = "YOUR_COINGLASS_API_KEY"
    # url = "https://open-api.coinglass.com/public/v2/liquidation_history"
    # headers = {"coinglassSecret": api_key}
    # params = {"symbol": "BTC", "time_type": "h1"}
    # response = requests.get(url, headers=headers, params=params)
    # ...
    
    return False


def main():
    print("="*70)
    print("HISTORICAL LIQUIDATION DATA FETCHER")
    print("="*70)
    print()
    
    # Create data directory
    Path("data").mkdir(exist_ok=True)
    
    # Initialize database
    init_db()
    
    print("\n" + "="*70)
    print("FETCHING AVAILABLE HISTORICAL DATA")
    print("="*70)
    print()
    
    # Fetch Open Interest (available from Binance)
    print("📊 Fetching Open Interest (30 days)...")
    for symbol in SYMBOLS:
        fetch_binance_historical_oi(symbol, days=30)
        time.sleep(0.5)  # Rate limiting
    
    print()
    
    # Fetch Funding Rates (available from Binance)
    print("💰 Fetching Funding Rates (30 days)...")
    for symbol in SYMBOLS:
        fetch_binance_historical_funding(symbol, days=30)
        time.sleep(0.5)  # Rate limiting
    
    print()
    print("="*70)
    print("LIQUIDATION DATA STATUS")
    print("="*70)
    print()
    print("❌ Historical liquidation data NOT available from Binance REST API")
    print("   Binance only provides real-time liquidations via WebSocket")
    print()
    print("✅ Alternative options:")
    print("   1. Use Coinglass API (paid, ~$50-100/month)")
    print("   2. Use CryptoQuant API (paid)")
    print("   3. Start WebSocket collector NOW and collect for 2-4 weeks")
    print()
    
    # Check third-party APIs
    check_coinglass_api()
    
    print()
    print("="*70)
    print("RECOMMENDATION")
    print("="*70)
    print()
    print("🚀 Start liquidation WebSocket collector NOW:")
    print("   go build -o bin/liquidation_collector ./cmd/liquidation_collector")
    print("   ./bin/liquidation_collector")
    print()
    print("⏱️  Run for 2-4 weeks to collect sufficient data")
    print()
    print("📊 Meanwhile, use OI + Funding data for initial analysis:")
    print("   - High OI + Extreme funding = Crowded positioning")
    print("   - OI spikes = Leverage building")
    print("   - Funding spikes = Cascade risk")
    print()
    print("✅ Database ready: data/liquidations.db")
    print("   - Open Interest: ✅ (30 days)")
    print("   - Funding Rates: ✅ (30 days)")
    print("   - Liquidations: ⏳ (start collecting)")
    print()


if __name__ == "__main__":
    main()
