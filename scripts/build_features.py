#!/usr/bin/env python3
"""Build features from OHLCV data for XGBoost training."""

from pathlib import Path

import numpy as np
import pandas as pd
import ta


def add_features(df: pd.DataFrame, timeframe: str = "5m") -> pd.DataFrame:
    """Add technical analysis features to OHLCV dataframe.

    Args:
        df: OHLCV dataframe with timestamp index
        timeframe: Base timeframe (e.g., "5m", "1m")
    """
    df = df.copy()

    # Determine multipliers for multi-timeframe features
    # For 5m base: 15m = 3x, 1h = 12x
    # For 1m base: 5m = 5x, 15m = 15x, 1h = 60x
    if timeframe == "5m":
        mult_15m = 3
        mult_1h = 12
    elif timeframe == "1m":
        mult_5m = 5
        mult_15m = 15
        mult_1h = 60
    else:
        mult_15m = 3
        mult_1h = 12

    # === Price Features (single timeframe) ===
    df["log_ret_1"] = np.log(df["close"] / df["close"].shift(1))
    df["log_ret_5"] = np.log(df["close"] / df["close"].shift(5))

    # === EMAs (base timeframe) ===
    df["ema_5"] = ta.trend.ema_indicator(df["close"], window=5)
    df["ema_9"] = ta.trend.ema_indicator(df["close"], window=9)
    df["ema_21"] = ta.trend.ema_indicator(df["close"], window=21)
    df["ema_50"] = ta.trend.ema_indicator(df["close"], window=50)

    # === Multi-Timeframe EMAs (KEY IMPROVEMENT) ===
    if timeframe == "5m":
        # 15-minute context (3 x 5m)
        df["ema_21_15m"] = (
            df["close"].rolling(window=21 * mult_15m, min_periods=21).mean()
        )
        df["ema_50_15m"] = (
            df["close"].rolling(window=50 * mult_15m, min_periods=50).mean()
        )

        # 1-hour context (12 x 5m)
        df["ema_21_1h"] = (
            df["close"].rolling(window=21 * mult_1h, min_periods=21).mean()
        )
        df["ema_50_1h"] = (
            df["close"].rolling(window=50 * mult_1h, min_periods=50).mean()
        )
    elif timeframe == "1m":
        # 5-minute context
        df["ema_21_5m"] = (
            df["close"].rolling(window=21 * mult_5m, min_periods=21).mean()
        )

        # 15-minute context
        df["ema_21_15m"] = (
            df["close"].rolling(window=21 * mult_15m, min_periods=21).mean()
        )

        # 1-hour context
        df["ema_21_1h"] = (
            df["close"].rolling(window=21 * mult_1h, min_periods=21).mean()
        )

    # === Trend Alignment (POWERFUL FEATURE) ===
    if timeframe == "5m":
        df["trend_aligned"] = (
            (df["close"] > df["ema_21"])  # 5m uptrend
            & (df["close"] > df["ema_21_15m"])  # 15m uptrend
            & (df["close"] > df["ema_21_1h"])  # 1h uptrend
        ).astype(int)
    elif timeframe == "1m":
        df["trend_aligned"] = (
            (df["close"] > df["ema_21"])  # 1m uptrend
            & (df["close"] > df["ema_21_5m"])  # 5m uptrend
            & (df["close"] > df["ema_21_15m"])  # 15m uptrend
        ).astype(int)

    # === RSI ===
    df["rsi_7"] = ta.momentum.rsi(df["close"], window=7)
    df["rsi_14"] = ta.momentum.rsi(df["close"], window=14)

    # === Bollinger Bands ===
    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_middle"] = bb.bollinger_mavg()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]

    # === MACD ===
    macd = ta.trend.MACD(df["close"], window_slow=26, window_fast=12, window_sign=9)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_histogram"] = macd.macd_diff()

    # === Volume Features (IMPROVED) ===
    df["volume_ratio"] = df["volume"] / df["volume"].rolling(window=20).mean()

    # Volume surge indicator (catches breakouts)
    df["vol_surge"] = (
        df["volume"] > df["volume"].rolling(window=100).mean() * 1.5
    ).astype(int)

    # Price-volume divergence
    df["pv_divergence"] = (
        (df["close"].diff() * df["volume"].diff()).rolling(window=10).sum()
    )

    # === Time Features ===
    df["hour"] = df.index.hour
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)

    # Session indicators (crypto has patterns based on geography)
    df["is_us_session"] = ((df.index.hour >= 13) & (df.index.hour < 21)).astype(
        int
    )  # 8am-4pm EST
    df["is_asia_session"] = ((df.index.hour >= 0) & (df.index.hour < 8)).astype(
        int
    )  # Asia hours
    df["is_weekend"] = (df.index.dayofweek >= 5).astype(int)

    # === Sentiment (placeholder - remove or implement properly) ===
    # NOTE: Currently zeros, consider removing these to reduce noise
    df["sentiment_1h"] = 0.0
    df["sentiment_24h"] = 0.0
    df["mentions_zscore"] = 0.0
    df["sentiment_velocity"] = 0.0

    return df


def add_labels(df: pd.DataFrame, threshold: float = 0.001) -> pd.DataFrame:
    """Add target labels: UP, DOWN, NEUTRAL based on next bar return."""
    df = df.copy()

    df["future_ret"] = df["close"].shift(-1) / df["close"] - 1

    df["label"] = 1
    df.loc[df["future_ret"] > threshold, "label"] = 2
    df.loc[df["future_ret"] < -threshold, "label"] = 0

    return df


FEATURE_COLUMNS = [
    "close",
    "log_ret_1",
    "log_ret_5",
    "ema_5",
    "ema_9",
    "ema_21",
    "ema_50",
    "ema_21_15m",
    "ema_50_15m",
    "ema_21_1h",
    "ema_50_1h",
    "trend_aligned",
    "rsi_7",
    "rsi_14",
    "bb_upper",
    "bb_middle",
    "bb_lower",
    "bb_width",
    "macd",
    "macd_signal",
    "macd_histogram",
    "volume_ratio",
    "vol_surge",
    "pv_divergence",
    "hour_sin",
    "hour_cos",
    "is_us_session",
    "is_asia_session",
    "is_weekend",
    # Sentiment features (currently zeros - consider removing)
    "sentiment_1h",
    "sentiment_24h",
    "mentions_zscore",
    "sentiment_velocity",
]


def prepare_dataset(
    data_dir: Path,
    symbols: list[str],
    threshold: float = 0.002,  # 0.2% for 5m candles
    timeframe: str = "5m",
) -> tuple[pd.DataFrame, pd.Series]:
    """Load and prepare dataset from parquet files."""

    all_dfs = []

    for symbol in symbols:
        pattern = f"{symbol.replace('/', '_')}_*.parquet"
        files = list(data_dir.glob(pattern))

        if not files:
            print(f"No data found for {symbol}")
            continue

        for f in files:
            print(f"Loading {f}")
            df = pd.read_parquet(f)
            df = add_features(df, timeframe=timeframe)
            df = add_labels(df, threshold)
            df["symbol"] = symbol
            all_dfs.append(df)

    if not all_dfs:
        raise ValueError("No data loaded")

    combined = pd.concat(all_dfs, axis=0)
    combined = combined.sort_index()

    combined = combined.dropna(subset=FEATURE_COLUMNS + ["label"])
    combined = combined[:-1]

    X = combined[FEATURE_COLUMNS]
    y = combined["label"]

    print(f"\nDataset shape: {X.shape}")
    print(f"Label distribution:\n{y.value_counts().sort_index()}")

    return X, y


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build features from OHLCV data")
    parser.add_argument("--data-dir", type=str, default="data", help="Data directory")
    parser.add_argument(
        "--symbols",
        type=str,
        default="BTC/USDT,ETH/USDT",
        help="Comma-separated symbols",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.002,
        help="Return threshold for UP/DOWN labels (0.002 = 0.2% for 5m)",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="5m",
        help="Base timeframe (5m recommended, 1m for legacy)",
    )
    parser.add_argument("--output", type=str, default="data/features.parquet")

    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")]
    X, y = prepare_dataset(Path(args.data_dir), symbols, args.threshold, args.timeframe)

    output = pd.concat([X, y], axis=1)
    output.to_parquet(args.output)
    print(f"\nSaved features to {args.output}")
