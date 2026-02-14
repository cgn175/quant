#!/usr/bin/env python3
"""
Compare trading strategy performance from JSON stats files.

Usage:
    python compare_stats.py stats_trend_*.json stats_market_making_*.json
"""

import json
import sys
from typing import List, Dict

def load_stats(filepath: str) -> Dict:
    with open(filepath, 'r') as f:
        return json.load(f)

def compare_stats(stats_files: List[str]):
    if len(stats_files) < 2:
        print("Error: Provide at least 2 stats files to compare")
        sys.exit(1)

    stats_list = []
    for filepath in stats_files:
        try:
            stats = load_stats(filepath)
            stats_list.append((filepath, stats))
        except Exception as e:
            print(f"Error loading {filepath}: {e}")
            continue

    if len(stats_list) < 2:
        print("Error: Could not load enough stats files")
        sys.exit(1)

    # Print comparison table
    print("\nStrategy Comparison Report")
    print("=" * 80)
    
    # Header
    header = f"{'Metric':<20}"
    for filepath, stats in stats_list:
        header += f" | {stats['strategy'][:18]:>18}"
    print(header)
    print("-" * 80)

    # Metrics
    metrics = [
        ("Total Trades", "total_trades", "{}"),
        ("Winning Trades", "winning_trades", "{}"),
        ("Losing Trades", "losing_trades", "{}"),
        ("Win Rate", "win_rate", "{:.1%}"),
        ("Net PnL", "net_pnl", "${:.2f}"),
        ("Avg Trade PnL", "avg_trade_pnl", "${:.2f}"),
        ("Profit Factor", "profit_factor", "{:.2f}"),
    ]

    for label, key, fmt in metrics:
        row = f"{label:<20}"
        for _, stats in stats_list:
            value = stats.get(key, 0)
            row += f" | {fmt.format(value):>18}"
        print(row)

    print("=" * 80)

    # Summary
    print("\nDuration:")
    for filepath, stats in stats_list:
        start = stats.get('start_time', 'N/A')
        end = stats.get('end_time', 'N/A')
        print(f"  {stats['strategy']}: {start} -> {end}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    compare_stats(sys.argv[1:])
