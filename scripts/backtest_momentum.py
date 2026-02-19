#!/usr/bin/env python3
"""Backtest trend following strategy WITH cross-sectional momentum filter.

Compares performance vs baseline (no momentum filter).
"""

import pandas as pd
import numpy as np
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))
from calculate_momentum import calculate_momentum, SYMBOLS, DATA_DIR

LOOKBACK_DAYS = 21
TOP_PCT = 0.5  # Trade top 50%


def load_all_data():
    """Load data for all symbols."""
    data = {}
    for symbol in SYMBOLS:
        file_path = DATA_DIR / f"{symbol}_4h_2190d.parquet"
        df = pd.read_parquet(file_path)
        if df.index.name == 'timestamp':
            df = df.reset_index()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp').reset_index(drop=True)
        data[symbol] = df
    return data


def get_momentum_ranks(data, idx):
    """Get momentum ranks at a specific index."""
    scores = []
    
    for symbol in SYMBOLS:
        df = data[symbol]
        if idx < LOOKBACK_DAYS:
            scores.append({'symbol': symbol, 'score': 0.0})
            continue
        
        # Get data up to current index
        recent = df.iloc[max(0, idx-LOOKBACK_DAYS):idx]
        score = calculate_momentum(recent, LOOKBACK_DAYS)
        scores.append({'symbol': symbol, 'score': score})
    
    # Sort by score descending
    scores = sorted(scores, key=lambda x: x['score'], reverse=True)
    
    # Assign ranks
    ranks = {}
    for i, item in enumerate(scores):
        ranks[item['symbol']] = i + 1
    
    return ranks


def is_top_momentum(symbol, ranks):
    """Check if symbol is in top N%."""
    rank = ranks.get(symbol, len(SYMBOLS))
    top_n = int(len(SYMBOLS) * TOP_PCT)
    if top_n < 1:
        top_n = 1
    return rank <= top_n


def simple_trend_signal(df, idx):
    """Simple trend signal: price > 50 EMA."""
    if idx < 50:
        return None
    
    ema50 = df['close'].iloc[max(0, idx-50):idx].mean()
    current_price = df.iloc[idx]['close']
    
    if current_price > ema50:
        return 'LONG'
    elif current_price < ema50:
        return 'SHORT'
    return None


def backtest_with_momentum():
    """Backtest with momentum filter."""
    print("Loading data...")
    data = load_all_data()
    
    # Find common date range
    min_len = min(len(df) for df in data.values())
    
    equity = 10000
    trades = []
    positions = {}  # symbol -> {'side', 'entry_price', 'entry_idx'}
    
    print(f"Backtesting {min_len} candles with momentum filter...")
    
    for idx in range(50, min_len):  # Start after EMA50 warmup
        # Get momentum ranks
        ranks = get_momentum_ranks(data, idx)
        
        # Check each symbol
        for symbol in SYMBOLS:
            df = data[symbol]
            
            # Skip if already in position
            if symbol in positions:
                # Check exit (simple: opposite signal or 3% stop)
                pos = positions[symbol]
                current_price = df.iloc[idx]['close']
                pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
                if pos['side'] == 'SHORT':
                    pnl_pct = -pnl_pct
                
                # Exit on stop loss or opposite signal
                signal = simple_trend_signal(df, idx)
                if pnl_pct < -0.03 or (signal and signal != pos['side']):
                    # Close position
                    equity *= (1 + pnl_pct * 0.01)  # 1% risk per trade
                    trades.append({
                        'symbol': symbol,
                        'entry_idx': pos['entry_idx'],
                        'exit_idx': idx,
                        'side': pos['side'],
                        'pnl_pct': pnl_pct,
                        'win': pnl_pct > 0
                    })
                    del positions[symbol]
                continue
            
            # Check entry signal
            signal = simple_trend_signal(df, idx)
            if not signal:
                continue
            
            # MOMENTUM FILTER: Only trade if in top momentum
            if not is_top_momentum(symbol, ranks):
                continue
            
            # Enter position
            positions[symbol] = {
                'side': signal,
                'entry_price': df.iloc[idx]['close'],
                'entry_idx': idx
            }
    
    # Close any remaining positions
    for symbol, pos in positions.items():
        df = data[symbol]
        current_price = df.iloc[min_len-1]['close']
        pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
        if pos['side'] == 'SHORT':
            pnl_pct = -pnl_pct
        
        equity *= (1 + pnl_pct * 0.01)
        trades.append({
            'symbol': symbol,
            'entry_idx': pos['entry_idx'],
            'exit_idx': min_len-1,
            'side': pos['side'],
            'pnl_pct': pnl_pct,
            'win': pnl_pct > 0
        })
    
    return equity, trades


def backtest_without_momentum():
    """Backtest WITHOUT momentum filter (baseline)."""
    print("Loading data...")
    data = load_all_data()
    
    min_len = min(len(df) for df in data.values())
    
    equity = 10000
    trades = []
    positions = {}
    
    print(f"Backtesting {min_len} candles WITHOUT momentum filter (baseline)...")
    
    for idx in range(50, min_len):
        for symbol in SYMBOLS:
            df = data[symbol]
            
            if symbol in positions:
                pos = positions[symbol]
                current_price = df.iloc[idx]['close']
                pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
                if pos['side'] == 'SHORT':
                    pnl_pct = -pnl_pct
                
                signal = simple_trend_signal(df, idx)
                if pnl_pct < -0.03 or (signal and signal != pos['side']):
                    equity *= (1 + pnl_pct * 0.01)
                    trades.append({
                        'symbol': symbol,
                        'entry_idx': pos['entry_idx'],
                        'exit_idx': idx,
                        'side': pos['side'],
                        'pnl_pct': pnl_pct,
                        'win': pnl_pct > 0
                    })
                    del positions[symbol]
                continue
            
            signal = simple_trend_signal(df, idx)
            if not signal:
                continue
            
            # NO MOMENTUM FILTER - trade all signals
            positions[symbol] = {
                'side': signal,
                'entry_price': df.iloc[idx]['close'],
                'entry_idx': idx
            }
    
    # Close remaining
    for symbol, pos in positions.items():
        df = data[symbol]
        current_price = df.iloc[min_len-1]['close']
        pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
        if pos['side'] == 'SHORT':
            pnl_pct = -pnl_pct
        
        equity *= (1 + pnl_pct * 0.01)
        trades.append({
            'symbol': symbol,
            'entry_idx': pos['entry_idx'],
            'exit_idx': min_len-1,
            'side': pos['side'],
            'pnl_pct': pnl_pct,
            'win': pnl_pct > 0
        })
    
    return equity, trades


def analyze_results(equity, trades, name):
    """Analyze backtest results."""
    df = pd.DataFrame(trades)
    
    total_trades = len(trades)
    winning_trades = df['win'].sum()
    win_rate = winning_trades / total_trades if total_trades > 0 else 0
    
    avg_win = df[df['win']]['pnl_pct'].mean() if winning_trades > 0 else 0
    avg_loss = df[~df['win']]['pnl_pct'].mean() if (total_trades - winning_trades) > 0 else 0
    
    total_return = (equity - 10000) / 10000
    
    # Calculate Sharpe (simplified)
    returns = df['pnl_pct'].values
    sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if len(returns) > 0 and returns.std() > 0 else 0
    
    print(f"\n{'='*70}")
    print(f"{name}")
    print(f"{'='*70}")
    print(f"Total Trades:    {total_trades}")
    print(f"Winning Trades:  {winning_trades}")
    print(f"Win Rate:        {win_rate:.1%}")
    print(f"Avg Win:         {avg_win:.2%}")
    print(f"Avg Loss:        {avg_loss:.2%}")
    print(f"Final Equity:    ${equity:,.0f}")
    print(f"Total Return:    {total_return:.1%}")
    print(f"Sharpe Ratio:    {sharpe:.2f}")
    
    return {
        'name': name,
        'trades': total_trades,
        'win_rate': win_rate,
        'final_equity': equity,
        'total_return': total_return,
        'sharpe': sharpe
    }


def main():
    print("="*70)
    print("BACKTEST: Cross-Sectional Momentum Filter")
    print("="*70)
    print()
    
    # Baseline (no momentum)
    equity_baseline, trades_baseline = backtest_without_momentum()
    results_baseline = analyze_results(equity_baseline, trades_baseline, "BASELINE (No Momentum Filter)")
    
    # With momentum
    equity_momentum, trades_momentum = backtest_with_momentum()
    results_momentum = analyze_results(equity_momentum, trades_momentum, "WITH MOMENTUM FILTER")
    
    # Comparison
    print(f"\n{'='*70}")
    print("COMPARISON")
    print(f"{'='*70}")
    print(f"{'Metric':<20} {'Baseline':>15} {'Momentum':>15} {'Change':>15}")
    print(f"{'-'*70}")
    print(f"{'Trades':<20} {results_baseline['trades']:>15} {results_momentum['trades']:>15} {results_momentum['trades'] - results_baseline['trades']:>15}")
    print(f"{'Win Rate':<20} {results_baseline['win_rate']:>14.1%} {results_momentum['win_rate']:>14.1%} {(results_momentum['win_rate'] - results_baseline['win_rate']):>14.1%}")
    print(f"{'Total Return':<20} {results_baseline['total_return']:>14.1%} {results_momentum['total_return']:>14.1%} {(results_momentum['total_return'] - results_baseline['total_return']):>14.1%}")
    print(f"{'Sharpe Ratio':<20} {results_baseline['sharpe']:>15.2f} {results_momentum['sharpe']:>15.2f} {(results_momentum['sharpe'] - results_baseline['sharpe']):>15.2f}")
    
    # Verdict
    print(f"\n{'='*70}")
    print("VERDICT")
    print(f"{'='*70}")
    
    if results_momentum['sharpe'] > results_baseline['sharpe']:
        improvement = (results_momentum['sharpe'] - results_baseline['sharpe']) / results_baseline['sharpe'] * 100
        print(f"✅ Momentum filter IMPROVES performance")
        print(f"   Sharpe improvement: +{improvement:.1f}%")
    else:
        decline = (results_baseline['sharpe'] - results_momentum['sharpe']) / results_baseline['sharpe'] * 100
        print(f"❌ Momentum filter DEGRADES performance")
        print(f"   Sharpe decline: -{decline:.1f}%")
    
    print()


if __name__ == "__main__":
    main()
