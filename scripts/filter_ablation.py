#!/usr/bin/env python3
"""
Filter Ablation Study — Plan D Trend Following.

Tests each optional filter individually on top of the baseline
(Donchian breakout + EMA(50) trend) and measures the marginal
change in OOS Sharpe and other metrics.

Usage:
    python3 filter_ablation.py
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_trend import TrendFollowingBacktester, load_all_data
from trend_signals import (
    DEFAULT_PARAMS,
    atr,
    adx_filter,
    combined_entry_signal,
    ema_crossover_confirmation,
    funding_filter,
    volatility_filter,
    volume_confirmation,
)


# ---------------------------------------------------------------------------
# Custom signal generator with toggleable filters
# ---------------------------------------------------------------------------

def generate_signals_with_filters(
    df: pd.DataFrame,
    df_funding: pd.DataFrame | None = None,
    params: dict | None = None,
    *,
    use_adx: bool = False,
    use_volatility: bool = False,
    use_funding: bool = False,
    use_ema_crossover: bool = False,
    use_volume: bool = False,
) -> pd.DataFrame:
    """Generate signals with selectable filters on top of the baseline.

    Baseline (always on): Donchian breakout + EMA(50) trend filter.
    Optional filters are toggled via boolean flags.
    """
    p = {**DEFAULT_PARAMS, **(params or {})}

    # --- Baseline: Donchian + EMA(50) ---
    raw_signal = combined_entry_signal(
        df,
        donchian_period=p["donchian_period"],
        ema_trend_period=p["ema_trend_period"],
    )

    filtered = raw_signal.copy()
    size_mult = pd.Series(1.0, index=df.index)

    # --- Optional filters ---
    if use_adx:
        adx_ok = adx_filter(df, period=p["adx_period"], threshold=p["adx_threshold"])
        filtered[~adx_ok] = 0

    if use_volatility:
        vol_ok = volatility_filter(
            df,
            fast=p["vol_filter_fast"],
            slow=p["vol_filter_slow"],
            low=p["vol_filter_low"],
            high=p["vol_filter_high"],
        )
        filtered[~vol_ok] = 0

    if use_funding:
        fund_long, fund_short, fund_size = funding_filter(
            df_funding, df.index,
            extreme=p["funding_extreme"],
            elevated=p["funding_elevated"],
        )
        filtered[(raw_signal == 1) & ~fund_long] = 0
        filtered[(raw_signal == -1) & ~fund_short] = 0
        size_mult = fund_size

    if use_ema_crossover:
        ema_xo = ema_crossover_confirmation(
            df,
            fast=p["ema_fast"],
            slow=p["ema_slow"],
            lookback=p["ema_confirm_bars"],
        )
        # Crossover must agree with signal direction
        filtered[(filtered == 1) & (ema_xo != 1)] = 0
        filtered[(filtered == -1) & (ema_xo != -1)] = 0

    if use_volume:
        vol_ok = volume_confirmation(df, period=p["volume_period"])
        filtered[~vol_ok] = 0

    # --- ATR and stop prices ---
    atr_val = atr(df, period=p["atr_period"])
    stop_mult = p["atr_stop_mult"]

    stop_price = pd.Series(np.nan, index=df.index)
    long_mask = filtered == 1
    short_mask = filtered == -1
    stop_price[long_mask] = df["close"][long_mask] - stop_mult * atr_val[long_mask]
    stop_price[short_mask] = df["close"][short_mask] + stop_mult * atr_val[short_mask]

    # --- Build output ---
    result = pd.DataFrame(index=df.index)
    result["signal"] = filtered
    result["signal_type"] = "none"
    result.loc[long_mask, "signal_type"] = "long"
    result.loc[short_mask, "signal_type"] = "short"
    result["size_multiplier"] = 1.0
    result.loc[filtered != 0, "size_multiplier"] = size_mult[filtered != 0]
    result["atr"] = atr_val
    result["stop_price"] = stop_price

    return result


# ---------------------------------------------------------------------------
# Filter variants to test
# ---------------------------------------------------------------------------

VARIANTS = [
    ("Baseline",              dict()),
    ("+ADX",                  dict(use_adx=True)),
    ("+Volatility",           dict(use_volatility=True)),
    ("+Funding",              dict(use_funding=True)),
    ("+EMA crossover",        dict(use_ema_crossover=True)),
    ("+Volume",               dict(use_volume=True)),
    ("+ADX +Volatility",      dict(use_adx=True, use_volatility=True)),
    ("+ADX +Funding",         dict(use_adx=True, use_funding=True)),
    ("All filters",           dict(use_adx=True, use_volatility=True, use_funding=True,
                                   use_ema_crossover=True, use_volume=True)),
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 80)
    print("FILTER ABLATION STUDY — Plan D Trend Following")
    print("=" * 80)
    print()

    # Load data
    print("Loading data...")
    ohlcv_dict, funding_dict = load_all_data()
    if not ohlcv_dict:
        print("ERROR: No OHLCV data found in data_4h/")
        return
    print()

    backtest_kwargs = dict(
        initial_equity=10_000,
        risk_per_trade=0.01,
        atr_stop_mult=2.5,
        max_leverage=2.0,
        max_daily_loss=0.03,
        fee_rate=0.0004,
        slippage_bps=5.0,
    )

    results = []

    for name, filter_flags in VARIANTS:
        t0 = time.time()

        # Generate signals per symbol with this filter config
        signals_dict = {}
        for sym, df in ohlcv_dict.items():
            funding = funding_dict.get(sym)
            signals = generate_signals_with_filters(df, funding, **filter_flags)
            signals_dict[sym] = signals

        # Run backtest
        bt = TrendFollowingBacktester(**backtest_kwargs)
        result = bt.run(signals_dict, ohlcv_dict)
        m = result.metrics

        elapsed = time.time() - t0

        row = {
            "variant": name,
            "sharpe": m.get("sharpe", 0.0),
            "win_rate": m.get("win_rate_pct", 0.0),
            "profit_factor": m.get("profit_factor", 0.0),
            "num_trades": m.get("num_trades", 0),
            "max_dd": m.get("max_drawdown_pct", 0.0),
            "total_return": m.get("total_return_pct", 0.0),
            "elapsed": elapsed,
        }
        results.append(row)
        print(f"  {name:<24s} — Sharpe {row['sharpe']:.2f}, "
              f"{row['num_trades']} trades ({elapsed:.1f}s)")

    # Print comparison table
    print()
    print("=" * 95)
    print(f"{'Filter Variant':<24s} | {'Sharpe':>6s} | {'WR%':>5s} | {'PF':>5s} | "
          f"{'Trades':>6s} | {'MaxDD%':>6s} | {'Return%':>8s} | {'ΔSharpe':>7s}")
    print("-" * 95)

    baseline_sharpe = results[0]["sharpe"]

    for r in results:
        delta = r["sharpe"] - baseline_sharpe
        delta_str = f"{delta:+.2f}" if r["variant"] != "Baseline" else "  —"
        pf_str = f"{r['profit_factor']:.2f}" if r["profit_factor"] != float("inf") else "  inf"
        print(f"{r['variant']:<24s} | {r['sharpe']:>6.2f} | {r['win_rate']:>5.1f} | "
              f"{pf_str:>5s} | {r['num_trades']:>6d} | {r['max_dd']:>6.2f} | "
              f"{r['total_return']:>+8.1f} | {delta_str:>7s}")

    print("=" * 95)

    # Recommendations
    print()
    print("RECOMMENDATIONS (filters improving Sharpe by > 0.1):")
    print("-" * 50)
    any_rec = False
    for r in results[1:]:
        delta = r["sharpe"] - baseline_sharpe
        if delta > 0.1:
            print(f"  ✅ {r['variant']:<24s}  ΔSharpe = {delta:+.2f}")
            any_rec = True

    if not any_rec:
        print("  ⚠️  No individual filter improves Sharpe by > 0.1")
        # Show best anyway
        best = max(results[1:], key=lambda r: r["sharpe"])
        delta = best["sharpe"] - baseline_sharpe
        print(f"  Best variant: {best['variant']} (ΔSharpe = {delta:+.2f})")

    print()
    print("FILTERS HURTING performance (Sharpe drop > 0.1):")
    print("-" * 50)
    any_hurt = False
    for r in results[1:]:
        delta = r["sharpe"] - baseline_sharpe
        if delta < -0.1:
            print(f"  ❌ {r['variant']:<24s}  ΔSharpe = {delta:+.2f}")
            any_hurt = True
    if not any_hurt:
        print("  None — all filters are neutral or positive.")


if __name__ == "__main__":
    main()
