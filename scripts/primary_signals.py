#!/usr/bin/env python3
"""Rule-based primary signal generators for trend following.

These generate many candidate signals; the meta-model (train_meta_model.py)
learns to filter them. No ML here — pure rule-based.

Signal types:
  - Trend continuation: close > EMA21 & EMA50, RSI > 50, daily uptrend
  - Breakout: 20-bar high breakout + volume surge + daily uptrend
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import ta

# ---------------------------------------------------------------------------
# Inline feature helpers (used when features are missing from DataFrame)
# ---------------------------------------------------------------------------


def _ensure_ema(df: pd.DataFrame, col: str, window: int) -> pd.Series:
    """Return EMA series, computing inline if column is missing."""
    if col in df.columns:
        return df[col]
    return ta.trend.ema_indicator(df["close"], window=window)


def _ensure_rsi(df: pd.DataFrame, col: str, window: int) -> pd.Series:
    """Return RSI series, computing inline if column is missing."""
    if col in df.columns:
        return df[col]
    return ta.momentum.rsi(df["close"], window=window)


def _ensure_volume_ratio(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """Return volume ratio, computing inline if column is missing."""
    if "volume_ratio" in df.columns:
        return df["volume_ratio"]
    return df["volume"] / df["volume"].rolling(window=lookback).mean()


def _ensure_daily_trend(df: pd.DataFrame) -> pd.Series:
    """Return daily_trend series (1=up, -1=down, 0=neutral).

    If ``daily_trend`` column exists, use it directly.
    Otherwise approximate using a 42-bar SMA (≈7 days on 4h) as a proxy.
    """
    if "daily_trend" in df.columns:
        return df["daily_trend"]
    sma_42 = df["close"].rolling(window=42).mean()
    trend = pd.Series(0, index=df.index, dtype=int)
    trend[df["close"] > sma_42] = 1
    trend[df["close"] < sma_42] = -1
    return trend


# ---------------------------------------------------------------------------
# Signal generators
# ---------------------------------------------------------------------------


def trend_continuation_signals(df: pd.DataFrame) -> pd.Series:
    """Long signal when ALL conditions met:

    - close > EMA21
    - close > EMA50
    - RSI14 > 50
    - daily_trend == 1 (if available, else skip)

    Args:
        df: DataFrame with OHLCV (and optionally pre-computed features).

    Returns:
        pd.Series of bool — True where signal fires.
    """
    ema_21 = _ensure_ema(df, "ema_21", 21)
    ema_50 = _ensure_ema(df, "ema_50", 50)
    rsi_14 = _ensure_rsi(df, "rsi_14", 14)

    cond = (df["close"] > ema_21) & (df["close"] > ema_50) & (rsi_14 > 50)

    daily_trend = _ensure_daily_trend(df)
    # Only apply daily_trend filter if we have meaningful data (not all 0)
    if (daily_trend != 0).any():
        cond = cond & (daily_trend == 1)

    return cond.fillna(False).astype(bool)


def breakout_signals(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """Long signal when ALL conditions met:

    - close > highest high of last ``lookback`` bars
    - volume_ratio > 1.5
    - daily_trend == 1 (if available, else skip)

    Args:
        df: DataFrame with OHLCV (and optionally pre-computed features).
        lookback: Number of bars for the rolling high (default 20).

    Returns:
        pd.Series of bool — True where signal fires.
    """
    highest_high = df["high"].rolling(window=lookback).max().shift(1)
    vol_ratio = _ensure_volume_ratio(df)

    cond = (df["close"] > highest_high) & (vol_ratio > 1.5)

    daily_trend = _ensure_daily_trend(df)
    if (daily_trend != 0).any():
        cond = cond & (daily_trend == 1)

    return cond.fillna(False).astype(bool)


def combined_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Union of trend continuation OR breakout signals.

    Args:
        df: DataFrame with OHLCV (and optionally pre-computed features).

    Returns:
        DataFrame with columns:
          - signal: bool (any signal fires)
          - signal_type: 'trend' | 'breakout' | 'both' | None
    """
    trend = trend_continuation_signals(df)
    brk = breakout_signals(df)

    signal = trend | brk

    signal_type = pd.Series(None, index=df.index, dtype=object)
    signal_type[trend & ~brk] = "trend"
    signal_type[~trend & brk] = "breakout"
    signal_type[trend & brk] = "both"

    return pd.DataFrame(
        {
            "signal": signal,
            "signal_type": signal_type,
        },
        index=df.index,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_signal_stats(df: pd.DataFrame, signals: pd.DataFrame, symbol: str) -> None:
    """Print summary statistics for generated signals."""
    total_bars = len(df)
    n_signals = signals["signal"].sum()
    pct = n_signals / total_bars * 100 if total_bars > 0 else 0

    print(f"\n{'=' * 60}")
    print(f"PRIMARY SIGNAL STATS — {symbol}")
    print(f"{'=' * 60}")
    print(f"Total bars:           {total_bars}")
    print(f"Total signals:        {int(n_signals)} ({pct:.1f}%)")
    print(f"Date range:           {df.index[0]} to {df.index[-1]}")

    # Breakdown by type
    if n_signals > 0:
        type_counts = signals.loc[signals["signal"], "signal_type"].value_counts()
        print(f"\nSignal type breakdown:")
        for stype, cnt in type_counts.items():
            print(f"  {stype:12s}: {cnt:5d} ({cnt / n_signals * 100:.1f}%)")

    # Signals per day (4h candles → 6 per day)
    if total_bars > 0:
        n_days = (df.index[-1] - df.index[0]).days
        if n_days > 0:
            signals_per_day = n_signals / n_days
            print(f"\nSignals/day:          {signals_per_day:.2f}")

    # Monthly breakdown
    sig_bars = df[signals["signal"]].copy()
    if len(sig_bars) > 0:
        sig_bars["month"] = sig_bars.index.to_period("M")
        monthly = sig_bars.groupby("month").size()
        print(f"\nMonthly signal counts (last 12 months):")
        for month, cnt in monthly.tail(12).items():
            print(f"  {month}: {cnt:4d}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate rule-based primary trading signals"
    )
    parser.add_argument("--data-dir", type=str, default="data_4h")
    parser.add_argument("--symbol", type=str, default="BTC/USDT")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    pattern = f"{args.symbol.replace('/', '_')}_*.parquet"
    files = sorted(data_dir.glob(pattern))

    if not files:
        raise ValueError(f"No data for {args.symbol} in {data_dir}")

    dfs = []
    for f in files:
        print(f"Loading {f}")
        df = pd.read_parquet(f)
        dfs.append(df)

    df = pd.concat(dfs).sort_index()
    df = df[~df.index.duplicated(keep="last")]

    signals = combined_signals(df)
    _print_signal_stats(df, signals, args.symbol)


if __name__ == "__main__":
    main()
