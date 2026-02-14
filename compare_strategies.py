import json
import os
import sys
import glob;
from typing import Dict, List
from datetime import datetime

def load_stats(filepath: str) -> Dict:
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        return None

def format_currency(value: float) -> str:
    return f"${value:,.2f}"

def format_percent(value: float) -> str:
    return f"{value:.2f}%"

def calculate_derived_metrics(stats: Dict) -> Dict:
    # Basic metrics
    total_trades = stats.get('total_trades', 0)
    if total_trades == 0:
        return stats
    
    wins = stats.get('winning_trades', 0)
    win_rate = (wins / total_trades) * 100
    
    total_pnl = stats.get('total_pnl', 0.0)
    avg_trade = total_pnl / total_trades
    
    # Calculate Sharpe (simplified if not present)
    # If daily returns are available in stats we could be more precise
    # For now we use what's available
    
    stats['win_rate'] = win_rate
    stats['avg_trade'] = avg_trade
    return stats

def main():
    # Find all stats_*.json files
    files = glob.glob("stats_*.json")
    if not files:
        print("No stats_*.json files found!")
        print("Run the bots with strategies to generate stats files first.")
        return

    results = []
    for f in files:
        data = load_stats(f)
        if data:
            data = calculate_derived_metrics(data)
            # Infer strategy name from filename or content
            name = f.replace("stats_", "").replace(".json", "")
            if 'strategy' in data:
                name = data['strategy']
            
            results.append({
                'name': name,
                'file': f,
                'data': data
            })

    # Print comparison table
    print(f"\n Strategy Comparison Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 100)
    
    headers = [
        "Strategy", 
        "Total Trades", 
        "Win Rate", 
        "Net PnL", 
        "Avg Trade", 
        "Max Drawdown",
        "Sharpe"
    ]
    
    # Print headers
    header_fmt = "{:<20} | {:<12} | {:<10} | {:<15} | {:<12} | {:<12} | {:<8}"
    print(header_fmt.format(*headers))
    print("-" * 100)
    
    for res in results:
        d = res['data']
        row = [
            res['name'][:18],
            d.get('total_trades', 0),
            format_percent(d.get('win_rate', 0)),
            format_currency(d.get('total_pnl', 0)),
            format_currency(d.get('avg_trade', 0)),
            format_percent(d.get('max_drawdown_pct', 0)),
            f"{d.get('sharpe_ratio', 0):.2f}"
        ]
        print(header_fmt.format(*row))
        
    print("=" * 100)
    print(f"Processed {len(results)} strategy files.")

if __name__ == "__main__":
    main()
