#!/usr/bin/env python3
"""Quick backtest using data_4h parquet files to validate Phase 1 features."""

import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path("data_4h")
SYMBOLS = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "BNB_USDT"]

def load_data(symbol: str) -> pd.DataFrame:
    """Load 4H data from parquet."""
    file_path = DATA_DIR / f"{symbol}_4h_2190d.parquet"
    df = pd.read_parquet(file_path)
    
    # Reset index if timestamp is index
    if df.index.name == 'timestamp':
        df = df.reset_index()
    
    # Ensure timestamp column
    if 'timestamp' not in df.columns and 'open_time' in df.columns:
        df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms')
    elif 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    df = df.sort_values('timestamp').reset_index(drop=True)
    return df

def calculate_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate returns and volatility."""
    df = df.copy()
    df['returns'] = df['close'].pct_change()
    df['range_pct'] = (df['high'] - df['low']) / df['close']
    df['atr_14'] = df['range_pct'].rolling(14).mean()
    df['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean()
    return df

def simple_trend_backtest(df: pd.DataFrame, symbol: str) -> dict:
    """Simple trend following backtest."""
    df = calculate_returns(df)
    
    # Simple Donchian breakout
    df['high_20'] = df['high'].rolling(20).max()
    df['low_20'] = df['low'].rolling(20).min()
    
    # EMA filters
    df['ema_9'] = df['close'].ewm(span=9).mean()
    df['ema_21'] = df['close'].ewm(span=21).mean()
    df['ema_50'] = df['close'].ewm(span=50).mean()
    
    # Signals
    df['long_signal'] = (df['close'] > df['high_20'].shift(1)) & (df['close'] > df['ema_50']) & (df['ema_9'] > df['ema_21'])
    df['short_signal'] = (df['close'] < df['low_20'].shift(1)) & (df['close'] < df['ema_50']) & (df['ema_9'] < df['ema_21'])
    
    # Simple position tracking
    position = 0
    entry_price = 0
    trades = []
    
    for i in range(50, len(df)):
        row = df.iloc[i]
        
        if position == 0:
            if row['long_signal']:
                position = 1
                entry_price = row['close']
            elif row['short_signal']:
                position = -1
                entry_price = row['close']
        else:
            # Simple exit: opposite signal or 3% stop
            exit_triggered = False
            pnl_pct = 0
            
            if position == 1:
                pnl_pct = (row['close'] - entry_price) / entry_price
                if row['short_signal'] or pnl_pct < -0.03:
                    exit_triggered = True
            else:
                pnl_pct = (entry_price - row['close']) / entry_price
                if row['long_signal'] or pnl_pct < -0.03:
                    exit_triggered = True
            
            if exit_triggered:
                trades.append({
                    'entry': entry_price,
                    'exit': row['close'],
                    'pnl_pct': pnl_pct,
                    'side': 'LONG' if position == 1 else 'SHORT'
                })
                position = 0
    
    if len(trades) == 0:
        return {'symbol': symbol, 'trades': 0, 'win_rate': 0, 'avg_pnl': 0, 'total_return': 0}
    
    trades_df = pd.DataFrame(trades)
    win_rate = (trades_df['pnl_pct'] > 0).mean()
    avg_pnl = trades_df['pnl_pct'].mean()
    total_return = (1 + trades_df['pnl_pct']).prod() - 1
    
    return {
        'symbol': symbol,
        'trades': len(trades),
        'win_rate': win_rate,
        'avg_pnl': avg_pnl,
        'total_return': total_return,
        'sharpe': avg_pnl / trades_df['pnl_pct'].std() if trades_df['pnl_pct'].std() > 0 else 0
    }

def main():
    print("="*60)
    print("Phase 1 Backtest - Trend Following (Baseline)")
    print("="*60)
    print()
    
    results = []
    for symbol in SYMBOLS:
        try:
            print(f"Backtesting {symbol}...")
            df = load_data(symbol)
            print(f"  Loaded {len(df)} candles from {df['timestamp'].min()} to {df['timestamp'].max()}")
            
            result = simple_trend_backtest(df, symbol)
            results.append(result)
            
            print(f"  Trades: {result['trades']}")
            print(f"  Win Rate: {result['win_rate']:.1%}")
            print(f"  Avg PnL: {result['avg_pnl']:.2%}")
            print(f"  Total Return: {result['total_return']:.2%}")
            print(f"  Sharpe: {result['sharpe']:.2f}")
            print()
        except Exception as e:
            print(f"  ERROR: {e}")
            print()
    
    if results:
        print("="*60)
        print("Summary")
        print("="*60)
        results_df = pd.DataFrame(results)
        print(results_df.to_string(index=False))
        print()
        print(f"Average Win Rate: {results_df['win_rate'].mean():.1%}")
        print(f"Average Sharpe: {results_df['sharpe'].mean():.2f}")
        print(f"Total Trades: {results_df['trades'].sum()}")

if __name__ == "__main__":
    main()
