#!/usr/bin/env python3
"""Backtest the trained model on historical data."""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
import joblib
import matplotlib.pyplot as plt
import seaborn as sns

from build_features import FEATURE_COLUMNS, prepare_dataset


def backtest(
    model: xgb.XGBClassifier,
    X: pd.DataFrame,
    y: pd.Series,
    threshold_up: float = 0.6,
    threshold_down: float = 0.6,
    fee_pct: float = 0.0004,
    initial_capital: float = 10000.0,
) -> pd.DataFrame:
    """Run backtest simulation."""
    
    proba = model.predict_proba(X)
    
    results = pd.DataFrame(index=X.index)
    results["close"] = X["close"]
    results["actual_label"] = y
    results["p_down"] = proba[:, 0]
    results["p_neutral"] = proba[:, 1]
    results["p_up"] = proba[:, 2]
    
    results["signal"] = 0
    results.loc[proba[:, 2] > threshold_up, "signal"] = 1
    results.loc[proba[:, 0] > threshold_down, "signal"] = -1
    
    results["position"] = results["signal"].shift(1).fillna(0)
    
    results["returns"] = results["close"].pct_change()
    
    results["strategy_returns"] = results["position"] * results["returns"]
    
    trades = results["position"].diff().abs()
    results["fees"] = trades * fee_pct
    results["strategy_returns_net"] = results["strategy_returns"] - results["fees"]
    
    results["equity"] = initial_capital * (1 + results["strategy_returns_net"]).cumprod()
    results["buy_hold_equity"] = initial_capital * (1 + results["returns"]).cumprod()
    
    return results


def compute_metrics(results: pd.DataFrame) -> dict:
    """Compute backtest performance metrics."""
    
    returns = results["strategy_returns_net"].dropna()
    
    total_return = (results["equity"].iloc[-1] / results["equity"].iloc[0]) - 1
    
    annual_factor = 365 * 24 * 60
    annual_return = (1 + total_return) ** (annual_factor / len(results)) - 1
    
    annual_vol = returns.std() * np.sqrt(annual_factor)
    sharpe = annual_return / annual_vol if annual_vol > 0 else 0
    
    cummax = results["equity"].cummax()
    drawdown = (results["equity"] - cummax) / cummax
    max_drawdown = drawdown.min()
    
    trades = results["signal"].diff().abs().sum() / 2
    
    winning_trades = (results["strategy_returns_net"] > 0).sum()
    total_trades = (results["strategy_returns_net"] != 0).sum()
    win_rate = winning_trades / total_trades if total_trades > 0 else 0
    
    gross_profit = results.loc[results["strategy_returns_net"] > 0, "strategy_returns_net"].sum()
    gross_loss = abs(results.loc[results["strategy_returns_net"] < 0, "strategy_returns_net"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    
    return {
        "total_return": total_return,
        "annual_return": annual_return,
        "annual_volatility": annual_vol,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_drawdown,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_trades": trades,
        "final_equity": results["equity"].iloc[-1],
    }


def plot_results(results: pd.DataFrame, output_path: Path):
    """Generate backtest visualization."""
    
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
    
    axes[0].plot(results.index, results["equity"], label="Strategy", linewidth=1)
    axes[0].plot(results.index, results["buy_hold_equity"], label="Buy & Hold", alpha=0.7, linewidth=1)
    axes[0].set_ylabel("Equity ($)")
    axes[0].legend()
    axes[0].set_title("Equity Curve")
    axes[0].grid(True, alpha=0.3)
    
    cummax = results["equity"].cummax()
    drawdown = (results["equity"] - cummax) / cummax * 100
    axes[1].fill_between(results.index, drawdown, 0, alpha=0.5, color="red")
    axes[1].set_ylabel("Drawdown (%)")
    axes[1].set_title("Drawdown")
    axes[1].grid(True, alpha=0.3)
    
    axes[2].plot(results.index, results["position"], linewidth=0.5)
    axes[2].set_ylabel("Position")
    axes[2].set_xlabel("Time")
    axes[2].set_title("Position Over Time")
    axes[2].grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    print(f"Saved plot to {output_path}")
    plt.close()


def main():
    parser = argparse.ArgumentParser(description="Backtest trained model")
    parser.add_argument("--model", type=str, default="models/xgboost_model.joblib")
    parser.add_argument("--data-dir", type=str, default="data")
    parser.add_argument("--symbols", type=str, default="BTC/USDT,ETH/USDT")
    parser.add_argument("--threshold", type=float, default=0.0003)
    parser.add_argument("--threshold-up", type=float, default=0.6)
    parser.add_argument("--threshold-down", type=float, default=0.6)
    parser.add_argument("--fee", type=float, default=0.0004)
    parser.add_argument("--capital", type=float, default=10000.0)
    parser.add_argument("--output", type=str, default="models/backtest.png")
    
    args = parser.parse_args()
    
    print(f"Loading model from {args.model}")
    model = joblib.load(args.model)
    
    symbols = [s.strip() for s in args.symbols.split(",")]
    X, y = prepare_dataset(Path(args.data_dir), symbols, args.threshold)
    
    split_idx = int(len(X) * 0.8)
    X_test = X.iloc[split_idx:]
    y_test = y.iloc[split_idx:]
    
    print(f"\nRunning backtest on {len(X_test)} samples...")
    results = backtest(
        model,
        X_test,
        y_test,
        args.threshold_up,
        args.threshold_down,
        args.fee,
        args.capital,
    )
    
    metrics = compute_metrics(results)
    
    print("\n" + "=" * 50)
    print("BACKTEST RESULTS")
    print("=" * 50)
    print(f"Total Return:      {metrics['total_return']:.2%}")
    print(f"Annual Return:     {metrics['annual_return']:.2%}")
    print(f"Annual Volatility: {metrics['annual_volatility']:.2%}")
    print(f"Sharpe Ratio:      {metrics['sharpe_ratio']:.2f}")
    print(f"Max Drawdown:      {metrics['max_drawdown']:.2%}")
    print(f"Win Rate:          {metrics['win_rate']:.2%}")
    print(f"Profit Factor:     {metrics['profit_factor']:.2f}")
    print(f"Total Trades:      {metrics['total_trades']:.0f}")
    print(f"Final Equity:      ${metrics['final_equity']:.2f}")
    print("=" * 50)
    
    plot_results(results, Path(args.output))


if __name__ == "__main__":
    main()
