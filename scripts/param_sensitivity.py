#!/usr/bin/env python3
"""
Plan D: Parameter Sensitivity Analysis.

Tests that the trend following strategy is robust across a neighborhood
of parameters. If it only works at exact default params, it's curve-fit.

Two analysis modes:
  1. One-at-a-time: vary each param individually, hold rest at default
  2. Interaction grid: donchian_period × atr_stop_mult (4×4 = 16 combos)

Robustness criteria:
  - Profitable in > 70% of parameter combinations
  - No single parameter value causes catastrophic failure (max_dd > 50%)
"""

from __future__ import annotations

import sys
from itertools import product
from multiprocessing import Pool, cpu_count
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_trend import TrendFollowingBacktester, load_all_data
from trend_signals import DEFAULT_PARAMS, generate_signals


# ---------------------------------------------------------------------------
# Parameter Grid
# ---------------------------------------------------------------------------

PARAM_GRID = {
    "donchian_period": [15, 20, 25, 30],
    "ema_fast": [7, 9, 12],
    "ema_slow": [18, 21, 26],
    "atr_stop_mult": [2.0, 2.5, 3.0, 3.5],
    "adx_threshold": [15.0, 20.0, 25.0],
    "risk_per_trade": [0.005, 0.01, 0.015],
}

# For risk_per_trade, we pass it to the backtester, not signals
SIGNAL_PARAMS = {"donchian_period", "ema_fast", "ema_slow", "atr_stop_mult", "adx_threshold"}
BACKTEST_PARAMS = {"risk_per_trade", "atr_stop_mult"}


# ---------------------------------------------------------------------------
# Worker function (for multiprocessing)
# ---------------------------------------------------------------------------

# Module-level data holders (set in main before pool)
_ohlcv_dict = None
_funding_dict = None


def _init_worker(ohlcv, funding):
    global _ohlcv_dict, _funding_dict
    _ohlcv_dict = ohlcv
    _funding_dict = funding


def _run_single_config(config: dict) -> dict:
    """Run a single backtest configuration. Returns metrics dict."""
    global _ohlcv_dict, _funding_dict

    params = config["params"]
    bt_kwargs = config.get("bt_kwargs", {})

    # Generate signals
    signals_dict = {}
    for sym, df in _ohlcv_dict.items():
        funding = _funding_dict.get(sym)
        signals = generate_signals(df, funding, params)
        signals_dict[sym] = signals

    # Run backtest
    bt = TrendFollowingBacktester(
        initial_equity=10_000,
        max_leverage=2.0,
        max_daily_loss=0.03,
        **bt_kwargs,
    )
    result = bt.run(signals_dict, _ohlcv_dict)
    m = result.metrics

    return {
        **config.get("meta", {}),
        "total_return_pct": m.get("total_return_pct", 0),
        "sharpe": m.get("sharpe", 0),
        "max_dd_pct": m.get("max_drawdown_pct", 0),
        "win_rate_pct": m.get("win_rate_pct", 0),
        "profit_factor": m.get("profit_factor", 0),
        "num_trades": m.get("num_trades", 0),
        "avg_wl_ratio": m.get("avg_winner_loser_ratio", 0),
    }


# ---------------------------------------------------------------------------
# One-at-a-time analysis
# ---------------------------------------------------------------------------

def one_at_a_time_sweep(ohlcv_dict, funding_dict) -> pd.DataFrame:
    """Vary each parameter individually while holding others at default."""
    configs = []

    for param_name, values in PARAM_GRID.items():
        for val in values:
            params = {**DEFAULT_PARAMS}
            bt_kwargs = {"risk_per_trade": 0.01, "atr_stop_mult": 3.0}

            if param_name in SIGNAL_PARAMS:
                params[param_name] = val
            if param_name in BACKTEST_PARAMS:
                if param_name == "risk_per_trade":
                    bt_kwargs["risk_per_trade"] = val
                elif param_name == "atr_stop_mult":
                    bt_kwargs["atr_stop_mult"] = val
                    params["atr_stop_mult"] = val

            is_default = val == (DEFAULT_PARAMS.get(param_name, bt_kwargs.get(param_name)))

            configs.append({
                "params": params,
                "bt_kwargs": bt_kwargs,
                "meta": {
                    "analysis": "one_at_a_time",
                    "param_name": param_name,
                    "param_value": val,
                    "is_default": is_default,
                },
            })

    total = len(configs)
    print(f"\nOne-at-a-time sweep: {total} configurations")

    results = []
    n_workers = min(cpu_count(), 4)

    # Use sequential processing if data is small or for debugging
    for i, config in enumerate(configs):
        # Set globals for worker
        global _ohlcv_dict, _funding_dict
        _ohlcv_dict = ohlcv_dict
        _funding_dict = funding_dict

        result = _run_single_config(config)
        results.append(result)

        print(f"  [{i + 1:3d}/{total}] {result['param_name']:20s} = {result['param_value']:<6}  "
              f"Ret: {result['total_return_pct']:+7.2f}%  "
              f"Sharpe: {result['sharpe']:5.2f}  "
              f"DD: {result['max_dd_pct']:5.1f}%  "
              f"Trades: {result['num_trades']:3d}")

    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Interaction grid: donchian × atr_stop
# ---------------------------------------------------------------------------

def interaction_grid(ohlcv_dict, funding_dict) -> pd.DataFrame:
    """Test donchian_period × atr_stop_mult interaction."""
    donchian_values = PARAM_GRID["donchian_period"]
    atr_values = PARAM_GRID["atr_stop_mult"]

    configs = []
    for dp, atr_m in product(donchian_values, atr_values):
        params = {**DEFAULT_PARAMS, "donchian_period": dp, "atr_stop_mult": atr_m}
        bt_kwargs = {"risk_per_trade": 0.01, "atr_stop_mult": atr_m}

        configs.append({
            "params": params,
            "bt_kwargs": bt_kwargs,
            "meta": {
                "analysis": "interaction",
                "donchian_period": dp,
                "atr_stop_mult": atr_m,
            },
        })

    total = len(configs)
    print(f"\nInteraction grid (Donchian × ATR): {total} configurations")

    results = []
    global _ohlcv_dict, _funding_dict
    _ohlcv_dict = ohlcv_dict
    _funding_dict = funding_dict

    for i, config in enumerate(configs):
        result = _run_single_config(config)
        results.append(result)

        print(f"  [{i + 1:3d}/{total}] DC={result['donchian_period']:2d}  "
              f"ATR={result['atr_stop_mult']:.1f}  "
              f"Ret: {result['total_return_pct']:+7.2f}%  "
              f"Sharpe: {result['sharpe']:5.2f}")

    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Robustness analysis
# ---------------------------------------------------------------------------

def analyze_robustness(oat_results: pd.DataFrame, interaction_results: pd.DataFrame):
    """Compute and print robustness analysis."""
    print()
    print("=" * 70)
    print("PARAMETER ROBUSTNESS ANALYSIS — Plan D")
    print("=" * 70)

    # One-at-a-time summary
    print("\n--- One-at-a-Time Sensitivity ---")
    for param_name in PARAM_GRID:
        subset = oat_results[oat_results["param_name"] == param_name]
        print(f"\n  {param_name}:")
        print(f"  {'Value':>8s}  {'Return':>9s}  {'Sharpe':>7s}  {'MaxDD':>7s}  {'WR':>6s}  {'PF':>6s}  {'Trades':>7s}")
        for _, row in subset.iterrows():
            marker = " ←" if row.get("is_default", False) else ""
            print(f"  {row['param_value']:>8}  {row['total_return_pct']:+8.2f}%  "
                  f"{row['sharpe']:6.2f}  {row['max_dd_pct']:6.1f}%  "
                  f"{row['win_rate_pct']:5.1f}%  {row['profit_factor']:5.2f}  "
                  f"{row['num_trades']:6d}{marker}")

    # Interaction heatmap (text-based)
    print("\n--- Interaction Heatmap: Total Return % ---")
    pivot = interaction_results.pivot_table(
        index="donchian_period", columns="atr_stop_mult",
        values="total_return_pct",
    )
    print(pivot.round(1).to_string())

    print("\n--- Interaction Heatmap: Sharpe Ratio ---")
    pivot_sharpe = interaction_results.pivot_table(
        index="donchian_period", columns="atr_stop_mult",
        values="sharpe",
    )
    print(pivot_sharpe.round(2).to_string())

    # Robustness scores
    all_results = pd.concat([oat_results, interaction_results], ignore_index=True)
    total_configs = len(all_results)
    profitable = (all_results["total_return_pct"] > 0).sum()
    catastrophic = (all_results["max_dd_pct"] > 50).sum()

    robustness_score = profitable / total_configs * 100 if total_configs > 0 else 0

    print()
    print("--- Robustness Summary ---")
    print(f"  Total configurations:   {total_configs}")
    print(f"  Profitable:             {profitable} ({robustness_score:.1f}%)")
    print(f"  Catastrophic (DD>50%):  {catastrophic}")
    print()

    if robustness_score >= 70:
        print(f"  🟢 ROBUST: {robustness_score:.1f}% profitable (threshold: 70%)")
    else:
        print(f"  🔴 NOT ROBUST: {robustness_score:.1f}% profitable (threshold: 70%)")

    if catastrophic > 0:
        print(f"  ⚠️  WARNING: {catastrophic} configurations had DD > 50%")
    else:
        print(f"  ✅ No catastrophic drawdowns")

    print("=" * 70)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    print("Plan D: Parameter Sensitivity Analysis")
    print("-" * 40)

    # Load data
    print("Loading data...")
    ohlcv_dict, funding_dict = load_all_data()

    if not ohlcv_dict:
        print("ERROR: No OHLCV data found!")
        sys.exit(1)

    # Run analyses
    oat_results = one_at_a_time_sweep(ohlcv_dict, funding_dict)
    interaction_results = interaction_grid(ohlcv_dict, funding_dict)

    # Analyze
    analyze_robustness(oat_results, interaction_results)

    # Save results
    results_dir = Path(__file__).resolve().parent.parent / "results"
    results_dir.mkdir(exist_ok=True)

    combined = pd.concat([oat_results, interaction_results], ignore_index=True)
    out_path = results_dir / "plan_d_sensitivity.csv"
    combined.to_csv(out_path, index=False)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
