#!/usr/bin/env python3
"""Train HMM-based Regime Classifier per symbol.

Uses Hidden Markov Model with 3 states to detect market regimes:
    - State 0: Ranging (low volatility, no trend)
    - State 1: Trending (directional movement)
    - State 2: Volatile (high volatility, choppy)

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
    
    # Volatility (ATR%)
    df["range"] = df["high"] - df["low"]
    df["atr_14"] = df["range"].rolling(14).mean()
    df["volatility"] = df["atr_14"] / df["close"]
    
    # Volume ratio
    df["volume_ratio"] = df["volume"] / df["volume"].rolling(20).mean()
    
    # Drop NaN
    df = df.dropna()
    
    return df[["returns", "volatility", "volume_ratio"]]


def train_hmm(symbol: str, db_path: Path, model_dir: Path):
    """Train HMM regime model for a symbol."""
    print(f"\n{'='*60}")
    print(f"Training HMM Regime Classifier: {symbol}")
    print(f"{'='*60}")
    
    # Load data
    df = load_data(symbol, db_path)
    print(f"Loaded {len(df)} candles")
    
    # Build features
    features_df = build_hmm_features(df)
    print(f"Built features: {len(features_df)} rows")
    
    # Split train/test (80/20)
    split_idx = int(len(features_df) * 0.8)
    train_df = features_df.iloc[:split_idx]
    test_df = features_df.iloc[split_idx:]
    
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
    
    # Analyze state characteristics
    print("\n--- State Analysis (Train) ---")
    for state in range(3):
        mask = train_states == state
        if mask.sum() == 0:
            continue
        
        state_data = train_df[mask]
        print(f"\nState {state} ({mask.sum()} samples, {mask.sum()/len(train_states)*100:.1f}%):")
        print(f"  Avg Returns: {state_data['returns'].mean():.4f}")
        print(f"  Avg Volatility: {state_data['volatility'].mean():.4f}")
        print(f"  Avg Volume Ratio: {state_data['volume_ratio'].mean():.2f}")
    
    # Label states based on characteristics
    # State with highest volatility = volatile
    # State with lowest volatility = ranging
    # Middle state = trending
    state_vols = []
    for state in range(3):
        mask = train_states == state
        if mask.sum() > 0:
            avg_vol = train_df[mask]["volatility"].mean()
            state_vols.append((state, avg_vol))
    
    state_vols.sort(key=lambda x: x[1])
    state_mapping = {
        state_vols[0][0]: "ranging",
        state_vols[1][0]: "trending",
        state_vols[2][0]: "volatile",
    }
    
    print("\n--- State Mapping ---")
    for state, label in state_mapping.items():
        print(f"State {state} -> {label}")
    
    # Save model and scaler
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / f"{symbol}.pkl"
    scaler_path = model_dir / f"{symbol}_scaler.pkl"
    mapping_path = model_dir / f"{symbol}_mapping.pkl"
    
    joblib.dump(model, model_path)
    joblib.dump(scaler, scaler_path)
    joblib.dump(state_mapping, mapping_path)
    
    print(f"\n✓ Saved model to {model_path}")
    print(f"✓ Saved scaler to {scaler_path}")
    print(f"✓ Saved mapping to {mapping_path}")


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
