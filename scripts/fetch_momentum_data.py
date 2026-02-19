#!/usr/bin/env python3
"""Fetch 4H candle data for the top 20 crypto pairs from Binance.

Uses the public Binance REST API with pagination (limit=1500).
Supports incremental fetch: if a CSV already exists, continues from the last timestamp.
"""

import argparse
import csv
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = "https://api.binance.com/api/v3/klines"

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
    "MATICUSDT", "UNIUSDT", "ATOMUSDT", "LTCUSDT", "ETCUSDT",
    "FILUSDT", "AAVEUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT",
]

INTERVAL = "4h"
LIMIT = 1500
CSV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

# 2020-01-01 00:00:00 UTC in milliseconds
DEFAULT_START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def last_timestamp_ms(filepath: Path) -> int | None:
    """Read the last timestamp from an existing CSV to support incremental fetch."""
    if not filepath.exists():
        return None
    last_ts = None
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            last_ts = row["timestamp"]
    if last_ts is None:
        return None
    # timestamp is ISO string – convert back to epoch ms
    dt = datetime.fromisoformat(last_ts).replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def fetch_klines(symbol: str, start_ms: int) -> list[list]:
    """Fetch all 4H klines from start_ms to now with pagination."""
    all_klines: list[list] = []
    current_ms = start_ms

    while True:
        params = {
            "symbol": symbol,
            "interval": INTERVAL,
            "startTime": current_ms,
            "limit": LIMIT,
        }
        try:
            resp = requests.get(BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            print(f"  Error fetching {symbol}: {e}, retrying in 5s...")
            time.sleep(5)
            continue

        if not data:
            break

        all_klines.extend(data)
        print(f"  {symbol}: fetched {len(all_klines)} candles...", end="\r")

        if len(data) < LIMIT:
            break

        # Next page starts after the last candle's open time
        current_ms = data[-1][0] + 1
        # Respect rate limits
        time.sleep(0.3)

    print(f"  {symbol}: fetched {len(all_klines)} candles total")
    return all_klines


def parse_klines(raw: list[list]) -> list[dict]:
    """Convert raw Binance kline arrays to dicts with proper types."""
    rows = []
    for k in raw:
        ts_ms = k[0]
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        rows.append({
            "timestamp": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        })
    return rows


def deduplicate(rows: list[dict]) -> list[dict]:
    """Remove duplicate timestamps, keeping the last occurrence."""
    seen: dict[str, dict] = {}
    for r in rows:
        seen[r["timestamp"]] = r
    return sorted(seen.values(), key=lambda r: r["timestamp"])


def save_csv(filepath: Path, rows: list[dict], append: bool = False) -> None:
    """Write rows to CSV. If append=True, skip the header."""
    mode = "a" if append else "w"
    with open(filepath, mode, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not append:
            writer.writeheader()
        writer.writerows(rows)


def fetch_symbol(symbol: str, output_dir: Path) -> None:
    """Fetch 4H data for a single symbol with incremental support."""
    filepath = output_dir / f"{symbol}_4h.csv"
    start_ms = DEFAULT_START_MS
    existing_rows: list[dict] = []

    last_ts = last_timestamp_ms(filepath)
    if last_ts is not None:
        # Start from the candle after the last one we have
        start_ms = last_ts + 1
        print(f"  {symbol}: resuming from {datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc)}")

    raw = fetch_klines(symbol, start_ms)
    if not raw:
        print(f"  {symbol}: no new data")
        return

    new_rows = parse_klines(raw)

    if last_ts is not None:
        # Append mode: just add new rows (already deduplicated by start_ms offset)
        save_csv(filepath, new_rows, append=True)
        print(f"  {symbol}: appended {len(new_rows)} new candles → {filepath}")
    else:
        new_rows = deduplicate(new_rows)
        save_csv(filepath, new_rows, append=False)
        print(f"  {symbol}: saved {len(new_rows)} candles → {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description="Fetch 4H candle data for top 20 crypto pairs from Binance"
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Comma-separated symbols (default: all 20)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/momentum",
        help="Output directory (default: data/momentum)",
    )
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else SYMBOLS
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching {INTERVAL} data for {len(symbols)} symbols → {output_dir}/")
    print(f"Start date: 2020-01-01 (incremental if CSV exists)")
    print("=" * 60)

    for i, symbol in enumerate(symbols, 1):
        print(f"\n[{i}/{len(symbols)}] {symbol}")
        fetch_symbol(symbol, output_dir)

    print("\n" + "=" * 60)
    print("Done!")


if __name__ == "__main__":
    main()
