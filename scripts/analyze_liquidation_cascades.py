#!/usr/bin/env python3
"""
Liquidation Cascade Pattern Analysis

Analyzes collected liquidation and open interest data to identify:
1. Liquidation cascade events
2. Crowded positioning signals  
3. Cascade exhaustion patterns
4. Trading opportunities

Usage:
    python analyze_liquidation_cascades.py --db liquidations.db --days 14
"""

import sqlite3
import pandas as pd
import numpy as np
import argparse
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import seaborn as sns

def load_data(db_path, days=14):
    """Load liquidation and open interest data from SQLite"""
    conn = sqlite3.connect(db_path)
    
    # Calculate time range
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)
    start_ts = int(start_time.timestamp() * 1000)
    end_ts = int(end_time.timestamp() * 1000)
    
    # Load liquidations
    liq_query = """
    SELECT timestamp, symbol, side, quantity, price, avg_price, filled_qty
    FROM liquidations 
    WHERE timestamp BETWEEN ? AND ?
    ORDER BY timestamp
    """
    liquidations = pd.read_sql_query(liq_query, conn, params=(start_ts, end_ts))
    liquidations['datetime'] = pd.to_datetime(liquidations['timestamp'], unit='ms')
    
    # Load open interest
    oi_query = """
    SELECT timestamp, symbol, open_interest
    FROM open_interest 
    WHERE timestamp BETWEEN ? AND ?
    ORDER BY timestamp
    """
    open_interest = pd.read_sql_query(oi_query, conn, params=(start_ts, end_ts))
    open_interest['datetime'] = pd.to_datetime(open_interest['timestamp'], unit='ms')
    
    conn.close()
    return liquidations, open_interest

def detect_cascade_events(liquidations, window_minutes=30, min_volume_usd=10_000_000):
    """Detect liquidation cascade events"""
    cascades = []
    
    for symbol in liquidations['symbol'].unique():
        symbol_liq = liquidations[liquidations['symbol'] == symbol].copy()
        symbol_liq = symbol_liq.sort_values('timestamp')
        
        # Calculate USD volume
        symbol_liq['usd_volume'] = symbol_liq['filled_qty'] * symbol_liq['avg_price']
        
        # Rolling window analysis
        symbol_liq.set_index('datetime', inplace=True)
        window = f'{window_minutes}min'
        
        # Aggregate by window
        agg_data = symbol_liq.groupby([pd.Grouper(freq=window), 'side']).agg({
            'usd_volume': 'sum',
            'filled_qty': 'sum',
            'avg_price': 'mean'
        }).reset_index()
        
        # Detect cascades (high volume in short time)
        for side in ['SELL', 'BUY']:
            side_data = agg_data[agg_data['side'] == side]
            if len(side_data) == 0:
                continue
                
            # Find volume spikes
            volume_threshold = side_data['usd_volume'].quantile(0.95)
            volume_threshold = max(volume_threshold, min_volume_usd)
            
            cascade_windows = side_data[side_data['usd_volume'] > volume_threshold]
            
            for _, window_data in cascade_windows.iterrows():
                cascades.append({
                    'symbol': symbol,
                    'datetime': window_data['datetime'],
                    'side': side,
                    'liquidation_type': 'Long Squeeze' if side == 'SELL' else 'Short Squeeze',
                    'usd_volume': window_data['usd_volume'],
                    'quantity': window_data['filled_qty'],
                    'avg_price': window_data['avg_price'],
                    'window_minutes': window_minutes
                })
    
    return pd.DataFrame(cascades)

def analyze_oi_patterns(open_interest):
    """Analyze open interest patterns for crowded positioning"""
    oi_analysis = []
    
    for symbol in open_interest['symbol'].unique():
        symbol_oi = open_interest[open_interest['symbol'] == symbol].copy()
        symbol_oi = symbol_oi.sort_values('timestamp')
        
        if len(symbol_oi) < 10:  # Need minimum data
            continue
            
        # Calculate OI changes
        symbol_oi['oi_change'] = symbol_oi['open_interest'].pct_change()
        symbol_oi['oi_change_abs'] = symbol_oi['open_interest'].diff()
        
        # Rolling statistics
        symbol_oi['oi_ma_24h'] = symbol_oi['open_interest'].rolling(window=288, min_periods=1).mean()  # 24h at 5min intervals
        symbol_oi['oi_std_24h'] = symbol_oi['open_interest'].rolling(window=288, min_periods=1).std()
        
        # Detect extreme OI levels
        current_oi = symbol_oi.iloc[-1]['open_interest']
        oi_percentile = (symbol_oi['open_interest'] <= current_oi).mean() * 100
        
        # Recent OI trend
        recent_change = symbol_oi.tail(12)['oi_change'].mean()  # Last hour average
        
        oi_analysis.append({
            'symbol': symbol,
            'current_oi': current_oi,
            'oi_percentile': oi_percentile,
            'recent_change_pct': recent_change * 100,
            'is_extreme_high': oi_percentile > 90,
            'is_rapid_growth': recent_change > 0.05,  # >5% growth in last hour
            'crowding_score': oi_percentile + (recent_change * 1000)  # Combined score
        })
    
    return pd.DataFrame(oi_analysis)

def generate_cascade_signals(liquidations, open_interest):
    """Generate trading signals based on cascade patterns"""
    signals = []
    
    # Detect recent cascades (last 24 hours)
    recent_time = datetime.now() - timedelta(hours=24)
    recent_liq = liquidations[liquidations['datetime'] > recent_time]
    
    cascades = detect_cascade_events(recent_liq, window_minutes=15, min_volume_usd=5_000_000)
    oi_analysis = analyze_oi_patterns(open_interest)
    
    for symbol in liquidations['symbol'].unique():
        symbol_cascades = cascades[cascades['symbol'] == symbol]
        symbol_oi = oi_analysis[oi_analysis['symbol'] == symbol]
        
        if len(symbol_oi) == 0:
            continue
            
        oi_data = symbol_oi.iloc[0]
        
        # Recent cascade activity
        recent_long_squeeze = len(symbol_cascades[symbol_cascades['liquidation_type'] == 'Long Squeeze'])
        recent_short_squeeze = len(symbol_cascades[symbol_cascades['liquidation_type'] == 'Short Squeeze'])
        
        # Generate signals
        signal_strength = 0
        signal_type = 'NEUTRAL'
        reasoning = []
        
        # High OI + Recent long liquidations = More long squeeze risk
        if oi_data['is_extreme_high'] and recent_long_squeeze > 0:
            signal_strength += 2
            signal_type = 'BEARISH'
            reasoning.append(f"High OI ({oi_data['oi_percentile']:.1f}%ile) + {recent_long_squeeze} long squeezes")
        
        # High OI + Recent short liquidations = More short squeeze risk  
        if oi_data['is_extreme_high'] and recent_short_squeeze > 0:
            signal_strength += 2
            signal_type = 'BULLISH'
            reasoning.append(f"High OI ({oi_data['oi_percentile']:.1f}%ile) + {recent_short_squeeze} short squeezes")
        
        # Rapid OI growth = Building leverage
        if oi_data['is_rapid_growth']:
            signal_strength += 1
            reasoning.append(f"Rapid OI growth ({oi_data['recent_change_pct']:.1f}%)")
        
        signals.append({
            'symbol': symbol,
            'signal_type': signal_type,
            'signal_strength': signal_strength,
            'crowding_score': oi_data['crowding_score'],
            'current_oi': oi_data['current_oi'],
            'oi_percentile': oi_data['oi_percentile'],
            'recent_long_squeezes': recent_long_squeeze,
            'recent_short_squeezes': recent_short_squeeze,
            'reasoning': '; '.join(reasoning)
        })
    
    return pd.DataFrame(signals)

def create_visualizations(liquidations, open_interest, cascades, output_dir='./'):
    """Create analysis visualizations"""
    
    # 1. Liquidation volume by symbol and type
    plt.figure(figsize=(12, 8))
    
    # Calculate daily liquidation volumes
    liquidations['date'] = liquidations['datetime'].dt.date
    liquidations['usd_volume'] = liquidations['filled_qty'] * liquidations['avg_price']
    
    daily_liq = liquidations.groupby(['date', 'symbol', 'side'])['usd_volume'].sum().reset_index()
    daily_liq['liquidation_type'] = daily_liq['side'].map({'SELL': 'Long Squeeze', 'BUY': 'Short Squeeze'})
    
    # Plot
    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    symbols = liquidations['symbol'].unique()[:4]  # Top 4 symbols
    
    for i, symbol in enumerate(symbols):
        ax = axes[i//2, i%2]
        symbol_data = daily_liq[daily_liq['symbol'] == symbol]
        
        if len(symbol_data) > 0:
            pivot_data = symbol_data.pivot_table(
                index='date', 
                columns='liquidation_type', 
                values='usd_volume', 
                fill_value=0
            )
            pivot_data.plot(kind='bar', stacked=True, ax=ax, color=['red', 'green'])
            ax.set_title(f'{symbol} Daily Liquidations')
            ax.set_ylabel('USD Volume')
            ax.tick_params(axis='x', rotation=45)
    
    plt.tight_layout()
    plt.savefig(f'{output_dir}/liquidation_analysis.png', dpi=300, bbox_inches='tight')
    plt.close()
    
    # 2. Open Interest trends
    plt.figure(figsize=(12, 6))
    for symbol in open_interest['symbol'].unique():
        symbol_oi = open_interest[open_interest['symbol'] == symbol]
        plt.plot(symbol_oi['datetime'], symbol_oi['open_interest'], label=symbol, linewidth=2)
    
    plt.title('Open Interest Trends')
    plt.xlabel('Date')
    plt.ylabel('Open Interest')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(f'{output_dir}/open_interest_trends.png', dpi=300, bbox_inches='tight')
    plt.close()

def main():
    parser = argparse.ArgumentParser(description='Analyze liquidation cascade patterns')
    parser.add_argument('--db', default='liquidations.db', help='SQLite database path')
    parser.add_argument('--days', type=int, default=14, help='Days of data to analyze')
    parser.add_argument('--output', default='./', help='Output directory for reports')
    args = parser.parse_args()
    
    print(f"Loading data from {args.db} (last {args.days} days)...")
    
    try:
        liquidations, open_interest = load_data(args.db, args.days)
    except Exception as e:
        print(f"Error loading data: {e}")
        return
    
    if len(liquidations) == 0:
        print("No liquidation data found. Make sure the collector is running and has collected data.")
        return
    
    print(f"Loaded {len(liquidations)} liquidation events and {len(open_interest)} OI records")
    
    # Analysis
    print("\n=== LIQUIDATION CASCADE ANALYSIS ===")
    
    # Detect cascades
    cascades = detect_cascade_events(liquidations)
    print(f"\nDetected {len(cascades)} cascade events:")
    if len(cascades) > 0:
        print(cascades.groupby(['symbol', 'liquidation_type']).agg({
            'usd_volume': ['count', 'sum', 'mean']
        }).round(2))
    
    # OI analysis
    oi_analysis = analyze_oi_patterns(open_interest)
    print(f"\n=== OPEN INTEREST ANALYSIS ===")
    if len(oi_analysis) > 0:
        print(oi_analysis[['symbol', 'oi_percentile', 'recent_change_pct', 'is_extreme_high', 'crowding_score']].round(2))
    
    # Generate signals
    signals = generate_cascade_signals(liquidations, open_interest)
    print(f"\n=== TRADING SIGNALS ===")
    if len(signals) > 0:
        active_signals = signals[signals['signal_strength'] > 0]
        if len(active_signals) > 0:
            print(active_signals[['symbol', 'signal_type', 'signal_strength', 'reasoning']])
        else:
            print("No active signals detected")
    
    # Create visualizations
    print(f"\nGenerating visualizations in {args.output}...")
    create_visualizations(liquidations, open_interest, cascades, args.output)
    
    # Summary statistics
    print(f"\n=== SUMMARY STATISTICS ===")
    print(f"Total liquidation volume: ${liquidations['filled_qty'].sum() * liquidations['avg_price'].mean():,.0f}")
    print(f"Average cascade size: ${cascades['usd_volume'].mean():,.0f}" if len(cascades) > 0 else "No cascades detected")
    print(f"Most active symbol: {liquidations.groupby('symbol')['filled_qty'].sum().idxmax()}")
    
    print(f"\nAnalysis complete. Check {args.output} for visualization files.")

if __name__ == "__main__":
    main()