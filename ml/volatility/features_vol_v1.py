"""Feature engineering for Volatility Predictor v1 (Dynamic Stop-Loss).

Minimal feature set for predicting next-candle high-low range.
Only 6 features — all capture *realized volatility patterns*.
Feature names must match exactly between Python training and Go inference.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import ta


FEATURE_VERSION = "vol_v1"

FEATURE_NAMES = [
    "range_1",           # (high - low) / close of current candle
    "range_sma_6",       # SMA of range_1 over 6 bars
    "atrp_14",           # ATR(14) / close (ATR as percentage of price)
    "volume_ratio_20",   # volume / SMA(volume, 20)
    "hour_sin",          # cyclical hour-of-day encoding (sin)
    "hour_cos",          # cyclical hour-of-day encoding (cos)
]


def build_vol_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build the volatility predictor feature set.

    Input must have a DatetimeIndex and columns:
        open, high, low, close, volume

    Returns df with added feature columns.
    """
    df = df.copy()

    # --- range_1: current candle range as % of close ---
    df["range_1"] = (df["high"] - df["low"]) / df["close"]

    # --- range_sma_6: 6-bar SMA of range ---
    df["range_sma_6"] = df["range_1"].rolling(window=6).mean()

    # --- atrp_14: ATR(14) as percentage of close ---
    atr = ta.volatility.average_true_range(
        df["high"], df["low"], df["close"], window=14
    )
    df["atrp_14"] = atr / df["close"]

    # --- volume_ratio_20: volume / SMA(volume, 20) ---
    vol_sma = df["volume"].rolling(window=20).mean()
    df["volume_ratio_20"] = df["volume"] / vol_sma

    # --- hour_sin, hour_cos: cyclical time encoding ---
    hour = df.index.hour + df.index.minute / 60.0
    df["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24)

    return df
