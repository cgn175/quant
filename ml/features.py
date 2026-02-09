"""Feature engineering for trend ML filter (v1).

All features use only data available at time t — no lookahead.
Feature names are snake_case and must match exactly between training
and Go inference.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import ta


FEATURE_VERSION = "trend_ml_filter_v1"

FEATURE_NAMES = [
    "returns_1bar",
    "returns_4bar",
    "returns_20bar",
    "volatility_20",
    "rsi_14",
    "bb_width_20",
    "adx_14",
    "ema_9_distance",
    "ema_50_distance",
    "volume_ratio_20",
    "funding_8h_avg",
    "funding_24h_avg",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
    "atr_14",
    "atr_ratio",
    "donchian_breakout",
]


def add_price_action(df: pd.DataFrame) -> pd.DataFrame:
    """Log returns and rolling volatility."""
    df["returns_1bar"] = np.log(df["close"] / df["close"].shift(1))
    df["returns_4bar"] = np.log(df["close"] / df["close"].shift(4))
    df["returns_20bar"] = np.log(df["close"] / df["close"].shift(20))
    df["volatility_20"] = df["returns_1bar"].rolling(window=20).std()
    return df


def add_technical(df: pd.DataFrame) -> pd.DataFrame:
    """RSI, Bollinger Band width, ADX, EMA distances."""
    df["rsi_14"] = ta.momentum.rsi(df["close"], window=14)

    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    bb_upper = bb.bollinger_hband()
    bb_lower = bb.bollinger_lband()
    bb_mid = bb.bollinger_mavg()
    df["bb_width_20"] = (bb_upper - bb_lower) / bb_mid

    df["adx_14"] = ta.trend.adx(df["high"], df["low"], df["close"], window=14)

    ema_9 = ta.trend.ema_indicator(df["close"], window=9)
    ema_50 = ta.trend.ema_indicator(df["close"], window=50)
    df["ema_9_distance"] = df["close"] / ema_9 - 1
    df["ema_50_distance"] = df["close"] / ema_50 - 1
    return df


def add_volume(df: pd.DataFrame) -> pd.DataFrame:
    """Volume ratio vs 20-bar SMA."""
    vol_sma = df["volume"].rolling(window=20).mean()
    df["volume_ratio_20"] = df["volume"] / vol_sma
    return df


def add_funding(df: pd.DataFrame) -> pd.DataFrame:
    """Funding rate rolling averages.

    Expects a `funding_rate` column already merged and forward-filled
    onto the candle DataFrame.
    """
    if "funding_rate" not in df.columns:
        df["funding_8h_avg"] = 0.0
        df["funding_24h_avg"] = 0.0
        return df

    df["funding_8h_avg"] = df["funding_rate"].rolling(window=2, min_periods=1).mean()
    df["funding_24h_avg"] = df["funding_rate"].rolling(window=6, min_periods=1).mean()
    return df


def add_temporal(df: pd.DataFrame) -> pd.DataFrame:
    """Cyclical time-of-day and day-of-week encoding."""
    hour = df.index.hour + df.index.minute / 60.0
    df["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24)

    dow = df.index.dayofweek
    df["dow_sin"] = np.sin(2 * np.pi * dow / 7)
    df["dow_cos"] = np.cos(2 * np.pi * dow / 7)
    return df


def add_regime(df: pd.DataFrame) -> pd.DataFrame:
    """ATR, ATR ratio, and Donchian breakout flag."""
    df["atr_14"] = ta.volatility.average_true_range(
        df["high"], df["low"], df["close"], window=14
    )
    atr_50 = ta.volatility.average_true_range(
        df["high"], df["low"], df["close"], window=50
    )
    df["atr_ratio"] = df["atr_14"] / atr_50

    upper = df["high"].shift(1).rolling(window=20).max()
    lower = df["low"].shift(1).rolling(window=20).min()

    dc = pd.Series(0, index=df.index, dtype=int)
    dc[df["close"] > upper] = 1
    dc[df["close"] < lower] = -1
    df["donchian_breakout"] = dc
    return df


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all feature groups. Returns df with added feature columns.

    The input must have a DatetimeIndex and columns:
        open, high, low, close, volume
    Optionally: funding_rate (forward-filled from funding table).
    """
    df = df.copy()
    df = add_price_action(df)
    df = add_technical(df)
    df = add_volume(df)
    df = add_funding(df)
    df = add_temporal(df)
    df = add_regime(df)
    return df
