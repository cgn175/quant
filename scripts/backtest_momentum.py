#!/usr/bin/env python3
"""
Cross-sectional crypto momentum backtest with walk-forward validation.

Strategy: Rank coins by past N-bar return, long top quartile, short bottom quartile.
Rebalance weekly. Walk-forward validation with 6mo train / 3mo test windows.

Usage:
    python scripts/backtest_momentum.py [--data-dir data/momentum] [--output results.csv]
"""

import os
import argparse
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple


def load_data(data_dir: str) -> Dict[str, pd.DataFrame]:
    """Load all CSV files from data directory."""
    data = {}
    for fname in os.listdir(data_dir):
        if fname.endswith("_4h.csv"):
            symbol = fname.replace("_4h.csv", "")
            df = pd.read_csv(os.path.join(data_dir, fname))
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            df.sort_index(inplace=True)
            data[symbol] = df
    return data


def align_data(data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Align all symbols to a common index, using close prices."""
    closes = pd.DataFrame({sym: df["close"] for sym, df in data.items()})
    closes = closes.dropna(how="all")  # Drop rows where all NaN
    return closes


def calculate_returns(closes: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Calculate lookback-period returns."""
    return closes.pct_change(lookback)


def rank_signals(returns: pd.DataFrame) -> pd.DataFrame:
    """Rank symbols cross-sectionally (1 = best, N = worst)."""
    return returns.rank(axis=1, ascending=False)


def backtest_momentum(
    closes: pd.DataFrame,
    lookback: int,
    rebalance_freq: int = 42,  # ~weekly at 4H bars
    top_pct: float = 0.25,
    cost_bps: float = 10,  # 10bps per side
) -> pd.Series:
    """
    Run momentum backtest.
    
    Long top quartile, short bottom quartile, equal-weight.
    Returns a series of portfolio returns.
    """
    returns = closes.pct_change()
    mom_returns = calculate_returns(closes, lookback)
    
    n_symbols = closes.shape[1]
    n_long = max(1, int(n_symbols * top_pct))
    n_short = n_long
    
    portfolio_returns = []
    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    last_rebalance = 0
    
    for i in range(lookback + 1, len(closes)):
        if (i - lookback - 1) % rebalance_freq == 0:
            # Rebalance
            ranks = mom_returns.iloc[i - 1].rank(ascending=False)
            valid = ranks.dropna()
            
            if len(valid) < n_long + n_short:
                continue
            
            # Long top, short bottom
            longs = valid.nsmallest(n_long).index  # smallest rank = highest return
            shorts = valid.nlargest(n_short).index  # largest rank = lowest return
            
            new_weights = pd.Series(0.0, index=closes.columns)
            new_weights[longs] = 1.0 / n_long
            new_weights[shorts] = -1.0 / n_short
            
            # Apply transaction costs
            turnover = (new_weights - weights.iloc[i - 1]).abs().sum()
            cost = turnover * (cost_bps / 10000)
            
            weights.iloc[i] = new_weights
            last_rebalance = i
        else:
            weights.iloc[i] = weights.iloc[i - 1]
        
        # Portfolio return
        daily_ret = (weights.iloc[i] * returns.iloc[i]).sum()
        
        # Subtract cost only on rebalance days
        if (i - lookback - 1) % rebalance_freq == 0:
            turnover = (weights.iloc[i] - weights.iloc[i - 1]).abs().sum()
            daily_ret -= turnover * (cost_bps / 10000)
        
        portfolio_returns.append(daily_ret)
    
    return pd.Series(portfolio_returns, index=closes.index[lookback + 1:])


def calculate_sharpe(returns: pd.Series, bars_per_year: float = 365 * 6) -> float:
    """Calculate annualized Sharpe ratio."""
    if len(returns) < 10 or returns.std() == 0:
        return 0.0
    return returns.mean() / returns.std() * np.sqrt(bars_per_year)


def walk_forward_backtest(
    closes: pd.DataFrame,
    train_bars: int = 1095,  # ~6 months at 4H
    test_bars: int = 547,    # ~3 months
    step_bars: int = 182,    # ~1 month
    lookback_grid: List[int] = None,
) -> List[Dict]:
    """
    Walk-forward validation.
    
    On each training window, optimize lookback.
    On test window, use best lookback and record performance.
    """
    if lookback_grid is None:
        lookback_grid = [12, 24, 42, 84, 168]
    
    results = []
    total_bars = len(closes)
    
    i = 0
    while i + train_bars + test_bars <= total_bars:
        train_start = i
        train_end = i + train_bars
        test_start = train_end
        test_end = test_start + test_bars
        
        train_data = closes.iloc[train_start:train_end]
        test_data = closes.iloc[test_start:test_end]
        
        # Optimize on training
        best_lookback = lookback_grid[0]
        best_train_sharpe = -999
        
        for lb in lookback_grid:
            if lb >= len(train_data) - 50:
                continue
            train_returns = backtest_momentum(train_data, lb)
            sharpe = calculate_sharpe(train_returns)
            if sharpe > best_train_sharpe:
                best_train_sharpe = sharpe
                best_lookback = lb
        
        # Test with best lookback
        if best_lookback >= len(test_data) - 50:
            i += step_bars
            continue
        
        test_returns = backtest_momentum(test_data, best_lookback)
        test_sharpe = calculate_sharpe(test_returns)
        
        results.append({
            "train_start": closes.index[train_start],
            "train_end": closes.index[train_end - 1],
            "test_start": closes.index[test_start],
            "test_end": closes.index[test_end - 1],
            "best_lookback": best_lookback,
            "train_sharpe": best_train_sharpe,
            "test_sharpe": test_sharpe,
            "n_test_bars": len(test_returns),
        })
        
        print(f"Period {len(results)}: Train Sharpe={best_train_sharpe:.2f}, "
              f"Test Sharpe={test_sharpe:.2f}, Lookback={best_lookback}")
        
        i += step_bars
    
    return results


def analyze_results(results: List[Dict]) -> Dict:
    """Analyze walk-forward results."""
    if not results:
        return {"error": "No results"}
    
    train_sharpes = [r["train_sharpe"] for r in results]
    test_sharpes = [r["test_sharpe"] for r in results]
    
    avg_train = np.mean(train_sharpes)
    avg_test = np.mean(test_sharpes)
    degradation = 1 - avg_test / avg_train if avg_train != 0 else 0
    pct_profitable = sum(1 for s in test_sharpes if s > 0) / len(test_sharpes)
    
    summary = {
        "n_periods": len(results),
        "avg_train_sharpe": avg_train,
        "avg_test_sharpe": avg_test,
        "sharpe_degradation": degradation,
        "pct_profitable_periods": pct_profitable,
        "worst_test_sharpe": min(test_sharpes),
        "best_test_sharpe": max(test_sharpes),
        "is_viable": avg_test > 0.5 and degradation < 0.5,
    }
    
    return summary


def main():
    parser = argparse.ArgumentParser(description="Cross-sectional crypto momentum backtest")
    parser.add_argument("--data-dir", default="data/momentum", help="Directory with CSV files")
    parser.add_argument("--output", default=None, help="Output CSV for results")
    args = parser.parse_args()
    
    if not os.path.exists(args.data_dir):
        print(f"Error: Data directory '{args.data_dir}' not found.")
        print("Run scripts/fetch_momentum_data.py first to download data.")
        return
    
    print(f"Loading data from {args.data_dir}...")
    data = load_data(args.data_dir)
    
    if len(data) < 4:
        print(f"Error: Need at least 4 symbols, found {len(data)}")
        return
    
    print(f"Loaded {len(data)} symbols")
    closes = align_data(data)
    print(f"Aligned data: {len(closes)} bars, {closes.shape[1]} symbols")
    
    print("\nRunning walk-forward backtest...")
    print("=" * 60)
    
    results = walk_forward_backtest(closes)
    
    print("=" * 60)
    print("\nSummary:")
    summary = analyze_results(results)
    
    for k, v in summary.items():
        if isinstance(v, float):
            print(f"  {k}: {v:.3f}")
        else:
            print(f"  {k}: {v}")
    
    # Validation warnings (per our research references)
    if summary.get("avg_test_sharpe", 0) < 0.5:
        print("\n⚠️  WARNING: Avg test Sharpe < 0.5 — strategy may not be viable")
    if summary.get("sharpe_degradation", 0) > 0.5:
        print("⚠️  WARNING: Sharpe degradation > 50% — likely overfit")
    if summary.get("pct_profitable_periods", 0) < 0.6:
        print("⚠️  WARNING: < 60% profitable periods — inconsistent edge")
    
    if args.output:
        pd.DataFrame(results).to_csv(args.output, index=False)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
