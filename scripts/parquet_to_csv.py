#!/usr/bin/env python3
"""Convert parquet files to CSV for Go backtest"""

import sys
from pathlib import Path

import pandas as pd

def convert_parquet_to_csv(parquet_file):
    """Convert a single parquet file to CSV"""
    csv_file = parquet_file.with_suffix(".csv")

    print(f"Converting {parquet_file.name}...")
    df = pd.read_parquet(parquet_file)

    # Reset index to make timestamp a column
    df = df.reset_index()

    # Ensure column order: timestamp, open, high, low, close, volume
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]

    # Save to CSV
    df.to_csv(csv_file, index=False)
    print(f"  -> {csv_file.name} ({len(df):,} rows)")

    return csv_file


def main():
    if len(sys.argv) < 2:
        data_dir = Path("data365")
    else:
        data_dir = Path(sys.argv[1])

    if not data_dir.exists():
        print(f"Error: directory {data_dir} not found")
        sys.exit(1)

    parquet_files = list(data_dir.glob("*.parquet"))

    if not parquet_files:
        print(f"No parquet files found in {data_dir}")
        sys.exit(1)

    print(f"Found {len(parquet_files)} parquet files\n")

    for pq_file in sorted(parquet_files):
        convert_parquet_to_csv(pq_file)

    print(f"\n✓ Converted {len(parquet_files)} files")


    print(f"\n✓ Converted {len(parquet_files)} files")

if __name__ == "__main__":
    main()
