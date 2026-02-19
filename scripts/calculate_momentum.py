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
DECAY_FACTOR = 0.94  # Exponential decay: ~50% weight reduction at 10 days


def load_data(symbol: str) -> pd.DataFrame:
    """Load 4H candle data."""
    file_path = DATA_DIR / f"{symbol}_4h_2190d.parquet"
    df = pd.read_parquet(file_path)
    if df.index.name == 'timestamp':
        df = df.reset_index()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df.sort_values('timestamp').reset_index(drop=True)


def calculate_momentum(df: pd.DataFrame, lookback_days: int = LOOKBACK_DAYS, decay_factor: float = DECAY_FACTOR) -> float:
    """Calculate volatility-adjusted momentum score with exponential decay weighting.
    
    Formula: weighted_returns / volatility
    - weighted_returns: sum of decay-weighted per-bar returns (recent bars weighted higher)
    - volatility: std(daily_returns_21d)
    - decay_factor: weight_i = decay^(n-1-i), normalized to sum to 1
    """
    if len(df) < lookback_days:
        return 0.0
    
    # Get last N days
    recent = df.tail(lookback_days)
    
    # Calculate per-bar returns
    daily_returns = recent['close'].pct_change().dropna()
    
    if len(daily_returns) == 0:
        return 0.0
    
    # Calculate volatility (std of daily returns)
    volatility = daily_returns.std()
    
    if volatility == 0:
        return 0.0
    
    # Calculate exponentially decay-weighted returns
    n = len(daily_returns)
    if 0 < decay_factor < 1:
        # weight_i = decay^(n-1-i): oldest gets smallest weight, newest gets weight=1
        indices = np.arange(n)
        weights = np.power(decay_factor, n - 1 - indices)
        weights /= weights.sum()  # normalize
        weighted_return = float(np.dot(weights, daily_returns.values)) * n
    else:
        # decay disabled: simple total return
        price_start = recent.iloc[0]['close']
        price_end = recent.iloc[-1]['close']
        weighted_return = (price_end / price_start) - 1
    
    # Volatility-adjusted momentum
    momentum_score = weighted_return / volatility
    
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
    
    print(f"Momentum Scores (21-day volatility-adjusted, decay={DECAY_FACTOR}):")
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
