"""Feature engineering for Regime Classifier v1 (Traffic Light).

Minimal feature set designed to avoid overfitting.
Only 6 features — all capture market *conditions*, not direction.
Feature names must match exactly between Python training and Go inference.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import ta


FEATURE_VERSION = "regime_v1"

FEATURE_NAMES = [
    "volatility_20",     # rolling std of log returns (20 bars)
    "volume_ratio_20",   # volume / SMA(volume, 20)
    "rsi_14",            # RSI(14)
    "hour_sin",          # cyclical hour-of-day encoding (sin)
    "hour_cos",          # cyclical hour-of-day encoding (cos)
    "funding_24h_avg",   # funding rate 24h rolling average
]


def build_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build the regime classifier feature set.

    Input must have a DatetimeIndex and columns:
        open, high, low, close, volume
    Optionally: funding_rate (forward-filled from funding table).

    Returns df with added feature columns.
    """
    df = df.copy()

    # --- volatility_20: rolling std of log returns ---
    log_ret = np.log(df["close"] / df["close"].shift(1))
    df["volatility_20"] = log_ret.rolling(window=20).std()

    # --- volume_ratio_20: volume / SMA(volume, 20) ---
    vol_sma = df["volume"].rolling(window=20).mean()
    df["volume_ratio_20"] = df["volume"] / vol_sma

    # --- rsi_14 ---
    df["rsi_14"] = ta.momentum.rsi(df["close"], window=14)

    # --- hour_sin, hour_cos: cyclical time encoding ---
    hour = df.index.hour + df.index.minute / 60.0
    df["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24)

    # --- funding_24h_avg ---
    if "funding_rate" in df.columns:
        df["funding_24h_avg"] = (
            df["funding_rate"].rolling(window=6, min_periods=1).mean()
        )
    else:
        df["funding_24h_avg"] = 0.0

    return df
