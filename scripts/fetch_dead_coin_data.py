#!/usr/bin/env python3
"""
Fetch or synthesize historical data for dead/failed cryptocurrencies.

This script addresses survivorship bias by including coins that:
- Went to zero (LUNA, FTT, CEL, etc.)
- Were delisted from exchanges
- Had catastrophic crashes (99%+ drawdowns)

Data sources:
1. Binance historical data (if available for delisted coins)
2. Synthesized realistic price paths based on known crash events
"""

import argparse
import json
import numpy as np
import pandas as pd
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import ccxt


@dataclass
class DeadCoin:
    """Metadata for a dead/failed cryptocurrency."""
    symbol: str  # e.g., "LUNA/USDT"
    name: str
    peak_price: float  # Approximate peak price before crash
    peak_date: datetime  # When it peaked
    crash_start: datetime  # When crash began
    crash_end: datetime  # When delisted/zeroed
    final_price: float  # Final price (often 0 or near-zero)
    crash_reason: str
    total_return_during_crash: float  # e.g., -0.999 for -99.9%
    available_on_binance: bool = False  # Whether historical data exists


# Dead coin database - historically accurate crash events
DEAD_COINS = [
    DeadCoin(
        symbol="LUNA/USDT",
        name="Terra Luna (Classic)",
        peak_price=119.51,
        peak_date=datetime(2022, 4, 5),
        crash_start=datetime(2022, 5, 9),  # Death spiral begins
        crash_end=datetime(2022, 5, 13),  # Delisted
        final_price=0.0001,
        crash_reason="Death spiral / UST depeg",
        total_return_during_crash=-0.999999,
        available_on_binance=True,  # Historical data exists as LUNC/USDT now
    ),
    DeadCoin(
        symbol="FTT/USDT",
        name="FTX Token",
        peak_price=84.18,
        peak_date=datetime(2021, 9, 9),
        crash_start=datetime(2022, 11, 6),  # CZ tweets about selling FTT
        crash_end=datetime(2022, 11, 14),  # FTX bankruptcy, token worthless
        final_price=0.80,
        crash_reason="FTX exchange collapse",
        total_return_during_crash=-0.99,
        available_on_binance=True,  # Was traded on Binance
    ),
    DeadCoin(
        symbol="CEL/USDT",
        name="Celsius Network",
        peak_price=8.02,
        peak_date=datetime(2021, 6, 4),
        crash_start=datetime(2022, 6, 10),  # Pause withdrawals
        crash_end=datetime(2022, 7, 14),  # Bankruptcy filing
        final_price=0.10,
        crash_reason="Celsius platform collapse",
        total_return_during_crash=-0.987,
        available_on_binance=True,
    ),
    DeadCoin(
        symbol="VGX/USDT",
        name="Voyager Token",
        peak_price=7.50,
        peak_date=datetime(2021, 1, 5),
        crash_start=datetime(2022, 6, 27),  # Suspended trading
        crash_end=datetime(2022, 7, 6),  # Bankruptcy
        final_price=0.02,
        crash_reason="Voyager bankruptcy",
        total_return_during_crash=-0.997,
        available_on_binance=True,
    ),
    DeadCoin(
        symbol="LUNC/USDT",
        name="Terra Classic (post-crash)",
        peak_price=0.0005,  # Post-crash peak
        peak_date=datetime(2022, 5, 13),
        crash_start=datetime(2022, 5, 13),
        crash_end=datetime(2022, 5, 31),
        final_price=0.00001,
        crash_reason="LUNA 2.0 fork, old LUNA becomes LUNC",
        total_return_during_crash=-0.98,
        available_on_binance=True,
    ),
    DeadCoin(
        symbol="ANC/USDT",
        name="Anchor Protocol",
        peak_price=8.36,
        peak_date=datetime(2022, 3, 5),
        crash_start=datetime(2022, 5, 9),  # With LUNA
        crash_end=datetime(2022, 5, 20),
        final_price=0.02,
        crash_reason="Terra ecosystem collapse",
        total_return_during_crash=-0.998,
        available_on_binance=False,  # Need to synthesize
    ),
    DeadCoin(
        symbol="MIR/USDT",
        name="Mirror Protocol",
        peak_price=12.90,
        peak_date=datetime(2021, 4, 10),
        crash_start=datetime(2022, 5, 9),  # With LUNA
        crash_end=datetime(2022, 6, 1),
        final_price=0.03,
        crash_reason="Terra ecosystem collapse",
        total_return_during_crash=-0.998,
        available_on_binance=True,
    ),
    DeadCoin(
        symbol="IRIS/USDT",
        name="IRISnet",
        peak_price=0.39,
        peak_date=datetime(2021, 4, 12),
        crash_start=datetime(2022, 5, 1),
        crash_end=datetime(2023, 1, 1),
        final_price=0.002,
        crash_reason="Gradual decline/delisting",
        total_return_during_crash=-0.995,
        available_on_binance=True,
    ),
    DeadCoin(
        symbol="BEAR/USDT",
        name="3X Short Bitcoin Token",
        peak_price=10000.0,
        peak_date=datetime(2019, 1, 1),
        crash_start=datetime(2020, 3, 1),
        crash_end=datetime(2021, 1, 1),
        final_price=1.0,
        crash_reason="Leveraged token decay",
        total_return_during_crash=-0.9999,
        available_on_binance=False,
    ),
    DeadCoin(
        symbol="BULL/USDT",
        name="3X Long Bitcoin Token",
        peak_price=100000.0,
        peak_date=datetime(2021, 4, 1),
        crash_start=datetime(2021, 5, 1),
        crash_end=datetime(2021, 12, 1),
        final_price=100.0,
        crash_reason="Leveraged token decay (bear market)",
        total_return_during_crash=-0.999,
        available_on_binance=False,
    ),
]


def fetch_binance_data(
    symbol: str,
    timeframe: str = "4h",
    start_date: datetime = None,
    end_date: datetime = None,
) -> Optional[pd.DataFrame]:
    """Try to fetch historical data from Binance for a symbol."""
    try:
        exchange = ccxt.binance({"enableRateLimit": True})
        
        # Check if symbol exists or has historical data
        markets = exchange.load_markets()
        if symbol not in markets:
            print(f"  {symbol} not currently on Binance, checking historical...")
            # Try alternative symbols (e.g., LUNA -> LUNC)
            alt_symbols = {
                "LUNA/USDT": "LUNC/USDT",
            }
            if symbol in alt_symbols:
                symbol = alt_symbols[symbol]
                print(f"  Trying alternative symbol: {symbol}")
        
        since = exchange.parse8601(start_date.isoformat()) if start_date else None
        
        all_ohlcv = []
        limit = 1000
        
        print(f"  Fetching {symbol} {timeframe} data from Binance...")
        
        while True:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
                if not ohlcv:
                    break
                
                all_ohlcv.extend(ohlcv)
                since = ohlcv[-1][0] + 1
                
                if len(ohlcv) < limit:
                    break
                    
            except ccxt.BadSymbol:
                print(f"  Symbol {symbol} not available on Binance")
                return None
            except Exception as e:
                print(f"  Error fetching: {e}")
                break
        
        if not all_ohlcv:
            return None
        
        df = pd.DataFrame(
            all_ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.set_index("timestamp")
        df = df[~df.index.duplicated(keep="last")]
        df = df.sort_index()
        
        print(f"  Fetched {len(df)} candles from {df.index[0]} to {df.index[-1]}")
        return df
        
    except Exception as e:
        print(f"  Failed to fetch {symbol}: {e}")
        return None


def synthesize_crash_data(
    coin: DeadCoin,
    timeframe: str = "4h",
    start_buffer_days: int = 365,
    end_buffer_days: int = 30,
) -> pd.DataFrame:
    """
    Synthesize realistic price path for a dead coin.
    
    Creates price action that includes:
    1. Pre-crash period with normal volatility
    2. The actual crash event with accelerated decay
    3. Post-crash zombie period until delisting
    """
    print(f"  Synthesizing data for {coin.symbol}...")
    
    # Generate time index
    start_date = coin.peak_date - timedelta(days=start_buffer_days)
    end_date = coin.crash_end + timedelta(days=end_buffer_days)
    
    if timeframe == "4h":
        freq = "4h"
        periods_per_day = 6
    elif timeframe == "1h":
        freq = "1h"
        periods_per_day = 24
    else:
        freq = "4h"
        periods_per_day = 6
    
    timestamps = pd.date_range(start=start_date, end=end_date, freq=freq)
    n_periods = len(timestamps)
    
    # Initialize price array
    prices = np.zeros(n_periods)
    volumes = np.zeros(n_periods)
    
    # Phase 1: Pre-crash (start to crash_start)
    # Normal crypto volatility with trend towards peak
    crash_start_idx = np.searchsorted(timestamps, coin.crash_start)
    peak_idx = np.searchsorted(timestamps, coin.peak_date)
    
    # Start from some fraction of peak and trend toward it
    start_price = coin.peak_price * 0.3
    prices[0] = start_price
    
    # Random walk to peak
    daily_volatility = 0.05  # 5% daily vol typical for alts
    for i in range(1, peak_idx):
        trend = (coin.peak_price - prices[i-1]) / (peak_idx - i + 1) / prices[i-1]
        shock = np.random.normal(0, daily_volatility / np.sqrt(periods_per_day))
        prices[i] = prices[i-1] * (1 + trend + shock)
    
    prices[peak_idx] = coin.peak_price
    
    # Phase 2: The crash (peak to crash_end)
    # Accelerating decay with high volatility
    crash_end_idx = min(np.searchsorted(timestamps, coin.crash_end), n_periods - 1)
    crash_periods = crash_end_idx - peak_idx
    
    if crash_periods > 0:
        # Exponential decay during crash
        decay_rate = np.log(coin.final_price / coin.peak_price) / crash_periods
        
        for i in range(peak_idx + 1, crash_end_idx + 1):
            # High volatility during crash
            vol_multiplier = 3.0  # 3x normal volatility during crash
            shock = np.random.normal(0, daily_volatility * vol_multiplier / np.sqrt(periods_per_day))
            
            # Exponential decay component + noise
            expected_price = coin.peak_price * np.exp(decay_rate * (i - peak_idx))
            prices[i] = expected_price * (1 + shock)
            
            # Ensure monotonic decay on average (crashes don't recover)
            prices[i] = min(prices[i], prices[i-1] * 1.1)
            prices[i] = max(prices[i], coin.final_price * 0.5)
    
    # Phase 3: Post-crash zombie (crash_end to end)
    # Low volume, gradual bleed to final price
    for i in range(crash_end_idx + 1, n_periods):
        # Very low volatility, slow decay
        shock = np.random.normal(0, daily_volatility * 0.5 / np.sqrt(periods_per_day))
        decay = np.log(coin.final_price / prices[i-1]) / (n_periods - i + 1)
        prices[i] = prices[i-1] * (1 + decay + shock)
        prices[i] = max(prices[i], coin.final_price * 0.1)
    
    # Generate OHLC from close prices
    # Typical crypto: high-low range is 2-5% of price
    ohlc_data = []
    for i, (ts, close) in enumerate(zip(timestamps, prices)):
        # Intraday volatility
        hl_range = close * np.random.uniform(0.01, 0.05)
        
        if i == 0:
            open_price = close
        else:
            open_price = prices[i-1]
        
        high = max(open_price, close) + hl_range * np.random.uniform(0.2, 0.5)
        low = min(open_price, close) - hl_range * np.random.uniform(0.2, 0.5)
        
        # Volume: high during crash, low otherwise
        if peak_idx <= i <= crash_end_idx:
            base_volume = np.random.uniform(1000000, 10000000)  # High volume during crash
        else:
            base_volume = np.random.uniform(100000, 1000000)
        
        volume = base_volume * (close / coin.peak_price) ** -0.5  # Higher volume as price drops
        
        ohlc_data.append({
            "timestamp": ts,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })
    
    df = pd.DataFrame(ohlc_data)
    df = df.set_index("timestamp")
    
    # Add delisting marker
    df["is_delisted"] = False
    delist_idx = np.searchsorted(timestamps, coin.crash_end)
    if delist_idx < len(df):
        df.iloc[delist_idx:, df.columns.get_loc("is_delisted")] = True
    
    print(f"  Synthesized {len(df)} candles")
    print(f"    Peak: ${coin.peak_price:.4f} at {coin.peak_date}")
    print(f"    Crash: {coin.crash_start} to {coin.crash_end}")
    print(f"    Final: ${coin.final_price:.6f}")
    print(f"    Actual crash return: {coin.total_return_during_crash:.2%}")
    
    return df


def save_dead_coin_data(
    df: pd.DataFrame,
    coin: DeadCoin,
    output_dir: Path,
    timeframe: str = "4h",
    days: int = 2190,  # ~6 years
):
    """Save dead coin data to parquet file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save main OHLCV data
    filename = f"{coin.symbol.replace('/', '_')}_{timeframe}_{days}d.parquet"
    filepath = output_dir / filename
    
    # Save without metadata columns
    df_save = df[["open", "high", "low", "close", "volume"]].copy()
    df_save.to_parquet(filepath)
    
    print(f"  Saved OHLCV to {filepath}")
    
    # Save metadata JSON
    meta_filename = f"{coin.symbol.replace('/', '_')}_metadata.json"
    meta_filepath = output_dir / meta_filename
    
    metadata = {
        "symbol": coin.symbol,
        "name": coin.name,
        "is_dead_coin": True,
        "peak_price": coin.peak_price,
        "peak_date": coin.peak_date.isoformat(),
        "crash_start": coin.crash_start.isoformat(),
        "crash_end": coin.crash_end.isoformat(),
        "final_price": coin.final_price,
        "crash_reason": coin.crash_reason,
        "total_return_during_crash": coin.total_return_during_crash,
        "delisting_date": coin.crash_end.isoformat(),
        "data_source": "synthesized" if not coin.available_on_binance else "binance",
    }
    
    with open(meta_filepath, "w") as f:
        json.dump(metadata, f, indent=2, default=str)
    
    print(f"  Saved metadata to {meta_filepath}")
    
    return filepath, meta_filepath


def create_combined_metadata(output_dir: Path):
    """Create a combined metadata file for all dead coins."""
    all_metadata = []
    
    for json_file in output_dir.glob("*_metadata.json"):
        with open(json_file) as f:
            all_metadata.append(json.load(f))
    
    combined_path = output_dir / "dead_coins_metadata.json"
    with open(combined_path, "w") as f:
        json.dump(all_metadata, f, indent=2, default=str)
    
    print(f"\nCombined metadata saved to {combined_path}")
    
    # Create summary report
    print("\n" + "=" * 60)
    print("DEAD COIN SUMMARY")
    print("=" * 60)
    
    for coin_data in all_metadata:
        print(f"\n{coin_data['symbol']} - {coin_data['name']}")
        print(f"  Crash: {coin_data['crash_reason']}")
        print(f"  Peak: ${coin_data['peak_price']:.4f} ({coin_data['peak_date'][:10]})")
        print(f"  Final: ${coin_data['final_price']:.6f}")
        print(f"  Loss: {coin_data['total_return_during_crash']:.2%}")
        print(f"  Delisted: {coin_data['delisting_date'][:10]}")


def main():
    parser = argparse.ArgumentParser(
        description="Fetch or synthesize historical data for dead/failed cryptocurrencies"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data_4h",
        help="Output directory for dead coin data",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="4h",
        help="Candle timeframe (default: 4h)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=2190,
        help="Days of history (default: 2190 = ~6 years)",
    )
    parser.add_argument(
        "--coins",
        type=str,
        default="all",
        help="Comma-separated list of coin symbols, or 'all' (default: all)",
    )
    parser.add_argument(
        "--prefer-binance",
        action="store_true",
        help="Try to fetch from Binance first before synthesizing",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    
    args = parser.parse_args()
    
    np.random.seed(args.seed)
    output_dir = Path(args.output_dir)
    
    # Select coins to process
    if args.coins == "all":
        coins_to_process = DEAD_COINS
    else:
        symbols = [s.strip() for s in args.coins.split(",")]
        coins_to_process = [c for c in DEAD_COINS if c.symbol in symbols]
    
    print("=" * 60)
    print("DEAD COIN DATA GENERATOR")
    print("=" * 60)
    print(f"Processing {len(coins_to_process)} dead coins...")
    print(f"Output directory: {output_dir}")
    print(f"Timeframe: {args.timeframe}")
    print()
    
    for coin in coins_to_process:
        print(f"\nProcessing {coin.symbol} ({coin.name})")
        print("-" * 40)
        
        df = None
        
        # Try Binance if available and requested
        if args.prefer_binance and coin.available_on_binance:
            df = fetch_binance_data(
                coin.symbol,
                args.timeframe,
                coin.peak_date - timedelta(days=args.days),
                coin.crash_end,
            )
        
        # Synthesize if no data fetched
        if df is None or len(df) == 0:
            df = synthesize_crash_data(coin, args.timeframe)
        
        # Save data
        save_dead_coin_data(df, coin, output_dir, args.timeframe, args.days)
    
    # Create combined metadata
    create_combined_metadata(output_dir)
    
    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)
    print(f"\nDead coin data saved to {output_dir}/")
    print("\nUse this data in backtests to fix survivorship bias!")
    print("Remember: Survivorship bias makes strategies look better than they are.")


if __name__ == "__main__":
    main()
