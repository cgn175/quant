"""Entry labeling for the Regime Classifier (Traffic Light).

Identifies Donchian breakout entries and labels each as:
    1 = SAFE_TO_TRADE  (target hit before stop within horizon)
    0 = DANGER_ZONE    (stop hit first, or neither hit)

The label captures "was this a profitable entry?" — the regime classifier
then learns the *conditions* that predict winning entries, not direction.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import ta


def label_entries(
    df: pd.DataFrame,
    donchian_period: int = 20,
    atr_period: int = 14,
    atr_stop_mult: float = 3.0,
    eval_horizon: int = 6,
) -> pd.DataFrame:
    """Identify breakout entries and label them as SAFE (1) or DANGER (0).

    Parameters
    ----------
    df : pd.DataFrame
        Must have columns: open, high, low, close, volume and a DatetimeIndex.
        Features should already be computed (call build_regime_features first).
    donchian_period : int
        Lookback for Donchian channel (default 20).
    atr_period : int
        ATR period for stop distance (default 14).
    atr_stop_mult : float
        ATR multiplier for stop distance (default 3.0).
    eval_horizon : int
        Number of bars to look ahead for outcome (default 6 = 24h on 4H).

    Returns
    -------
    pd.DataFrame
        Rows where a breakout occurred, with added columns:
        - side: "LONG" or "SHORT"
        - entry_price: close price at entry
        - label: 1 (SAFE_TO_TRADE) or 0 (DANGER_ZONE)
    """
    df = df.copy()

    # --- Donchian channels (shifted — exclude current bar) ---
    upper = df["high"].shift(1).rolling(window=donchian_period).max()
    lower = df["low"].shift(1).rolling(window=donchian_period).min()

    # --- ATR for stop distance ---
    atr = ta.volatility.average_true_range(
        df["high"], df["low"], df["close"], window=atr_period
    )

    # --- Identify breakouts ---
    long_breakout = df["close"] > upper
    short_breakout = df["close"] < lower

    # Build entry rows
    entries = []
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    for i in range(n):
        is_long = bool(long_breakout.iloc[i]) if not pd.isna(long_breakout.iloc[i]) else False
        is_short = bool(short_breakout.iloc[i]) if not pd.isna(short_breakout.iloc[i]) else False

        if not is_long and not is_short:
            continue

        atr_val = atr.iloc[i]
        if pd.isna(atr_val) or atr_val <= 0:
            continue

        entry_price = closes[i]
        stop_distance = atr_stop_mult * atr_val
        side = "LONG" if is_long else "SHORT"

        if side == "LONG":
            stop_level = entry_price - stop_distance
            target_level = entry_price + stop_distance  # 1R target
        else:
            stop_level = entry_price + stop_distance
            target_level = entry_price - stop_distance  # 1R target

        # Look forward within horizon
        label = 0  # default: DANGER_ZONE
        end_idx = min(i + eval_horizon, n - 1)

        for j in range(i + 1, end_idx + 1):
            if side == "LONG":
                # Check stop hit (using low)
                if lows[j] <= stop_level:
                    label = 0
                    break
                # Check target hit (using high)
                if highs[j] >= target_level:
                    label = 1
                    break
            else:  # SHORT
                # Check stop hit (using high)
                if highs[j] >= stop_level:
                    label = 0
                    break
                # Check target hit (using low)
                if lows[j] <= target_level:
                    label = 1
                    break

        entries.append({
            "idx": df.index[i],
            "side": side,
            "entry_price": entry_price,
            "label": label,
        })

    if not entries:
        return pd.DataFrame()

    # Build result DataFrame
    entry_df = pd.DataFrame(entries).set_index("idx")
    entry_df.index.name = df.index.name

    # Merge features from original df
    result = df.loc[entry_df.index].copy()
    result["side"] = entry_df["side"]
    result["entry_price"] = entry_df["entry_price"]
    result["label"] = entry_df["label"]

    return result
