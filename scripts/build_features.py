#!/usr/bin/env python3
"""Build features from OHLCV data for XGBoost training."""

import pandas as pd
import numpy as np
from pathlib import Path
import ta


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add technical analysis features to OHLCV dataframe."""
    df = df.copy()
    
    df["log_ret_1m"] = np.log(df["close"] / df["close"].shift(1))
    df["log_ret_5m"] = np.log(df["close"] / df["close"].shift(5))
    
    df["ema_5"] = ta.trend.ema_indicator(df["close"], window=5)
    df["ema_9"] = ta.trend.ema_indicator(df["close"], window=9)
    df["ema_21"] = ta.trend.ema_indicator(df["close"], window=21)
    df["ema_50"] = ta.trend.ema_indicator(df["close"], window=50)
    
    df["rsi_7"] = ta.momentum.rsi(df["close"], window=7)
    df["rsi_14"] = ta.momentum.rsi(df["close"], window=14)
    
    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_middle"] = bb.bollinger_mavg()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]
    
    macd = ta.trend.MACD(df["close"], window_slow=26, window_fast=12, window_sign=9)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_histogram"] = macd.macd_diff()
    
    df["volume_ratio"] = df["volume"] / df["volume"].rolling(window=20).mean()
    
    df["hour"] = df.index.hour
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    
    df["sentiment_1h"] = 0.0
    df["sentiment_24h"] = 0.0
    df["mentions_zscore"] = 0.0
    df["sentiment_velocity"] = 0.0
    
    return df


def add_labels(df: pd.DataFrame, threshold: float = 0.0003) -> pd.DataFrame:
    """Add target labels: UP, DOWN, NEUTRAL based on next bar return."""
    df = df.copy()
    
    df["future_ret"] = df["close"].shift(-1) / df["close"] - 1
    
    df["label"] = 1
    df.loc[df["future_ret"] > threshold, "label"] = 2
    df.loc[df["future_ret"] < -threshold, "label"] = 0
    
    return df


FEATURE_COLUMNS = [
    "close",
    "log_ret_1m",
    "log_ret_5m",
    "ema_5",
    "ema_9",
    "ema_21",
    "ema_50",
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
    "sentiment_1h",
    "sentiment_24h",
    "mentions_zscore",
    "sentiment_velocity",
    "hour_sin",
    "hour_cos",
]


def prepare_dataset(
    data_dir: Path,
    symbols: list[str],
    threshold: float = 0.0003,
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
            df = add_features(df)
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
        default=0.0003,
        help="Return threshold for UP/DOWN labels",
    )
    parser.add_argument("--output", type=str, default="data/features.parquet")
    
    args = parser.parse_args()
    
    symbols = [s.strip() for s in args.symbols.split(",")]
    X, y = prepare_dataset(Path(args.data_dir), symbols, args.threshold)
    
    output = pd.concat([X, y], axis=1)
    output.to_parquet(args.output)
    print(f"\nSaved features to {args.output}")
