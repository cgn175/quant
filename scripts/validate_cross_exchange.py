#!/usr/bin/env python3
"""
Quick validation script for cross-exchange arbitrage opportunities.
Tests opportunity detection without placing real orders.
"""

import requests
import time
from datetime import datetime

def get_binance_funding():
    """Get Binance funding rate"""
    url = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
    resp = requests.get(url)
    data = resp.json()
    return float(data['lastFundingRate'])

def get_bybit_funding():
    """Get Bybit funding rate"""
    url = "https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT"
    resp = requests.get(url)
    data = resp.json()
    return float(data['result']['list'][0]['fundingRate'])

def get_okx_funding():
    """Get OKX funding rate"""
    url = "https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP"
    resp = requests.get(url)
    data = resp.json()
    return float(data['data'][0]['fundingRate'])

def get_binance_perp_price():
    """Get Binance perp price"""
    url = "https://fapi.binance.com/fapi/v1/ticker/price?symbol=BTCUSDT"
    resp = requests.get(url)
    return float(resp.json()['price'])

def get_bybit_perp_price():
    """Get Bybit perp price"""
    url = "https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT"
    resp = requests.get(url)
    data = resp.json()
    return float(data['result']['list'][0]['lastPrice'])

def get_okx_perp_price():
    """Get OKX perp price"""
    url = "https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT-SWAP"
    resp = requests.get(url)
    return float(resp.json()['data'][0]['last'])

def main():
    print("=" * 60)
    print("CROSS-EXCHANGE ARBITRAGE VALIDATION")
    print("=" * 60)
    print()
    
    # Fetch data from all exchanges
    print("Fetching data from exchanges...")
    
    try:
        binance_funding = get_binance_funding()
        binance_price = get_binance_perp_price()
        print(f"✅ Binance: Funding={binance_funding:.6f} ({binance_funding*100:.4f}%), Price=${binance_price:,.2f}")
    except Exception as e:
        print(f"❌ Binance error: {e}")
        binance_funding = None
        binance_price = None
    
    try:
        bybit_funding = get_bybit_funding()
        bybit_price = get_bybit_perp_price()
        print(f"✅ Bybit:   Funding={bybit_funding:.6f} ({bybit_funding*100:.4f}%), Price=${bybit_price:,.2f}")
    except Exception as e:
        print(f"❌ Bybit error: {e}")
        bybit_funding = None
        bybit_price = None
    
    try:
        okx_funding = get_okx_funding()
        okx_price = get_okx_perp_price()
        print(f"✅ OKX:     Funding={okx_funding:.6f} ({okx_funding*100:.4f}%), Price=${okx_price:,.2f}")
    except Exception as e:
        print(f"❌ OKX error: {e}")
        okx_funding = None
        okx_price = None
    
    print()
    print("-" * 60)
    print("ARBITRAGE OPPORTUNITIES")
    print("-" * 60)
    
    # Find funding rate arbitrage opportunities
    exchanges = []
    if binance_funding is not None:
        exchanges.append(("Binance", binance_funding, binance_price))
    if bybit_funding is not None:
        exchanges.append(("Bybit", bybit_funding, bybit_price))
    if okx_funding is not None:
        exchanges.append(("OKX", okx_funding, okx_price))
    
    if len(exchanges) < 2:
        print("❌ Need at least 2 exchanges to find arbitrage")
        return
    
    # Sort by funding rate
    exchanges.sort(key=lambda x: x[1])
    
    lowest = exchanges[0]
    highest = exchanges[-1]
    
    spread = highest[1] - lowest[1]
    spread_pct = spread * 100
    spread_apy = spread * 365 * 3 * 100  # 3 funding periods per day
    
    print()
    print(f"📊 Funding Rate Spread:")
    print(f"   Lowest:  {lowest[0]} = {lowest[1]:.6f} ({lowest[1]*100:.4f}%)")
    print(f"   Highest: {highest[0]} = {highest[1]:.6f} ({highest[1]*100:.4f}%)")
    print(f"   Spread:  {spread:.6f} ({spread_pct:.4f}%)")
    print(f"   APY:     {spread_apy:.2f}%")
    print()
    
    # Check if opportunity exists
    min_threshold = 0.0001  # 0.01% per 8h
    if spread >= min_threshold:
        print(f"✅ OPPORTUNITY DETECTED!")
        print(f"   Strategy: SHORT {highest[0]} + LONG {lowest[0]}")
        print(f"   Expected profit: {spread_pct:.4f}% per 8h")
        print(f"   Annualized: {spread_apy:.2f}% APY")
    else:
        print(f"❌ No opportunity (spread {spread_pct:.4f}% < threshold {min_threshold*100:.4f}%)")
    
    print()
    print("-" * 60)
    print("PRICE ARBITRAGE")
    print("-" * 60)
    
    # Check price differences
    if len(exchanges) >= 2:
        price_exchanges = [(name, price) for name, _, price in exchanges]
        price_exchanges.sort(key=lambda x: x[1])
        
        lowest_price = price_exchanges[0]
        highest_price = price_exchanges[-1]
        
        price_diff = highest_price[1] - lowest_price[1]
        price_diff_pct = (price_diff / lowest_price[1]) * 100
        
        print()
        print(f"📊 Price Spread:")
        print(f"   Lowest:  {lowest_price[0]} = ${lowest_price[1]:,.2f}")
        print(f"   Highest: {highest_price[0]} = ${highest_price[1]:,.2f}")
        print(f"   Spread:  ${price_diff:,.2f} ({price_diff_pct:.4f}%)")
        print()
        
        if price_diff_pct > 0.1:  # 0.1% price difference
            print(f"✅ PRICE ARBITRAGE DETECTED!")
            print(f"   Strategy: BUY {lowest_price[0]} + SELL {highest_price[0]}")
            print(f"   Profit: {price_diff_pct:.4f}%")
        else:
            print(f"❌ No price arbitrage (spread {price_diff_pct:.4f}% < 0.1%)")
    
    print()
    print("=" * 60)
    print(f"Validation complete at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

if __name__ == "__main__":
    main()
