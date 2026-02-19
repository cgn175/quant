#!/usr/bin/env python3
"""
Check data collection status for high-alpha strategies.
"""

import sqlite3
import os
from datetime import datetime, timedelta

def check_database(db_path, table_name, time_column="timestamp"):
    """Check database status"""
    if not os.path.exists(db_path):
        return {
            "exists": False,
            "total_rows": 0,
            "last_24h": 0,
            "last_update": None
        }
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Total rows
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    total_rows = cursor.fetchone()[0]
    
    # Last 24h
    cutoff = int((datetime.now() - timedelta(hours=24)).timestamp())
    cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE {time_column} >= ?", (cutoff,))
    last_24h = cursor.fetchone()[0]
    
    # Last update
    cursor.execute(f"SELECT MAX({time_column}) FROM {table_name}")
    last_ts = cursor.fetchone()[0]
    if last_ts and last_ts > 1000000000000:  # Milliseconds
        last_ts = last_ts / 1000
    last_update = datetime.fromtimestamp(last_ts) if last_ts else None
    
    conn.close()
    
    return {
        "exists": True,
        "total_rows": total_rows,
        "last_24h": last_24h,
        "last_update": last_update
    }

def main():
    print("=" * 60)
    print("DATA COLLECTION STATUS")
    print("=" * 60)
    print()
    
    # Check liquidation data
    print("📊 LIQUIDATION DATA")
    print("-" * 60)
    
    liq_db = "data/liquidations.db"
    liq_status = check_database(liq_db, "liquidations")
    oi_status = check_database(liq_db, "open_interest")
    
    if liq_status["exists"]:
        print(f"✅ Database: {liq_db}")
        print(f"   Liquidations: {liq_status['total_rows']:,} total, {liq_status['last_24h']:,} last 24h")
        print(f"   Open Interest: {oi_status['total_rows']:,} total, {oi_status['last_24h']:,} last 24h")
        if liq_status["last_update"]:
            age = datetime.now() - liq_status["last_update"]
            print(f"   Last update: {liq_status['last_update'].strftime('%Y-%m-%d %H:%M:%S')} ({int(age.total_seconds())}s ago)")
            if age.total_seconds() > 300:
                print(f"   ⚠️  No data in last 5 minutes - collector may be down")
    else:
        print(f"❌ Database not found: {liq_db}")
        print("   Run: ./scripts/start_collectors.sh")
    
    print()
    
    # Check order flow data
    print("📊 ORDER FLOW DATA")
    print("-" * 60)
    
    of_db = "data/orderflow.db"
    of_status = check_database(of_db, "order_flow")
    
    if of_status["exists"]:
        print(f"✅ Database: {of_db}")
        print(f"   Records: {of_status['total_rows']:,} total, {of_status['last_24h']:,} last 24h")
        if of_status["last_update"]:
            age = datetime.now() - of_status["last_update"]
            print(f"   Last update: {of_status['last_update'].strftime('%Y-%m-%d %H:%M:%S')} ({int(age.total_seconds())}s ago)")
            if age.total_seconds() > 60:
                print(f"   ⚠️  No data in last minute - collector may be down")
    else:
        print(f"❌ Database not found: {of_db}")
        print("   Run: ./scripts/start_collectors.sh")
    
    print()
    print("=" * 60)
    print("COLLECTION TIMELINE")
    print("=" * 60)
    print()
    
    # Calculate collection progress
    if liq_status["exists"] and liq_status["total_rows"] > 0:
        # Estimate days of data
        if liq_status["last_update"] and oi_status["total_rows"] > 0:
            # Rough estimate: 1 OI record per hour per symbol (4 symbols)
            days_collected = oi_status["total_rows"] / (24 * 4)
            print(f"Liquidation data: ~{days_collected:.1f} days collected")
            
            target_days = 21  # 2-4 weeks, use 3 weeks as target
            if days_collected >= target_days:
                print(f"✅ Sufficient data for backtesting!")
            else:
                remaining = target_days - days_collected
                print(f"⏳ Need {remaining:.1f} more days (target: {target_days} days)")
    
    if of_status["exists"] and of_status["total_rows"] > 0:
        # Estimate days of data
        if of_status["last_update"]:
            # Rough estimate: 60 records per minute per symbol (1s, 5s, 1m windows)
            # 4 symbols * 60 records/min * 60 min/hr * 24 hr/day = 345,600 per day
            days_collected = of_status["total_rows"] / 345600
            print(f"Order flow data: ~{days_collected:.1f} days collected")
            
            target_days = 7  # 1-2 weeks, use 1 week as minimum
            if days_collected >= target_days:
                print(f"✅ Sufficient data for backtesting!")
            else:
                remaining = target_days - days_collected
                print(f"⏳ Need {remaining:.1f} more days (target: {target_days} days)")
    
    print()
    print("=" * 60)
    print("COMMANDS")
    print("=" * 60)
    print()
    print("Start collectors:")
    print("  ./scripts/start_collectors.sh")
    print()
    print("Check logs:")
    print("  tail -f logs/liquidation_collector.log")
    print("  tail -f logs/orderflow_collector.log")
    print()
    print("Stop collectors:")
    print("  pkill liquidation_collector")
    print("  pkill orderflow_collector")
    print()

if __name__ == "__main__":
    main()
