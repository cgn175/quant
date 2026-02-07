#!/usr/bin/env python3
"""Fetch historical OHLCV data from Binance."""

import argparse
import ccxt
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import time


def fetch_ohlcv(
    symbol: str,
    timeframe: str = "1m",
    days: int = 180,
    output_dir: Path = Path("data"),
) -> pd.DataFrame:
    exchange = ccxt.binance({"enableRateLimit": True})
    
    since = exchange.parse8601(
        (datetime.utcnow() - timedelta(days=days)).isoformat()
    )
    
    all_ohlcv = []
    limit = 1000
    
    print(f"Fetching {symbol} {timeframe} data for {days} days...")
    
    while True:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            if not ohlcv:
                break
            
            all_ohlcv.extend(ohlcv)
            since = ohlcv[-1][0] + 1
            
            print(f"  Fetched {len(all_ohlcv)} candles...", end="\r")
            
            if len(ohlcv) < limit:
                break
                
            time.sleep(exchange.rateLimit / 1000)
            
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)
            continue
    
    print(f"\nTotal: {len(all_ohlcv)} candles")
    
    df = pd.DataFrame(
        all_ohlcv,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df = df.set_index("timestamp")
    df = df[~df.index.duplicated(keep="last")]
    df = df.sort_index()
    
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{symbol.replace('/', '_')}_{timeframe}_{days}d.parquet"
    filepath = output_dir / filename
    df.to_parquet(filepath)
    print(f"Saved to {filepath}")
    
    return df


def main():
    parser = argparse.ArgumentParser(description="Fetch historical OHLCV data")
    parser.add_argument(
        "--symbols",
        type=str,
        default="BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT",
        help="Comma-separated symbols",
    )
    parser.add_argument("--timeframe", type=str, default="1m", help="Timeframe")
    parser.add_argument("--days", type=int, default=180, help="Days of history")
    parser.add_argument("--output", type=str, default="data", help="Output directory")
    
    args = parser.parse_args()
    
    symbols = [s.strip() for s in args.symbols.split(",")]
    output_dir = Path(args.output)
    
    for symbol in symbols:
        fetch_ohlcv(symbol, args.timeframe, args.days, output_dir)
        print()


if __name__ == "__main__":
    main()
