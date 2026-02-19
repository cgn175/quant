#!/usr/bin/env python3
"""
Momentum Filter Validation Script

Validates that the momentum filter is working correctly in paper trading.

Usage:
    python3 scripts/validate_momentum.py
"""

import sqlite3
import pandas as pd
from datetime import datetime, timedelta

def main():
    print("=" * 60)
    print("MOMENTUM FILTER VALIDATION")
    print("=" * 60)
    print()
    
    # Check if momentum data exists
    try:
        # Read from CSV file
        df = pd.read_csv("results/momentum_scores.csv")
        
        if df.empty:
            print("❌ No momentum data found")
            print("   Run: python3 scripts/calculate_momentum.py")
            return
        
        print("✅ Latest Momentum Rankings:")
        print()
        for _, row in df.iterrows():
            print(f"   {int(row['rank'])}. {row['symbol']}: {row['momentum_score']:.4f}")
        
        print()
        print("-" * 60)
        
        # Check which symbols should be trading
        top_n = 2  # From config: momentum_filter.top_n
        top_symbols = df.nsmallest(top_n, 'rank')['symbol'].tolist()
        
        print(f"📊 Top {top_n} symbols (should be trading):")
        for sym in top_symbols:
            print(f"   ✅ {sym}")
        
        print()
        blocked_symbols = df[~df['symbol'].isin(top_symbols)]['symbol'].tolist()
        print(f"🚫 Blocked symbols (should NOT trade):")
        for sym in blocked_symbols:
            print(f"   ❌ {sym}")
        
        print()
        print("-" * 60)
        print("VALIDATION CHECKLIST")
        print("-" * 60)
        print()
        print("[ ] Bot is running with momentum filter enabled")
        print("[ ] Only top 2 symbols are generating signals")
        print("[ ] Other symbols show 'momentum filter blocked' in logs")
        print("[ ] No errors in bot logs")
        print()
        print("To check logs:")
        print("  grep 'momentum' logs/bot.log | tail -20")
        print("  grep 'signal blocked' logs/bot.log | tail -20")
        print()
        
    except FileNotFoundError:
        print("❌ Momentum scores file not found")
        print()
        print("Run momentum calculation first:")
        print("  python3 scripts/calculate_momentum.py")
        print()
    except Exception as e:
        print(f"❌ Error: {e}")
        print()
    
    print("=" * 60)

if __name__ == "__main__":
    main()
