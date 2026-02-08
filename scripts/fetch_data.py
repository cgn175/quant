#!/usr/bin/env python3
"""Fetch historical OHLCV data from Binance."""

import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path

import ccxt
import pandas as pd


def fetch_ohlcv(
    symbol: str,
    timeframe: str = "1m",
    days: int = 180,
    output_dir: Path = Path("data"),
) -> pd.DataFrame:
    exchange = ccxt.binance({"enableRateLimit": True})

    since = exchange.parse8601((datetime.utcnow() - timedelta(days=days)).isoformat())

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


def fetch_funding_rates(
    symbol: str,
    days: int = 730,
    output_dir: Path = Path("data_4h/funding"),
) -> pd.DataFrame:
    """Fetch funding rate history via CCXT.

    Args:
        symbol: Trading pair (e.g., "BTC/USDT").
        days: Number of days of history to fetch.
        output_dir: Directory to save parquet output.

    Returns:
        DataFrame with columns: timestamp (index), symbol, fundingRate.
    """
    exchange = ccxt.binance(
        {"enableRateLimit": True, "options": {"defaultType": "future"}}
    )

    since = exchange.parse8601((datetime.utcnow() - timedelta(days=days)).isoformat())

    all_rates: list[dict] = []
    limit = 1000

    print(f"Fetching {symbol} funding rates for {days} days...")

    while True:
        try:
            rates = exchange.fetch_funding_rate_history(
                symbol, since=since, limit=limit
            )
            if not rates:
                break

            all_rates.extend(rates)
            since = rates[-1]["timestamp"] + 1

            print(f"  Fetched {len(all_rates)} records...", end="\r")

            if len(rates) < limit:
                break

            time.sleep(exchange.rateLimit / 1000)

        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)
            continue

    print(f"\nTotal: {len(all_rates)} funding rate records")

    if not all_rates:
        print(f"  No funding rate data available for {symbol}")
        return pd.DataFrame(columns=["symbol", "fundingRate"])

    df = pd.DataFrame(
        [
            {
                "timestamp": r["timestamp"],
                "symbol": symbol,
                "fundingRate": r.get("fundingRate", 0.0),
            }
            for r in all_rates
        ]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df = df.set_index("timestamp")
    df = df[~df.index.duplicated(keep="last")]
    df = df.sort_index()

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{symbol.replace('/', '_')}_funding_{days}d.parquet"
    filepath = output_dir / filename
    df.to_parquet(filepath)
    print(f"Saved to {filepath}")

    return df


def fetch_daily_ohlcv(
    symbol: str,
    days: int = 730,
    output_dir: Path = Path("data_daily"),
) -> pd.DataFrame:
    """Fetch daily OHLCV candles.

    Args:
        symbol: Trading pair (e.g., "BTC/USDT").
        days: Number of days of history to fetch.
        output_dir: Directory to save parquet output.

    Returns:
        DataFrame with OHLCV columns indexed by timestamp.
    """
    exchange = ccxt.binance({"enableRateLimit": True})

    since = exchange.parse8601((datetime.utcnow() - timedelta(days=days)).isoformat())

    all_ohlcv: list[list] = []
    limit = 1000

    print(f"Fetching {symbol} 1d data for {days} days...")

    while True:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, "1d", since=since, limit=limit)
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

    print(f"\nTotal: {len(all_ohlcv)} daily candles")

    df = pd.DataFrame(
        all_ohlcv,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df = df.set_index("timestamp")
    df = df[~df.index.duplicated(keep="last")]
    df = df.sort_index()

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{symbol.replace('/', '_')}_1d_{days}d.parquet"
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
    parser.add_argument(
        "--add-funding",
        action="store_true",
        help="Also fetch funding rate history (default 730 days)",
    )
    parser.add_argument(
        "--add-daily",
        action="store_true",
        help="Also fetch daily OHLCV candles (default 730 days)",
    )
    parser.add_argument(
        "--extra-days",
        type=int,
        default=730,
        help="Days of history for funding/daily data (default: 730)",
    )

    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")]
    output_dir = Path(args.output)

    for symbol in symbols:
        fetch_ohlcv(symbol, args.timeframe, args.days, output_dir)
        print()

    if args.add_funding:
        print("=" * 60)
        print("Fetching funding rates...")
        print("=" * 60)
        funding_dir = output_dir / "funding"
        for symbol in symbols:
            fetch_funding_rates(symbol, args.extra_days, funding_dir)
            print()

    if args.add_daily:
        print("=" * 60)
        print("Fetching daily OHLCV...")
        print("=" * 60)
        daily_dir = Path("data_daily")
        for symbol in symbols:
            fetch_daily_ohlcv(symbol, args.extra_days, daily_dir)
            print()


if __name__ == "__main__":
    main()
