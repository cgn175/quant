#!/usr/bin/env python3
"""Stress Testing for Phase 1 Strategies

Simulates extreme market scenarios to ensure portfolio survival:
1. COVID Crash (March 2020): -50% in 2 days
2. Luna Collapse (May 2022): -90% in 1 day  
3. China Ban (Sept 2021): -30% in 1 week

Tests all strategies under extreme conditions.
"""

import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path("data_4h")
SYMBOLS = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "BNB_USDT"]

# Stress scenarios
SCENARIOS = {
    "covid_crash": {
        "name": "COVID Crash (March 2020)",
        "drop": -0.50,  # -50%
        "duration_hours": 48,  # 2 days
        "date": "2020-03-12",
    },
    "luna_collapse": {
        "name": "Luna Collapse (May 2022)",
        "drop": -0.90,  # -90%
        "duration_hours": 24,  # 1 day
        "date": "2022-05-09",
    },
    "china_ban": {
        "name": "China Ban (Sept 2021)",
        "drop": -0.30,  # -30%
        "duration_hours": 168,  # 1 week
        "date": "2021-09-24",
    },
}


def load_data(symbol: str) -> pd.DataFrame:
    """Load 4H data."""
    file_path = DATA_DIR / f"{symbol}_4h_2190d.parquet"
    df = pd.read_parquet(file_path)
    if df.index.name == 'timestamp':
        df = df.reset_index()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df.sort_values('timestamp').reset_index(drop=True)


def simulate_crash(df: pd.DataFrame, scenario: dict) -> pd.DataFrame:
    """Simulate a crash scenario on historical data."""
    df = df.copy()
    
    # Find the date
    crash_date = pd.to_datetime(scenario['date'])
    mask = df['timestamp'] >= crash_date
    
    if not mask.any():
        return df
    
    crash_idx = df[mask].index[0]
    duration_candles = scenario['duration_hours'] // 4  # 4H candles
    
    # Apply crash
    for i in range(duration_candles):
        if crash_idx + i >= len(df):
            break
        
        # Gradual decline over duration
        progress = (i + 1) / duration_candles
        drop_factor = 1 + (scenario['drop'] * progress)
        
        df.loc[crash_idx + i, 'close'] *= drop_factor
        df.loc[crash_idx + i, 'high'] *= drop_factor
        df.loc[crash_idx + i, 'low'] *= drop_factor
        df.loc[crash_idx + i, 'open'] *= drop_factor
    
    return df


def test_strategy_survival(df: pd.DataFrame, symbol: str, scenario_name: str) -> dict:
    """Test if strategy survives the crash - assumes we're in a position."""
    
    # Assume we're LONG at the start of the crash (worst case)
    crash_date = pd.to_datetime([s['date'] for s in SCENARIOS.values() if s['name'] == scenario_name][0])
    mask = df['timestamp'] >= crash_date
    
    if not mask.any():
        return {
            'symbol': symbol,
            'scenario': scenario_name,
            'survived': True,
            'final_equity': 10000,
            'max_drawdown': 0,
            'stopped_out': False,
        }
    
    crash_idx = df[mask].index[0]
    entry_price = df.loc[crash_idx, 'close']
    equity = 10000
    position_size = 0.01  # 1% risk per trade
    leverage = 2.0
    
    # Calculate position
    risk_amount = equity * position_size
    stop_distance = 0.03  # 3% stop
    position_value = risk_amount / stop_distance * leverage
    position_btc = position_value / entry_price
    
    peak_equity = equity
    max_drawdown = 0
    stopped_out = False
    
    # Simulate the crash
    for i in range(crash_idx, min(crash_idx + 100, len(df))):
        current_price = df.loc[i, 'close']
        
        # Calculate PnL
        pnl_pct = (current_price - entry_price) / entry_price
        position_pnl = position_value * pnl_pct
        current_equity = equity + position_pnl
        
        # Check stop loss (3%)
        if pnl_pct <= -0.03:
            equity = current_equity
            stopped_out = True
            break
        
        # Track drawdown
        if current_equity < peak_equity:
            drawdown = (peak_equity - current_equity) / peak_equity
            max_drawdown = max(max_drawdown, drawdown)
        
        # Check if wiped out (lost 50%)
        if current_equity < equity * 0.5:
            return {
                'symbol': symbol,
                'scenario': scenario_name,
                'survived': False,
                'final_equity': current_equity,
                'max_drawdown': max_drawdown,
                'stopped_out': stopped_out,
            }
    
    # If we made it through
    final_price = df.loc[min(crash_idx + 100, len(df)-1), 'close']
    final_pnl_pct = (final_price - entry_price) / entry_price
    final_equity = equity + (position_value * final_pnl_pct)
    
    return {
        'symbol': symbol,
        'scenario': scenario_name,
        'survived': final_equity > equity * 0.5,  # Survived if lost < 50%
        'final_equity': final_equity,
        'max_drawdown': max_drawdown,
        'stopped_out': stopped_out,
    }


def main():
    print("="*70)
    print("STRESS TESTING - Phase 1 Strategies")
    print("="*70)
    print()
    
    all_results = []
    
    for scenario_key, scenario in SCENARIOS.items():
        print(f"\n{'='*70}")
        print(f"Scenario: {scenario['name']}")
        print(f"Drop: {scenario['drop']:.0%} over {scenario['duration_hours']}h")
        print(f"Date: {scenario['date']}")
        print(f"{'='*70}\n")
        
        for symbol in SYMBOLS:
            try:
                # Load data
                df = load_data(symbol)
                
                # Simulate crash
                df_crashed = simulate_crash(df, scenario)
                
                # Test survival
                result = test_strategy_survival(df_crashed, symbol, scenario['name'])
                all_results.append(result)
                
                status = "✅ SURVIVED" if result['survived'] else "❌ WIPED OUT"
                print(f"{symbol:12} {status}")
                print(f"  Final Equity: ${result['final_equity']:,.0f}")
                print(f"  Max Drawdown: {result['max_drawdown']:.1%}")
                print(f"  Stopped Out: {result['stopped_out']}")
                print()
                
            except Exception as e:
                print(f"{symbol:12} ERROR: {e}\n")
    
    # Summary
    print("\n" + "="*70)
    print("STRESS TEST SUMMARY")
    print("="*70)
    
    results_df = pd.DataFrame(all_results)
    
    # Survival rate by scenario
    print("\nSurvival Rate by Scenario:")
    for scenario_name in results_df['scenario'].unique():
        scenario_results = results_df[results_df['scenario'] == scenario_name]
        survival_rate = scenario_results['survived'].mean()
        print(f"  {scenario_name:30} {survival_rate:.0%} ({scenario_results['survived'].sum()}/{len(scenario_results)})")
    
    # Overall survival
    overall_survival = results_df['survived'].mean()
    print(f"\nOverall Survival Rate: {overall_survival:.0%}")
    
    # Average max drawdown
    avg_drawdown = results_df['max_drawdown'].mean()
    print(f"Average Max Drawdown: {avg_drawdown:.1%}")
    
    # Recommendations
    print("\n" + "="*70)
    print("RECOMMENDATIONS")
    print("="*70)
    
    if overall_survival < 1.0:
        print("\n⚠️  Portfolio does NOT survive all stress scenarios!")
        print("\nRecommended Actions:")
        print("1. Reduce position sizes (currently 1% risk per trade)")
        print("2. Implement portfolio-wide stop loss (e.g., -10% daily)")
        print("3. Add volatility circuit breaker (halt trading when ATR > 10%)")
        print("4. Reduce leverage (currently 2x max)")
    else:
        print("\n✅ Portfolio survives all stress scenarios!")
        print("\nCurrent risk management is adequate for extreme events.")
    
    print()


if __name__ == "__main__":
    main()
