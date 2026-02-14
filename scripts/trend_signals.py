#!/usr/bin/env python3
"""
Plan D: Trend Following Signal Generation (Layer 1 + Layer 2).

No ML. No prediction. Pure mechanical rules.

Layer 1 — Entry Signals:
  A. Donchian Channel Breakout (primary)
  B. EMA Trend Filter

Layer 2 — Regime Filters:
  1. ADX trend strength
  2. Volatility regime (ATR ratio)
  3. Funding rate filter
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Layer 1: Entry Signals
# ---------------------------------------------------------------------------

def donchian_breakout(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Donchian Channel breakout signal.

    LONG:  close[t] > highest high of bars [t-period .. t-1]  (exclude current bar)
    SHORT: close[t] < lowest low  of bars [t-period .. t-1]

    Returns: Series of int: 1 (long), -1 (short), 0 (no signal).
    """
    # Use shifted rolling to avoid lookahead (exclude current bar)
    upper = df["high"].shift(1).rolling(window=period).max()
    lower = df["low"].shift(1).rolling(window=period).min()

    signal = pd.Series(0, index=df.index, dtype=int)
    signal[df["close"] > upper] = 1
    signal[df["close"] < lower] = -1
    return signal


def ema_crossover_confirmation(
    df: pd.DataFrame, fast: int = 9, slow: int = 21, lookback: int = 5
) -> pd.Series:
    """Dual EMA crossover confirmation.

    Bullish:  EMA(fast) > EMA(slow) AND crossed above within `lookback` bars.
    Bearish:  EMA(fast) < EMA(slow) AND crossed below within `lookback` bars.

    Returns: Series of int: 1 (bullish), -1 (bearish), 0 (no confirmation).
    """
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()

    diff = ema_fast - ema_slow
    cross_up = (diff > 0) & (diff.shift(1) <= 0)  # just crossed above
    cross_down = (diff < 0) & (diff.shift(1) >= 0)  # just crossed below

    # Has there been a cross within the last `lookback` bars?
    recent_cross_up = cross_up.rolling(window=lookback, min_periods=1).max().astype(bool)
    recent_cross_down = cross_down.rolling(window=lookback, min_periods=1).max().astype(bool)

    signal = pd.Series(0, index=df.index, dtype=int)
    signal[(diff > 0) & recent_cross_up] = 1
    signal[(diff < 0) & recent_cross_down] = -1
    return signal


def ema_trend_filter(df: pd.DataFrame, period: int = 50) -> pd.Series:
    """EMA trend direction filter.

    Returns: Series of int: 1 (close above EMA), -1 (below).
    """
    ema = df["close"].ewm(span=period, adjust=False).mean()
    return pd.Series(np.where(df["close"] > ema, 1, -1), index=df.index, dtype=int)


def volume_confirmation(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Volume confirmation: current volume > rolling average.

    Returns: Series of bool.
    """
    avg_vol = df["volume"].rolling(window=period).mean()
    return df["volume"] > avg_vol


def combined_entry_signal(
    df: pd.DataFrame,
    donchian_period: int = 20,
    ema_trend_period: int = 50,
) -> pd.Series:
    """Combined entry signal: Donchian AND EMA trend filter.

    Returns: Series of int: 1 (long), -1 (short), 0 (no signal).
    """
    sig_donchian = donchian_breakout(df, donchian_period)
    sig_trend = ema_trend_filter(df, ema_trend_period)

    signal = pd.Series(0, index=df.index, dtype=int)

    long_mask = (sig_donchian == 1) & (sig_trend == 1)
    short_mask = (sig_donchian == -1) & (sig_trend == -1)

    signal[long_mask] = 1
    signal[short_mask] = -1
    return signal


# ---------------------------------------------------------------------------
# Layer 2: Regime Filters
# ---------------------------------------------------------------------------

def _true_range(df: pd.DataFrame) -> pd.Series:
    """True Range = max(H-L, |H-prev_C|, |L-prev_C|)."""
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift(1)).abs()
    lc = (df["low"] - df["close"].shift(1)).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder's smoothing)."""
    tr = _true_range(df)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def adx_filter(df: pd.DataFrame, period: int = 14, threshold: float = 20.0) -> pd.Series:
    """ADX trend strength filter.

    Returns: Series of bool — True if ADX > threshold (trend exists).
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    # Directional movement
    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr = _true_range(df)

    # Wilder smoothing (alpha = 1/period)
    alpha = 1.0 / period
    atr_smooth = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_smooth
    minus_di = 100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_smooth

    # DX and ADX
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = dx.ewm(alpha=alpha, adjust=False).mean()

    return adx_val > threshold


def volatility_filter(
    df: pd.DataFrame,
    fast: int = 14,
    slow: int = 50,
    low: float = 0.5,
    high: float = 2.5,
) -> pd.Series:
    """Volatility regime filter: ATR(fast) / ATR(slow) within [low, high].

    Returns: Series of bool — True if volatility is normal.
    """
    atr_fast = atr(df, fast)
    atr_slow = atr(df, slow)
    ratio = atr_fast / atr_slow.replace(0, np.nan)
    return (ratio > low) & (ratio < high)


def funding_filter(
    df_funding: pd.DataFrame | None,
    index: pd.DatetimeIndex,
    extreme: float = 0.0005,
    elevated: float = 0.0003,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Funding rate filter.

    Uses the last known funding rate at or before each bar timestamp.
    Funding is 8-hourly; we use a rolling mean of last 3 values (~24h).

    Returns:
        (allow_long, allow_short, size_multiplier) — all indexed to `index`.
    """
    allow_long = pd.Series(True, index=index)
    allow_short = pd.Series(True, index=index)
    size_mult = pd.Series(1.0, index=index)

    if df_funding is None or df_funding.empty:
        return allow_long, allow_short, size_mult

    # Reindex funding to bar timestamps using forward-fill (last known value)
    funding_aligned = (
        df_funding["fundingRate"]
        .reindex(index, method="ffill")
    )

    # Rolling 8h average (funding is every 8h, so ~3 periods for 24h context)
    # On 4h bars, 3 funding periods ≈ 6 bars back, but funding is sparser.
    # Use a 24h rolling mean (6 bars on 4h timeframe).
    funding_avg = funding_aligned.rolling(window=6, min_periods=1).mean()

    # Block long if market extremely long
    allow_long = funding_avg <= extreme
    # Block short if market extremely short
    allow_short = funding_avg >= -extreme

    # Reduce size if elevated
    elevated_mask = funding_avg.abs() > elevated
    size_mult[elevated_mask] = 0.5

    return allow_long, allow_short, size_mult


# ---------------------------------------------------------------------------
# Full Signal Pipeline
# ---------------------------------------------------------------------------

DEFAULT_PARAMS = {
    "donchian_period": 20,
    "ema_fast": 9,
    "ema_slow": 21,
    "ema_confirm_bars": 5,
    "ema_trend_period": 50,
    "volume_period": 20,
    "atr_period": 14,
    "atr_stop_mult": 2.5,
    "adx_period": 14,
    "adx_threshold": 20.0,
    "vol_filter_fast": 14,
    "vol_filter_slow": 50,
    "vol_filter_low": 0.5,
    "vol_filter_high": 2.5,
    "funding_extreme": 0.0005,
    "funding_elevated": 0.0003,
}


def generate_signals(
    df: pd.DataFrame,
    df_funding: pd.DataFrame | None = None,
    params: dict | None = None,
) -> pd.DataFrame:
    """Full signal generation pipeline: entries + filters → final signals.

    Args:
        df: OHLCV DataFrame (DatetimeIndex, columns: open, high, low, close, volume).
        df_funding: Funding rate DataFrame (DatetimeIndex, column: fundingRate).
        params: Strategy parameters (uses DEFAULT_PARAMS if None).

    Returns:
        DataFrame with columns:
            signal (int): -1, 0, 1
            signal_type (str): 'long', 'short', 'none'
            size_multiplier (float): 0.5 or 1.0
            atr (float): ATR(14) value
            stop_price (float): initial stop price
    """
    p = {**DEFAULT_PARAMS, **(params or {})}

    # --- Layer 1: Entry signals ---
    raw_signal = combined_entry_signal(
        df,
        donchian_period=p["donchian_period"],
        ema_trend_period=p["ema_trend_period"],
    )

    # --- Layer 2: Regime filters ---
    adx_ok = adx_filter(df, period=p["adx_period"], threshold=p["adx_threshold"])
    vol_ok = volatility_filter(
        df,
        fast=p["vol_filter_fast"],
        slow=p["vol_filter_slow"],
        low=p["vol_filter_low"],
        high=p["vol_filter_high"],
    )
    fund_long, fund_short, fund_size = funding_filter(
        df_funding, df.index,
        extreme=p["funding_extreme"],
        elevated=p["funding_elevated"],
    )

    # Apply filters
    filtered = raw_signal.copy()
    # Block if ADX or volatility says no
    filtered[~adx_ok] = 0
    filtered[~vol_ok] = 0
    # Block specific directions based on funding
    filtered[(raw_signal == 1) & ~fund_long] = 0
    filtered[(raw_signal == -1) & ~fund_short] = 0

    # --- Compute ATR and stop prices ---
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
    result.loc[filtered != 0, "size_multiplier"] = fund_size[filtered != 0]
    result["atr"] = atr_val
    result["stop_price"] = stop_price

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    """Load BTC 4h data, generate signals, print summary."""
    data_dir = Path(__file__).resolve().parent.parent / "data_4h"

    # Load OHLCV
    ohlcv_path = data_dir / "BTC_USDT_4h_2190d.parquet"
    if not ohlcv_path.exists():
        # Try CSV fallback
        ohlcv_path = data_dir / "BTC_USDT_4h_2190d.csv"
    print(f"Loading OHLCV from {ohlcv_path}")
    df = pd.read_parquet(ohlcv_path) if str(ohlcv_path).endswith(".parquet") else pd.read_csv(ohlcv_path, parse_dates=["timestamp"], index_col="timestamp")

    # Load funding
    funding_path = data_dir / "funding" / "BTC_USDT_funding_2190d.parquet"
    df_funding = None
    if funding_path.exists():
        print(f"Loading funding from {funding_path}")
        df_funding = pd.read_parquet(funding_path)

    print(f"Data shape: {df.shape}, range: {df.index[0]} → {df.index[-1]}")
    print()

    # Generate signals
    signals = generate_signals(df, df_funding)

    # Summary
    total = len(signals)
    longs = (signals["signal"] == 1).sum()
    shorts = (signals["signal"] == -1).sum()
    pct = (longs + shorts) / total * 100

    print("=" * 60)
    print("SIGNAL SUMMARY (BTC/USDT 4h)")
    print("=" * 60)
    print(f"Total bars:      {total:,}")
    print(f"Long signals:    {longs:,}")
    print(f"Short signals:   {shorts:,}")
    print(f"Signal rate:     {pct:.2f}%")
    print(f"Avg ATR:         {signals['atr'].mean():.2f}")
    print()

    # Show ablation (Layer 1 only vs full)
    raw = combined_entry_signal(df)
    raw_longs = (raw == 1).sum()
    raw_shorts = (raw == -1).sum()
    print("--- Ablation ---")
    print(f"Layer 1 only:    {raw_longs + raw_shorts:,} signals ({raw_longs} L / {raw_shorts} S)")
    print(f"After filters:   {longs + shorts:,} signals ({longs} L / {shorts} S)")
    print(f"Filter rate:     {(1 - (longs + shorts) / max(raw_longs + raw_shorts, 1)) * 100:.1f}% blocked")

    # Per-year breakdown
    print()
    print("--- Per-Year Breakdown ---")
    signals["year"] = signals.index.year
    for year, grp in signals.groupby("year"):
        n_l = (grp["signal"] == 1).sum()
        n_s = (grp["signal"] == -1).sum()
        print(f"  {year}: {n_l + n_s:3d} signals ({n_l:3d} L / {n_s:3d} S)")
    signals.drop(columns=["year"], inplace=True)


if __name__ == "__main__":
    main()
