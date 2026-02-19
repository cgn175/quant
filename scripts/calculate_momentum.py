#!/usr/bin/env python3
"""Calculate cross-sectional momentum scores for all symbols.

Uses 3-week (21-day) volatility-adjusted momentum as per Artemis research.
"""

import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path("data_4h")
SYMBOLS = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "BNB_USDT"]
LOOKBACK_DAYS = 21


def load_data(symbol: str) -> pd.DataFrame:
    """Load 4H candle data."""
    file_path = DATA_DIR / f"{symbol}_4h_2190d.parquet"
    df = pd.read_parquet(file_path)
    if df.index.name == 'timestamp':
        df = df.reset_index()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df.sort_values('timestamp').reset_index(drop=True)


def calculate_momentum(df: pd.DataFrame, lookback_days: int = LOOKBACK_DAYS) -> float:
    """Calculate volatility-adjusted momentum score.
    
    Formula: returns / volatility
    - returns: (price_now / price_21d_ago) - 1
    - volatility: std(daily_returns_21d)
    """
    if len(df) < lookback_days:
        return 0.0
    
    # Get last N days
    recent = df.tail(lookback_days)
    
    # Calculate returns
    price_start = recent.iloc[0]['close']
    price_end = recent.iloc[-1]['close']
    returns = (price_end / price_start) - 1
    
    # Calculate volatility (std of daily returns)
    daily_returns = recent['close'].pct_change().dropna()
    volatility = daily_returns.std()
    
    if volatility == 0:
        return 0.0
    
    # Volatility-adjusted momentum
    momentum_score = returns / volatility
    
    return momentum_score


def calculate_all_momentum() -> pd.DataFrame:
    """Calculate momentum scores for all symbols."""
    results = []
    
    for symbol in SYMBOLS:
        df = load_data(symbol)
        score = calculate_momentum(df)
        
        results.append({
            'symbol': symbol,
            'momentum_score': score,
            'price': df.iloc[-1]['close'],
            'timestamp': df.iloc[-1]['timestamp']
        })
    
    # Create DataFrame and rank
    df_results = pd.DataFrame(results)
    df_results = df_results.sort_values('momentum_score', ascending=False)
    df_results['rank'] = range(1, len(df_results) + 1)
    df_results['top_50pct'] = df_results['rank'] <= len(df_results) / 2
    
    return df_results


def main():
    print("="*70)
    print("Cross-Sectional Momentum Calculator")
    print("="*70)
    print()
    
    results = calculate_all_momentum()
    
    print("Momentum Scores (21-day volatility-adjusted):")
    print()
    print(results.to_string(index=False))
    print()
    
    print("="*70)
    print("Top 50% (Trade These):")
    print("="*70)
    top = results[results['top_50pct']]
    for _, row in top.iterrows():
        print(f"  {row['symbol']:12} Score: {row['momentum_score']:8.2f}")
    print()
    
    print("="*70)
    print("Bottom 50% (Skip These):")
    print("="*70)
    bottom = results[~results['top_50pct']]
    for _, row in bottom.iterrows():
        print(f"  {row['symbol']:12} Score: {row['momentum_score']:8.2f}")
    print()
    
    # Save to CSV
    output_path = Path("results/momentum_scores.csv")
    output_path.parent.mkdir(exist_ok=True)
    results.to_csv(output_path, index=False)
    print(f"Saved to: {output_path}")


if __name__ == "__main__":
    main()
