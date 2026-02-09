"""Feature engineering for Regime Classifier v2 (Traffic Light).

Extends v1 with 2 realized-volatility features from the vol predictor:
    - atrp_14: ATR(14) / close (ATR as percentage of price)
    - range_sma_6: SMA of (high-low)/close over 6 bars

Total: 8 features (vs 6 in v1). These 2 extra features are the vol predictor's
strongest signals, and the hypothesis is they help the regime classifier
distinguish between breakouts in calm vs volatile conditions.

Feature names must match exactly between Python training and Go inference.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import ta


FEATURE_VERSION = "regime_v2"

# Original v1 features (6)
FEATURE_NAMES_V1 = [
    "volatility_20",     # rolling std of log returns (20 bars)
    "volume_ratio_20",   # volume / SMA(volume, 20)
    "rsi_14",            # RSI(14)
    "hour_sin",          # cyclical hour-of-day encoding (sin)
    "hour_cos",          # cyclical hour-of-day encoding (cos)
    "funding_24h_avg",   # funding rate 24h rolling average
]

# New v2 features (2 from vol predictor)
FEATURE_NAMES_NEW = [
    "atrp_14",           # ATR(14) / close (ATR as percentage of price)
    "range_sma_6",       # SMA of (high - low) / close over 6 bars
]

# Combined v2 feature set (8 total)
FEATURE_NAMES = FEATURE_NAMES_V1 + FEATURE_NAMES_NEW


def build_regime_features_v2(df: pd.DataFrame) -> pd.DataFrame:
    """Build the regime classifier v2 feature set (8 features).

    Input must have a DatetimeIndex and columns:
        open, high, low, close, volume
    Optionally: funding_rate (forward-filled from funding table).

    Returns df with added feature columns.
    """
    df = df.copy()

    # === Original v1 features ===

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

    # === New v2 features (from vol predictor) ===

    # --- atrp_14: ATR(14) / close ---
    atr = ta.volatility.average_true_range(
        df["high"], df["low"], df["close"], window=14
    )
    df["atrp_14"] = atr / df["close"]

    # --- range_sma_6: SMA of (high - low) / close over 6 bars ---
    range_1 = (df["high"] - df["low"]) / df["close"]
    df["range_sma_6"] = range_1.rolling(window=6).mean()

    return df
