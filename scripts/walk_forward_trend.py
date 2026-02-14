#!/usr/bin/env python3
"""
Plan D: Walk-Forward Validation for Trend Following Strategy.

Key difference from Plan B walk-forward:
  - NO model retraining (no ML model exists)
  - Same parameters used across ALL windows
  - Tests robustness and regime-independence

The strategy must pass a profitability gate to proceed to Go integration.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_trend import TrendFollowingBacktester, load_all_data, print_metrics
from trend_signals import DEFAULT_PARAMS, generate_signals


@dataclass
class WalkForwardResult:
    window_results: list[dict]
    aggregate_metrics: dict
    gate_result: dict
    per_symbol_consistency: dict


# ---------------------------------------------------------------------------
# Profitability Gate Thresholds (revised from oracle review)
# ---------------------------------------------------------------------------

GATE_THRESHOLDS = {
    "win_rate": 0.30,                # > 30%
    "profit_factor": 1.2,            # > 1.2
    "sharpe": 0.6,                   # > 0.6 (OOS annualized)
    "avg_winner_loser_ratio": 2.0,   # > 2.0 (key metric for trend following)
    "max_drawdown": 0.35,            # < 35%
    "consistency": 0.60,             # > 60% windows profitable
    "per_symbol_consistency": 0.50,  # each symbol > 50% windows profitable
}


def walk_forward_validate(
    data_dict: dict[str, pd.DataFrame],
    funding_dict: dict[str, pd.DataFrame] | None = None,
    window_size: int = 180,
    step_size: int = 30,
    params: dict | None = None,
    backtest_kwargs: dict | None = None,
) -> WalkForwardResult:
    """Run walk-forward validation.

    Args:
        data_dict: {symbol: OHLCV DataFrame}
        funding_dict: {symbol: funding DataFrame}
        window_size: days per test window
        step_size: days between window starts
        params: strategy parameters (defaults if None)
        backtest_kwargs: kwargs for TrendFollowingBacktester

    Returns:
        WalkForwardResult with per-window, aggregate, and gate results.
    """
    if params is None:
        params = DEFAULT_PARAMS
    if backtest_kwargs is None:
        backtest_kwargs = {}
    if funding_dict is None:
        funding_dict = {}

    # Find common date range
    min_dates = []
    max_dates = []
    for sym, df in data_dict.items():
        min_dates.append(df.index.min())
        max_dates.append(df.index.max())

    common_start = max(min_dates)
    common_end = min(max_dates)
    print(f"Common date range: {common_start.date()} → {common_end.date()}")
    print(f"Total days: {(common_end - common_start).days}")
    print(f"Window: {window_size}d, Step: {step_size}d")

    # Generate windows
    windows = []
    ws = pd.Timedelta(days=window_size)
    ss = pd.Timedelta(days=step_size)
    window_start = common_start
    while window_start + ws <= common_end:
        window_end = window_start + ws
        windows.append((window_start, window_end))
        window_start += ss

    print(f"Number of windows: {len(windows)}")
    print()

    # Run backtest on each window
    window_results = []
    per_symbol_windows: dict[str, list[bool]] = {sym: [] for sym in data_dict}

    for i, (w_start, w_end) in enumerate(windows):
        # Slice data for this window
        ohlcv_window = {}
        signals_window = {}
        for sym, df in data_dict.items():
            df_slice = df[(df.index >= w_start) & (df.index < w_end)]
            if len(df_slice) < 50:  # minimum bars
                continue
            ohlcv_window[sym] = df_slice

            funding = funding_dict.get(sym)
            if funding is not None:
                funding_slice = funding[(funding.index >= w_start) & (funding.index < w_end)]
            else:
                funding_slice = None

            signals = generate_signals(df_slice, funding_slice, params)
            signals_window[sym] = signals

        if not signals_window:
            continue

        # Run backtest
        bt = TrendFollowingBacktester(**backtest_kwargs)
        result = bt.run(signals_window, ohlcv_window)
        m = result.metrics

        is_profitable = m.get("total_return", 0) > 0

        window_result = {
            "window_idx": i + 1,
            "start": w_start.strftime("%Y-%m-%d"),
            "end": w_end.strftime("%Y-%m-%d"),
            "total_return_pct": m.get("total_return_pct", 0),
            "sharpe": m.get("sharpe", 0),
            "max_dd_pct": m.get("max_drawdown_pct", 0),
            "win_rate_pct": m.get("win_rate_pct", 0),
            "profit_factor": m.get("profit_factor", 0),
            "avg_wl_ratio": m.get("avg_winner_loser_ratio", 0),
            "num_trades": m.get("num_trades", 0),
            "expectancy_pct": m.get("expectancy_pct", 0),
            "profitable": is_profitable,
        }
        window_results.append(window_result)

        # Per-symbol consistency tracking
        for sym in data_dict:
            sym_trades = [t for t in result.trades if t.symbol == sym]
            sym_pnl = sum(t.pnl for t in sym_trades)
            per_symbol_windows[sym].append(sym_pnl > 0)

        status = "✅" if is_profitable else "❌"
        print(
            f"  Window {i + 1:3d}/{len(windows)} "
            f"[{w_start.strftime('%Y-%m-%d')} → {w_end.strftime('%Y-%m-%d')}] "
            f"Ret: {m.get('total_return_pct', 0):+6.2f}%  "
            f"Sharpe: {m.get('sharpe', 0):5.2f}  "
            f"WR: {m.get('win_rate_pct', 0):5.1f}%  "
            f"Trades: {m.get('num_trades', 0):3d}  "
            f"{status}"
        )

    # Aggregate metrics
    if not window_results:
        print("ERROR: No valid windows!")
        return WalkForwardResult([], {}, {}, {})

    profitable_windows = sum(1 for w in window_results if w["profitable"])
    total_windows = len(window_results)
    consistency = profitable_windows / total_windows if total_windows > 0 else 0

    # Pool across windows
    avg_return = np.mean([w["total_return_pct"] for w in window_results])
    avg_sharpe = np.mean([w["sharpe"] for w in window_results])
    max_dd = max(w["max_dd_pct"] for w in window_results)
    avg_wr = np.mean([w["win_rate_pct"] for w in window_results])
    total_trades = sum(w["num_trades"] for w in window_results)

    # Weighted profit factor and W/L ratio (weight by trade count)
    pf_values = [w["profit_factor"] for w in window_results if w["num_trades"] > 0]
    wl_values = [w["avg_wl_ratio"] for w in window_results if w["num_trades"] > 0]
    avg_pf = np.mean(pf_values) if pf_values else 0
    avg_wl = np.mean(wl_values) if wl_values else 0

    aggregate = {
        "avg_return_pct": avg_return,
        "avg_sharpe": avg_sharpe,
        "max_drawdown_pct": max_dd,
        "avg_win_rate_pct": avg_wr,
        "avg_profit_factor": avg_pf,
        "avg_winner_loser_ratio": avg_wl,
        "total_trades": total_trades,
        "consistency_pct": consistency * 100,
        "profitable_windows": profitable_windows,
        "total_windows": total_windows,
    }

    # Per-symbol consistency
    sym_consistency = {}
    for sym, results in per_symbol_windows.items():
        if results:
            sym_consistency[sym] = sum(results) / len(results)
        else:
            sym_consistency[sym] = 0.0

    # Gate check
    gate = {}
    gate["win_rate"] = {
        "value": avg_wr / 100,
        "threshold": GATE_THRESHOLDS["win_rate"],
        "pass": avg_wr / 100 > GATE_THRESHOLDS["win_rate"],
    }
    gate["profit_factor"] = {
        "value": avg_pf,
        "threshold": GATE_THRESHOLDS["profit_factor"],
        "pass": avg_pf > GATE_THRESHOLDS["profit_factor"],
    }
    gate["sharpe"] = {
        "value": avg_sharpe,
        "threshold": GATE_THRESHOLDS["sharpe"],
        "pass": avg_sharpe > GATE_THRESHOLDS["sharpe"],
    }
    gate["avg_winner_loser_ratio"] = {
        "value": avg_wl,
        "threshold": GATE_THRESHOLDS["avg_winner_loser_ratio"],
        "pass": avg_wl > GATE_THRESHOLDS["avg_winner_loser_ratio"],
    }
    gate["max_drawdown"] = {
        "value": max_dd / 100,
        "threshold": GATE_THRESHOLDS["max_drawdown"],
        "pass": max_dd / 100 < GATE_THRESHOLDS["max_drawdown"],
    }
    gate["consistency"] = {
        "value": consistency,
        "threshold": GATE_THRESHOLDS["consistency"],
        "pass": consistency > GATE_THRESHOLDS["consistency"],
    }

    # Per-symbol gate
    all_symbols_pass = all(
        v >= GATE_THRESHOLDS["per_symbol_consistency"]
        for v in sym_consistency.values()
    )
    gate["per_symbol_consistency"] = {
        "value": sym_consistency,
        "threshold": GATE_THRESHOLDS["per_symbol_consistency"],
        "pass": all_symbols_pass,
    }

    return WalkForwardResult(
        window_results=window_results,
        aggregate_metrics=aggregate,
        gate_result=gate,
        per_symbol_consistency=sym_consistency,
    )


def print_gate_results(result: WalkForwardResult):
    """Pretty-print profitability gate results."""
    print()
    print("=" * 70)
    print("PROFITABILITY GATE — Plan D: Trend Following")
    print("=" * 70)

    agg = result.aggregate_metrics
    print(f"  Windows:            {agg['profitable_windows']}/{agg['total_windows']} profitable")
    print(f"  Avg return/window:  {agg['avg_return_pct']:+.2f}%")
    print(f"  Avg Sharpe:         {agg['avg_sharpe']:.2f}")
    print(f"  Max drawdown:       {agg['max_drawdown_pct']:.2f}%")
    print(f"  Avg win rate:       {agg['avg_win_rate_pct']:.1f}%")
    print(f"  Avg profit factor:  {agg['avg_profit_factor']:.2f}")
    print(f"  Avg W/L ratio:      {agg['avg_winner_loser_ratio']:.2f}")
    print(f"  Total trades:       {agg['total_trades']}")
    print()

    print("--- Gate Criteria ---")
    all_pass = True
    for criterion, info in result.gate_result.items():
        if criterion == "per_symbol_consistency":
            status = "✅ PASS" if info["pass"] else "❌ FAIL"
            print(f"  {criterion:30s}  {status}")
            for sym, val in info["value"].items():
                sym_status = "✅" if val >= info["threshold"] else "❌"
                print(f"    {sym:20s} {val * 100:.1f}% (need >{info['threshold'] * 100:.0f}%)  {sym_status}")
        else:
            val = info["value"]
            thresh = info["threshold"]
            status = "✅ PASS" if info["pass"] else "❌ FAIL"
            if isinstance(val, float):
                print(f"  {criterion:30s}  {val:.4f} vs {thresh:.4f}  {status}")
            else:
                print(f"  {criterion:30s}  {val} vs {thresh}  {status}")

        if not info["pass"]:
            all_pass = False

    print()
    if all_pass:
        print("🟢 OVERALL: ALL GATES PASSED — Proceed to Phase 2 (Go Integration)")
    else:
        print("🔴 OVERALL: GATE FAILED — Analyze failures before proceeding")
    print("=" * 70)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    print("Plan D: Walk-Forward Validation")
    print("-" * 40)

    # Load data
    print("Loading data...")
    ohlcv_dict, funding_dict = load_all_data()

    if not ohlcv_dict:
        print("ERROR: No OHLCV data found!")
        sys.exit(1)

    # Run walk-forward
    print("\nRunning walk-forward validation...")
    print()

    result = walk_forward_validate(
        data_dict=ohlcv_dict,
        funding_dict=funding_dict,
        window_size=180,
        step_size=30,
        params=DEFAULT_PARAMS,
        backtest_kwargs={
            "initial_equity": 10_000,
            "risk_per_trade": 0.01,
            "atr_stop_mult": 2.5,
            "max_leverage": 2.0,
            "max_daily_loss": 0.03,
        },
    )

    # Print gate results
    print_gate_results(result)

    # Save per-window results
    results_dir = Path(__file__).resolve().parent.parent / "results"
    results_dir.mkdir(exist_ok=True)

    wf_df = pd.DataFrame(result.window_results)
    wf_path = results_dir / "plan_d_walk_forward.csv"
    wf_df.to_csv(wf_path, index=False)
    print(f"\nWalk-forward results saved to {wf_path}")


if __name__ == "__main__":
    main()
