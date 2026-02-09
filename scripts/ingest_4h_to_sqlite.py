#!/usr/bin/env python3
"""Ingest 4H candle and funding rate parquet data into SQLite for ML training."""

import argparse
import glob
import os
import re
import sqlite3
import time
from datetime import datetime, timezone

import pandas as pd

FOUR_HOURS_MS = 4 * 60 * 60 * 1000

CANDLE_FILES = "data_4h/*_USDT_4h_2190d.parquet"
FUNDING_FILES = "data_4h/funding/*_USDT_funding_2190d.parquet"

CREATE_CANDLES_TABLE = """
CREATE TABLE IF NOT EXISTS candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    open_time INTEGER NOT NULL,
    close_time INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    is_closed INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE(symbol, open_time)
);
"""

CREATE_FUNDING_TABLE = """
CREATE TABLE IF NOT EXISTS funding (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    funding_rate REAL NOT NULL,
    UNIQUE(symbol, timestamp)
);
"""

CREATE_FUNDING_INDEX = """
CREATE INDEX IF NOT EXISTS idx_funding_symbol_time ON funding(symbol, timestamp DESC);
"""


def symbol_from_filename(filename: str) -> str:
    base = os.path.basename(filename)
    match = re.match(r"([A-Z]+)_([A-Z]+)", base)
    if not match:
        raise ValueError(f"Cannot parse symbol from filename: {base}")
    return match.group(1) + match.group(2)


def ingest_candles(conn: sqlite3.Connection, root: str) -> dict:
    conn.execute(CREATE_CANDLES_TABLE)
    created_at = int(time.time() * 1000)
    stats = {}

    for path in sorted(glob.glob(os.path.join(root, CANDLE_FILES))):
        symbol = symbol_from_filename(path)
        df = pd.read_parquet(path)
        df.index = pd.to_datetime(df.index)

        records = []
        for ts, row in df.iterrows():
            open_time = int(ts.timestamp() * 1000)
            close_time = open_time + FOUR_HOURS_MS - 1
            records.append((
                symbol, open_time, close_time,
                row["open"], row["high"], row["low"], row["close"],
                row["volume"], 1, created_at,
            ))

        conn.executemany(
            "INSERT OR REPLACE INTO candles "
            "(symbol, open_time, close_time, open, high, low, close, volume, is_closed, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            records,
        )
        conn.commit()
        stats[symbol] = len(records)
        print(f"  Candles: {symbol} — {len(records)} rows ingested")

    return stats


def ingest_funding(conn: sqlite3.Connection, root: str) -> dict:
    conn.execute(CREATE_FUNDING_TABLE)
    conn.execute(CREATE_FUNDING_INDEX)
    stats = {}

    for path in sorted(glob.glob(os.path.join(root, FUNDING_FILES))):
        symbol = symbol_from_filename(path)
        df = pd.read_parquet(path)
        df.index = pd.to_datetime(df.index)

        records = []
        for ts, row in df.iterrows():
            ts_ms = int(ts.timestamp() * 1000)
            records.append((symbol, ts_ms, row["fundingRate"]))

        conn.executemany(
            "INSERT OR REPLACE INTO funding (symbol, timestamp, funding_rate) VALUES (?, ?, ?)",
            records,
        )
        conn.commit()
        stats[symbol] = len(records)
        print(f"  Funding: {symbol} — {len(records)} rows ingested")

    return stats


def print_verification(conn: sqlite3.Connection):
    print("\n" + "=" * 70)
    print("VERIFICATION — Candles")
    print("=" * 70)
    rows = conn.execute(
        "SELECT symbol, COUNT(*) as cnt, MIN(open_time) as min_t, MAX(open_time) as max_t "
        "FROM candles GROUP BY symbol ORDER BY symbol"
    ).fetchall()
    for symbol, cnt, min_t, max_t in rows:
        min_dt = datetime.fromtimestamp(min_t / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        max_dt = datetime.fromtimestamp(max_t / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        days = (max_t - min_t) / 1000 / 86400
        print(f"  {symbol:>10}  {cnt:>6} rows  |  {min_dt}  →  {max_dt}  ({days:.0f} days)")

    print("\n" + "=" * 70)
    print("VERIFICATION — Funding")
    print("=" * 70)
    rows = conn.execute(
        "SELECT symbol, COUNT(*) as cnt, MIN(timestamp) as min_t, MAX(timestamp) as max_t "
        "FROM funding GROUP BY symbol ORDER BY symbol"
    ).fetchall()
    for symbol, cnt, min_t, max_t in rows:
        min_dt = datetime.fromtimestamp(min_t / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        max_dt = datetime.fromtimestamp(max_t / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        days = (max_t - min_t) / 1000 / 86400
        print(f"  {symbol:>10}  {cnt:>6} rows  |  {min_dt}  →  {max_dt}  ({days:.0f} days)")


def main():
    parser = argparse.ArgumentParser(description="Ingest 4H parquet data into SQLite")
    parser.add_argument("--db-path", default="data/training.db", help="Path to SQLite DB (default: data/training.db)")
    args = parser.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(root, args.db_path) if not os.path.isabs(args.db_path) else args.db_path

    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    print(f"Database: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    print("\nIngesting candle data...")
    ingest_candles(conn, root)

    print("\nIngesting funding data...")
    ingest_funding(conn, root)

    print_verification(conn)
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
