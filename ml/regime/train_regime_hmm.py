#!/usr/bin/env python3
"""Train HMM-based Regime Classifier per symbol.

Uses Hidden Markov Model with 3 states to detect market regimes:
    - State 0: Ranging (low volatility, no trend)
    - State 1: Trending (directional movement, high |forward returns|)
    - State 2: Volatile (high volatility, choppy, low directional persistence)

HMM advantages over RandomForest:
    - Captures regime transitions probabilistically
    - No overfitting to specific feature patterns
    - Smooth state transitions (not binary)
    - Better handles regime persistence

Usage:
    python3 ml/regime/train_regime_hmm.py                   # train all symbols
    python3 ml/regime/train_regime_hmm.py --symbol BTCUSDT  # train one symbol
"""

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import joblib
except ImportError:
    from sklearn.externals import joblib

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "training.db"
MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "regime_hmm_v1"

# Forward return look ahead for state validation (5 bars = ~20 hours)
FORWARD_BARS = 5


def load_data(symbol: str, db_path: Path) -> pd.DataFrame:
    """Load 4H candles from training.db."""
    conn = sqlite3.connect(db_path)
    query = f"""
        SELECT timestamp, open, high, low, close, volume
        FROM candles_4h
        WHERE symbol = '{symbol}'
        ORDER BY timestamp ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def build_hmm_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build features for HMM: returns, volatility, volume_ratio."""
    df = df.copy()
    
    # Returns (4H)
    df["returns"] = df["close"].pct_change()
    
    # Forward returns (for state validation)
    df["forward_return"] = df["close"].shift(-FORWARD_BARS) / df["close"] - 1
    df["abs_forward_return"] = df["forward_return"].abs()
    
    # Volatility (ATR%)
    df["range"] = df["high"] - df["low"]
    df["atr_14"] = df["range"].rolling(14).mean()
    df["volatility"] = df["atr_14"] / df["close"]
    
    # Volume ratio
    df["volume_ratio"] = df["volume"] / df["volume"].rolling(20).mean()
    
    # Drop NaN
    df = df.dropna()
    
    return df[["returns", "volatility", "volume_ratio", "forward_return", "abs_forward_return"]]


def analyze_states(train_df: pd.DataFrame, train_states: np.ndarray) -> dict:
    """Analyze state characteristics to determine proper labeling.
    
    Uses both volatility AND forward returns to properly identify states:
    - Trending: High |forward returns| (regardless of volatility)
    - Volatile: High volatility but low |forward returns| (choppy)
    - Ranging: Low volatility AND low |forward returns|
    """
    print("\n--- State Analysis (Train) ---")
    
    state_stats = {}
    
    for state in range(3):
        mask = train_states == state
        if mask.sum() == 0:
            continue
        
        state_data = train_df[mask]
        stats = {
            "count": mask.sum(),
            "pct": mask.sum() / len(train_states) * 100,
            "avg_returns": state_data["returns"].mean(),
            "avg_volatility": state_data["volatility"].mean(),
            "avg_volume_ratio": state_data["volume_ratio"].mean(),
            "avg_abs_forward_return": state_data["abs_forward_return"].mean(),
            "forward_return_25th": state_data["abs_forward_return"].quantile(0.25),
            "forward_return_75th": state_data["abs_forward_return"].quantile(0.75),
        }
        state_stats[state] = stats
        
        print(f"\nState {state} ({stats['count']} samples, {stats['pct']:.1f}%):")
        print(f"  Avg Returns: {stats['avg_returns']:.4f}")
        print(f"  Avg Volatility: {stats['avg_volatility']:.4f}")
        print(f"  Avg Volume Ratio: {stats['avg_volume_ratio']:.2f}")
        print(f"  Avg |Forward Return|: {stats['avg_abs_forward_return']:.4f}")
        print(f"  Forward Return 25th-75th: {stats['forward_return_25th']:.4f} - {stats['forward_return_75th']:.4f}")
    
    return state_stats


def label_states(state_stats: dict) -> dict:
    """Label HMM states based on forward returns AND volatility.
    
    Logic:
    1. Trending: Highest average |forward returns| (strong directional moves)
    2. Volatile: High volatility BUT low |forward returns| (choppy, no direction)
    3. Ranging: Low volatility AND low |forward returns| (quiet, no trend)
    """
    # Score each state on two dimensions
    states = list(state_stats.keys())
    
    # Rank by forward returns (higher = more trending)
    forward_returns = [(s, state_stats[s]["avg_abs_forward_return"]) for s in states]
    forward_returns.sort(key=lambda x: x[1], reverse=True)
    
    # Rank by volatility (higher = more volatile)
    volatilities = [(s, state_stats[s]["avg_volatility"]) for s in states]
    volatilities.sort(key=lambda x: x[1], reverse=True)
    
    print("\n--- State Rankings ---")
    print("By |Forward Return| (trend strength):")
    for rank, (state, val) in enumerate(forward_returns, 1):
        print(f"  {rank}. State {state}: {val:.4f}")
    
    print("\nBy Volatility:")
    for rank, (state, val) in enumerate(volatilities, 1):
        print(f"  {rank}. State {state}: {val:.4f}")
    
    # Determine labels
    # State with highest forward returns = Trending
    trending_state = forward_returns[0][0]
    
    # Among remaining states, highest volatility = Volatile, lowest = Ranging
    remaining = [s for s, _ in forward_returns[1:]]
    remaining_vol = [(s, state_stats[s]["avg_volatility"]) for s in remaining]
    remaining_vol.sort(key=lambda x: x[1], reverse=True)
    
    volatile_state = remaining_vol[0][0]
    ranging_state = remaining_vol[1][0]
    
    state_mapping = {
        ranging_state: "ranging",
        trending_state: "trending", 
        volatile_state: "volatile",
    }
    
    # Validate: Trending should have significantly higher forward returns
    trending_forward = state_stats[trending_state]["avg_abs_forward_return"]
    others_forward = [state_stats[s]["avg_abs_forward_return"] for s in [ranging_state, volatile_state]]
    avg_others = np.mean(others_forward)
    
    if trending_forward < avg_others * 1.2:  # Less than 20% higher
        print(f"\n⚠️  WARNING: Trending state forward return ({trending_forward:.4f})")
        print(f"    is not significantly higher than others ({avg_others:.4f})")
        print(f"    State separation may be poor. Consider retraining or using more data.")
    
    return state_mapping


def train_hmm(symbol: str, db_path: Path, model_dir: Path):
    """Train HMM regime model for a symbol."""
    print(f"\n{'='*60}")
    print(f"Training HMM Regime Classifier: {symbol}")
    print(f"{'='*60}")
    
    # Load data
    df = load_data(symbol, db_path)
    print(f"Loaded {len(df)} candles")
    
    # Build features (with forward returns for validation)
    features_df = build_hmm_features(df)
    print(f"Built features: {len(features_df)} rows")
    print(f"Forward return look-ahead: {FORWARD_BARS} bars (~{FORWARD_BARS*4} hours)")
    
    # Split train/test (80/20)
    split_idx = int(len(features_df) * 0.8)
    train_df_full = features_df.iloc[:split_idx]
    test_df_full = features_df.iloc[split_idx:]
    
    # For HMM training, only use contemporaneous features (no forward data)
    train_df = train_df_full[["returns", "volatility", "volume_ratio"]]
    test_df = test_df_full[["returns", "volatility", "volume_ratio"]]
    
    print(f"Train: {len(train_df)} | Test: {len(test_df)}")
    
    # Standardize features
    scaler = StandardScaler()
    X_train = scaler.fit_transform(train_df)
    X_test = scaler.transform(test_df)
    
    # Train HMM with 3 states
    print("\nTraining HMM (3 states)...")
    model = GaussianHMM(
        n_components=3,
        covariance_type="full",
        n_iter=100,
        random_state=42,
    )
    model.fit(X_train)
    
    # Predict states
    train_states = model.predict(X_train)
    test_states = model.predict(X_test)
    
    # Analyze and label states using forward returns
    state_stats = analyze_states(train_df_full, train_states)
    state_mapping = label_states(state_stats)
    
    print("\n--- Final State Mapping ---")
    for state, label in sorted(state_mapping.items()):
        print(f"State {state} -> {label}")
    
    # Validate on test set
    print("\n--- Test Set Validation ---")
    test_stats = {}
    for state in range(3):
        mask = test_states == state
        if mask.sum() == 0:
            continue
        state_data = test_df_full[mask]
        label = state_mapping[state]
        avg_forward = state_data["abs_forward_return"].mean()
        avg_vol = state_data["volatility"].mean()
        test_stats[state] = {"forward": avg_forward, "vol": avg_vol}
        print(f"{label:12s}: |forward|={avg_forward:.4f}, vol={avg_vol:.4f}, n={mask.sum()}")
    
    # Save model and scaler
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / f"{symbol}.pkl"
    scaler_path = model_dir / f"{symbol}_scaler.pkl"
    mapping_path = model_dir / f"{symbol}_mapping.pkl"
    stats_path = model_dir / f"{symbol}_stats.pkl"
    
    joblib.dump(model, model_path)
    joblib.dump(scaler, scaler_path)
    joblib.dump(state_mapping, mapping_path)
    joblib.dump(state_stats, stats_path)
    
    print(f"\n✓ Saved model to {model_path}")
    print(f"✓ Saved scaler to {scaler_path}")
    print(f"✓ Saved mapping to {mapping_path}")
    print(f"✓ Saved stats to {stats_path}")


def main():
    parser = argparse.ArgumentParser(description="Train HMM regime classifier")
    parser.add_argument("--symbol", type=str, help="Train single symbol")
    args = parser.parse_args()
    
    symbols = [args.symbol] if args.symbol else SYMBOLS
    
    for symbol in symbols:
        try:
            train_hmm(symbol, DB_PATH, MODEL_DIR)
        except Exception as e:
            print(f"ERROR training {symbol}: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
