#!/usr/bin/env python3
"""Build v2 features for regime-aware trend following with meta-labeling.

Feature set (~25 features):
  - Price: log returns (1, 2, 6, 12 bars)
  - Trend: EMA 21/50
  - Momentum: RSI 14, MACD histogram
  - Volatility: BB width, BB %B, ATR 14, ATR ratio, vol_regime_ratio, volatility_percentile
  - Volume: volume_ratio, vol_surge
  - Funding: funding_rate, funding_ma8, funding_extreme
  - Cross-asset: btc_dominance_proxy, eth_btc_ratio, market_breadth
  - Daily context: daily_trend, daily_rsi
  - Time: hour_sin, hour_cos, day_sin, day_cos
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import ta

# ---------- Feature Columns ----------

FEATURE_COLUMNS_V2: list[str] = [
    # Price returns
    "log_ret_1",
    "log_ret_2",
    "log_ret_6",
    "log_ret_12",
    # Trend
    "ema_21",
    "ema_50",
    # Momentum
    "rsi_14",
    "macd_histogram",
    # Bollinger Bands
    "bb_width",
    "bb_pct",
    # Volume
    "volume_ratio",
    "vol_surge",
    # Volatility
    "atr_14",
    "atr_ratio",
    "vol_regime_ratio",
    "volatility_percentile",
    # Funding rate
    "funding_rate",
    "funding_ma8",
    "funding_extreme",
    # Cross-asset
    "btc_dominance_proxy",
    "eth_btc_ratio",
    "market_breadth",
    # Daily context
    "daily_trend",
    "daily_rsi",
    # Time
    "hour_sin",
    "hour_cos",
    "day_sin",
    "day_cos",
]


# ---------- Feature Engineering ----------


def add_features_v2(
    df_4h: pd.DataFrame,
    funding_df: pd.DataFrame | None = None,
    daily_df: pd.DataFrame | None = None,
    cross_asset_dfs: dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Add v2 features to a 4h OHLCV dataframe.

    Args:
        df_4h: 4h OHLCV dataframe (timestamp index, OHLCV columns).
        funding_df: Funding rate dataframe (timestamp index, fundingRate column).
                    If None, funding features are filled with 0.
        daily_df: Daily OHLCV dataframe (timestamp index, OHLCV columns).
                  If None, daily context features are filled with 0.
        cross_asset_dfs: Dict mapping symbol -> 4h OHLCV dataframe for all symbols.
                         Used for cross-asset features. If None, filled with NaN.

    Returns:
        DataFrame with all v2 features added.
    """
    df = df_4h.copy()

    # === Price Returns ===
    df["log_ret_1"] = np.log(df["close"] / df["close"].shift(1))
    df["log_ret_2"] = np.log(df["close"] / df["close"].shift(2))
    df["log_ret_6"] = np.log(df["close"] / df["close"].shift(6))  # 24h
    df["log_ret_12"] = np.log(df["close"] / df["close"].shift(12))  # 48h

    # === Trend: EMAs ===
    df["ema_21"] = ta.trend.ema_indicator(df["close"], window=21)
    df["ema_50"] = ta.trend.ema_indicator(df["close"], window=50)

    # === Momentum: RSI ===
    df["rsi_14"] = ta.momentum.rsi(df["close"], window=14)

    # === Bollinger Bands ===
    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    bb_upper = bb.bollinger_hband()
    bb_lower = bb.bollinger_lband()
    bb_middle = bb.bollinger_mavg()
    df["bb_width"] = (bb_upper - bb_lower) / bb_middle
    df["bb_pct"] = (df["close"] - bb_lower) / (bb_upper - bb_lower)

    # === MACD ===
    macd = ta.trend.MACD(df["close"], window_slow=26, window_fast=12, window_sign=9)
    df["macd_histogram"] = macd.macd_diff()

    # === Volume ===
    df["volume_ratio"] = df["volume"] / df["volume"].rolling(window=20).mean()
    df["vol_surge"] = (
        df["volume"] > df["volume"].rolling(window=50).mean() * 1.5
    ).astype(int)

    # === Volatility ===
    df["atr_14"] = ta.volatility.average_true_range(
        df["high"], df["low"], df["close"], window=14
    )
    df["atr_ratio"] = df["atr_14"] / df["close"]  # normalized ATR

    atr_50 = ta.volatility.average_true_range(
        df["high"], df["low"], df["close"], window=50
    )
    df["vol_regime_ratio"] = df["atr_14"] / atr_50
    df["vol_regime_ratio"] = df["vol_regime_ratio"].replace([np.inf, -np.inf], np.nan)

    df["volatility_percentile"] = (
        df["atr_14"]
        .rolling(window=100)
        .apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)
    )

    # === Time Features ===
    df["hour_sin"] = np.sin(2 * np.pi * df.index.hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df.index.hour / 24)
    df["day_sin"] = np.sin(2 * np.pi * df.index.dayofweek / 7)
    df["day_cos"] = np.cos(2 * np.pi * df.index.dayofweek / 7)

    # === Funding Rate Features ===
    if funding_df is not None and not funding_df.empty:
        _add_funding_features(df, funding_df)
    else:
        df["funding_rate"] = 0.0
        df["funding_ma8"] = 0.0
        df["funding_extreme"] = 0

    # === Daily Context Features ===
    if daily_df is not None and not daily_df.empty:
        _add_daily_features(df, daily_df)
    else:
        df["daily_trend"] = 0
        df["daily_rsi"] = 50.0

    # === Cross-Asset Features ===
    if cross_asset_dfs is not None:
        _add_cross_asset_features(df, cross_asset_dfs)
    else:
        df["btc_dominance_proxy"] = np.nan
        df["eth_btc_ratio"] = np.nan
        df["market_breadth"] = np.nan

    return df


def _add_funding_features(df: pd.DataFrame, funding_df: pd.DataFrame) -> None:
    """Merge funding rate features into df (in-place).

    Merges by nearest timestamp using merge_asof.
    """
    funding = funding_df[["fundingRate"]].copy()
    funding = funding.sort_index()
    funding = funding[~funding.index.duplicated(keep="last")]

    # merge_asof requires both sorted and non-duplicate index
    df_sorted = df[["close"]].copy().sort_index()
    merged = pd.merge_asof(
        df_sorted,
        funding,
        left_index=True,
        right_index=True,
        direction="backward",
    )

    df["funding_rate"] = merged["fundingRate"].fillna(0.0).values
    df["funding_ma8"] = df["funding_rate"].rolling(window=8, min_periods=1).mean()

    # Extreme: |funding_rate| > 90th percentile of rolling 100 bars
    rolling_pct90 = (
        df["funding_rate"].abs().rolling(window=100, min_periods=20).quantile(0.9)
    )
    df["funding_extreme"] = (df["funding_rate"].abs() > rolling_pct90).astype(int)


def _add_daily_features(df: pd.DataFrame, daily_df: pd.DataFrame) -> None:
    """Add daily context features to 4h dataframe (in-place).

    Computes daily_trend (close > SMA20) and daily_rsi on daily bars,
    then forward-fills into the 4h dataframe.
    """
    daily = daily_df.copy().sort_index()
    daily = daily[~daily.index.duplicated(keep="last")]

    # Compute daily indicators
    daily["daily_sma20"] = daily["close"].rolling(window=20).mean()
    daily["daily_trend"] = (daily["close"] > daily["daily_sma20"]).astype(int)
    daily["daily_rsi"] = ta.momentum.rsi(daily["close"], window=14)

    daily_feats = daily[["daily_trend", "daily_rsi"]].copy()

    # merge_asof: for each 4h bar, get the most recent daily value
    df_sorted = df[["close"]].copy().sort_index()
    merged = pd.merge_asof(
        df_sorted,
        daily_feats,
        left_index=True,
        right_index=True,
        direction="backward",
    )

    df["daily_trend"] = merged["daily_trend"].fillna(0).astype(int).values
    df["daily_rsi"] = merged["daily_rsi"].fillna(50.0).values


def _add_cross_asset_features(
    df: pd.DataFrame,
    cross_asset_dfs: dict[str, pd.DataFrame],
) -> None:
    """Add cross-asset features to df (in-place).

    Requires close prices from BTC, ETH, SOL, BNB.
    """
    # Build a combined close-price dataframe aligned on timestamps
    closes: dict[str, pd.Series] = {}
    for sym, sym_df in cross_asset_dfs.items():
        key = sym.replace("/", "_").replace("USDT", "").rstrip("_")
        closes[key] = sym_df["close"].rename(f"close_{key}")

    if not closes:
        df["btc_dominance_proxy"] = np.nan
        df["eth_btc_ratio"] = np.nan
        df["market_breadth"] = np.nan
        return

    close_df = pd.concat(closes.values(), axis=1).sort_index()
    close_df = close_df.reindex(df.index, method="ffill")

    # BTC dominance proxy
    btc_col = [c for c in close_df.columns if "BTC" in c]
    if btc_col:
        total = close_df.sum(axis=1)
        df["btc_dominance_proxy"] = (close_df[btc_col[0]] / total).replace(
            [np.inf, -np.inf], np.nan
        )
    else:
        df["btc_dominance_proxy"] = np.nan

    # ETH/BTC ratio
    eth_col = [c for c in close_df.columns if "ETH" in c]
    if btc_col and eth_col:
        df["eth_btc_ratio"] = (close_df[eth_col[0]] / close_df[btc_col[0]]).replace(
            [np.inf, -np.inf], np.nan
        )
    else:
        df["eth_btc_ratio"] = np.nan

    # Market breadth: fraction of symbols with positive 4h return
    ret_df = close_df.pct_change(1)
    df["market_breadth"] = (ret_df > 0).sum(axis=1) / ret_df.shape[1]


# ---------- Dataset Preparation ----------


def prepare_dataset_v2(
    data_dir: Path,
    symbols: list[str],
    funding_dir: Path | None = None,
    daily_dir: Path | None = None,
) -> pd.DataFrame:
    """Load 4h + funding + daily data and build v2 features for all symbols.

    Args:
        data_dir: Directory containing 4h OHLCV parquet files.
        symbols: List of symbols (e.g., ["BTC/USDT", "ETH/USDT"]).
        funding_dir: Directory containing funding rate parquet files.
        daily_dir: Directory containing daily OHLCV parquet files.

    Returns:
        Combined DataFrame with all features and a 'symbol' column.
    """
    # --- Load all 4h OHLCV ---
    raw_4h: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        pattern = f"{symbol.replace('/', '_')}_*.parquet"
        files = list(data_dir.glob(pattern))
        if not files:
            print(f"No 4h data found for {symbol} in {data_dir}")
            continue
        dfs = []
        for f in files:
            print(f"Loading 4h: {f}")
            dfs.append(pd.read_parquet(f))
        combined = pd.concat(dfs).sort_index()
        combined = combined[~combined.index.duplicated(keep="last")]
        raw_4h[symbol] = combined

    if not raw_4h:
        raise ValueError(f"No 4h data loaded from {data_dir}")

    # --- Load funding data ---
    funding_data: dict[str, pd.DataFrame] = {}
    if funding_dir and funding_dir.exists():
        for symbol in symbols:
            pattern = f"{symbol.replace('/', '_')}_funding_*.parquet"
            files = list(funding_dir.glob(pattern))
            if files:
                print(f"Loading funding: {files[0]}")
                funding_data[symbol] = pd.read_parquet(files[0])

    # --- Load daily data ---
    daily_data: dict[str, pd.DataFrame] = {}
    if daily_dir and daily_dir.exists():
        for symbol in symbols:
            pattern = f"{symbol.replace('/', '_')}_1d_*.parquet"
            files = list(daily_dir.glob(pattern))
            if files:
                print(f"Loading daily: {files[0]}")
                daily_data[symbol] = pd.read_parquet(files[0])

    # --- Build features per symbol ---
    all_featured: list[pd.DataFrame] = []

    for symbol, df_4h in raw_4h.items():
        print(f"\nBuilding features for {symbol}...")
        funding_df = funding_data.get(symbol)
        daily_df = daily_data.get(symbol)

        featured = add_features_v2(
            df_4h,
            funding_df=funding_df,
            daily_df=daily_df,
            cross_asset_dfs=raw_4h,
        )
        featured["symbol"] = symbol
        all_featured.append(featured)

    combined = pd.concat(all_featured, axis=0).sort_index()

    # Report stats
    total = len(combined)
    valid = combined[FEATURE_COLUMNS_V2].notna().all(axis=1).sum()
    print(f"\nTotal rows: {total}")
    print(f"Valid rows (no NaN in features): {valid}")
    print(f"NaN rows dropped: {total - valid}")

    # Report per-feature NaN counts
    nan_counts = combined[FEATURE_COLUMNS_V2].isna().sum()
    if nan_counts.any():
        print("\nNaN counts per feature:")
        for feat, cnt in nan_counts[nan_counts > 0].items():
            print(f"  {feat}: {cnt}")

    return combined


# ---------- CLI ----------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build v2 features for regime-aware trend following"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data_4h",
        help="Directory with 4h OHLCV parquet files",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT",
        help="Comma-separated symbols",
    )
    parser.add_argument(
        "--funding-dir",
        type=str,
        default=None,
        help="Directory with funding rate parquet files (default: <data-dir>/funding)",
    )
    parser.add_argument(
        "--daily-dir",
        type=str,
        default="data_daily",
        help="Directory with daily OHLCV parquet files",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data_4h/features_v2.parquet",
        help="Output parquet path",
    )

    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")]
    data_dir = Path(args.data_dir)
    funding_dir = Path(args.funding_dir) if args.funding_dir else data_dir / "funding"
    daily_dir = Path(args.daily_dir)

    combined = prepare_dataset_v2(
        data_dir=data_dir,
        symbols=symbols,
        funding_dir=funding_dir,
        daily_dir=daily_dir,
    )

    # Save full featured dataset
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(output_path)
    print(f"\nSaved features to {output_path}")

    # Print feature summary
    print(f"\nFeature columns ({len(FEATURE_COLUMNS_V2)}):")
    for col in FEATURE_COLUMNS_V2:
        print(f"  {col}")


if __name__ == "__main__":
    main()
