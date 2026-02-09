"""Enhanced entry labeling using 1H candles for intrabar simulation.

Same breakout detection as label_regime.py (on 4H candles), but evaluates
stop/target hits using the higher-resolution 1H candle path. This resolves
"both hit in same 4H bar" ambiguity and gives cleaner labels.

The key insight: we train on 4H features but use 1H data ONLY for more
accurate outcome evaluation. At inference time, the model still receives
4H features — no distribution mismatch.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import ta


def label_entries_1h(
    df_4h: pd.DataFrame,
    df_1h: pd.DataFrame,
    donchian_period: int = 20,
    atr_period: int = 14,
    atr_stop_mult: float = 3.0,
    eval_horizon: int = 6,
) -> pd.DataFrame:
    """Identify breakout entries on 4H candles, label using 1H intrabar simulation.

    Parameters
    ----------
    df_4h : pd.DataFrame
        4H candles with features already computed (call build_regime_features first).
        Must have columns: open, high, low, close, volume and DatetimeIndex.
    df_1h : pd.DataFrame
        1H candles (raw OHLCV). Must have columns: open, high, low, close, volume
        and DatetimeIndex.
    donchian_period : int
        Lookback for Donchian channel on 4H bars (default 20).
    atr_period : int
        ATR period on 4H bars for stop distance (default 14).
    atr_stop_mult : float
        ATR multiplier for stop distance (default 3.0).
    eval_horizon : int
        Number of 4H bars to look ahead (default 6 = 24h).
        Translates to 6×4 = 24 one-hour candles for intrabar simulation.

    Returns
    -------
    pd.DataFrame
        Rows where a breakout occurred, with added columns:
        - side: "LONG" or "SHORT"
        - entry_price: close price at entry
        - label: 1 (SAFE_TO_TRADE) or 0 (DANGER_ZONE)
    """
    df_4h = df_4h.copy()

    # --- Donchian channels on 4H (shifted — exclude current bar) ---
    upper = df_4h["high"].shift(1).rolling(window=donchian_period).max()
    lower = df_4h["low"].shift(1).rolling(window=donchian_period).min()

    # --- ATR on 4H for stop distance ---
    atr = ta.volatility.average_true_range(
        df_4h["high"], df_4h["low"], df_4h["close"], window=atr_period
    )

    # --- Identify breakouts on 4H ---
    long_breakout = df_4h["close"] > upper
    short_breakout = df_4h["close"] < lower

    # Pre-sort 1H data for efficient lookups
    df_1h_sorted = df_1h.sort_index()
    h1_timestamps = df_1h_sorted.index
    h1_highs = df_1h_sorted["high"].values
    h1_lows = df_1h_sorted["low"].values

    entries = []
    n_4h = len(df_4h)
    eval_hours = eval_horizon * 4  # convert 4H bars to hours

    for i in range(n_4h):
        is_long = bool(long_breakout.iloc[i]) if not pd.isna(long_breakout.iloc[i]) else False
        is_short = bool(short_breakout.iloc[i]) if not pd.isna(short_breakout.iloc[i]) else False

        if not is_long and not is_short:
            continue

        atr_val = atr.iloc[i]
        if pd.isna(atr_val) or atr_val <= 0:
            continue

        entry_price = df_4h["close"].iloc[i]
        stop_distance = atr_stop_mult * atr_val
        side = "LONG" if is_long else "SHORT"

        if side == "LONG":
            stop_level = entry_price - stop_distance
            target_level = entry_price + stop_distance  # 1R target
        else:
            stop_level = entry_price + stop_distance
            target_level = entry_price - stop_distance  # 1R target

        # --- Evaluate outcome using 1H candles ---
        entry_time = df_4h.index[i]
        # Look at 1H candles AFTER the entry (next bar onward)
        # Entry happens at 4H close, so start from next hour
        start_time = entry_time + pd.Timedelta(hours=4)  # next 4H bar starts here
        end_time = entry_time + pd.Timedelta(hours=4 + eval_hours)

        # Get 1H candles in the evaluation window
        mask = (h1_timestamps >= start_time) & (h1_timestamps < end_time)
        window_indices = np.where(mask)[0]

        label = 0  # default: DANGER_ZONE

        for j in window_indices:
            if side == "LONG":
                # Pessimistic: check stop first (using low), then target (using high)
                if h1_lows[j] <= stop_level:
                    label = 0
                    break
                if h1_highs[j] >= target_level:
                    label = 1
                    break
            else:  # SHORT
                # Pessimistic: check stop first (using high), then target (using low)
                if h1_highs[j] >= stop_level:
                    label = 0
                    break
                if h1_lows[j] <= target_level:
                    label = 1
                    break

        entries.append({
            "idx": df_4h.index[i],
            "side": side,
            "entry_price": entry_price,
            "label": label,
        })

    if not entries:
        return pd.DataFrame()

    entry_df = pd.DataFrame(entries).set_index("idx")
    entry_df.index.name = df_4h.index.name

    result = df_4h.loc[entry_df.index].copy()
    result["side"] = entry_df["side"]
    result["entry_price"] = entry_df["entry_price"]
    result["label"] = entry_df["label"]

    return result
