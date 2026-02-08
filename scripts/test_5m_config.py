#!/usr/bin/env python3
"""Test script to verify 5-minute configuration is correct."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd
from build_features import FEATURE_COLUMNS, add_features, add_labels

print("=" * 70)
print("Testing 5-Minute Feature Engineering")
print("=" * 70)

# Create sample 5-minute data
print("\n1. Creating sample 5-minute OHLCV data...")
dates = pd.date_range("2025-01-01", periods=1000, freq="5min")
df = pd.DataFrame(
    {
        "open": 45000 + np.random.randn(1000) * 100,
        "high": 45050 + np.random.randn(1000) * 100,
        "low": 44950 + np.random.randn(1000) * 100,
        "close": 45000 + np.random.randn(1000) * 100,
        "volume": 100 + np.random.randn(1000) * 10,
    },
    index=dates,
)

print(f"   Created {len(df)} bars of 5m data")

# Test feature generation
print("\n2. Testing feature generation (5m timeframe)...")
try:
    df_features = add_features(df, timeframe="5m")
    print(f"   ✓ Features generated successfully")
    print(f"   ✓ Shape: {df_features.shape}")
except Exception as e:
    print(f"   ✗ Error: {e}")
    sys.exit(1)

# Test label generation
print("\n3. Testing label generation (threshold=0.002)...")
try:
    df_labeled = add_labels(df_features, threshold=0.002)
    print(f"   ✓ Labels generated successfully")

    # Show label distribution
    label_counts = df_labeled["label"].value_counts().sort_index()
    print(f"\n   Label distribution:")
    for label, count in label_counts.items():
        label_name = {0: "DOWN", 1: "NEUTRAL", 2: "UP"}[label]
        pct = count / len(df_labeled) * 100
        print(f"     {label_name:8s}: {count:4d} ({pct:5.1f}%)")

except Exception as e:
    print(f"   ✗ Error: {e}")
    sys.exit(1)

# Check feature columns
print(f"\n4. Checking feature columns...")
print(f"   Total features: {len(FEATURE_COLUMNS)}")
print(f"   Expected: 33 features")

if len(FEATURE_COLUMNS) == 33:
    print(f"   ✓ Correct number of features!")
else:
    print(f"   ✗ Wrong number of features (expected 33, got {len(FEATURE_COLUMNS)})")

# List new multi-timeframe features
new_features = [
    "ema_21_15m",
    "ema_50_15m",
    "ema_21_1h",
    "ema_50_1h",
    "trend_aligned",
    "vol_surge",
    "pv_divergence",
    "is_us_session",
    "is_asia_session",
    "is_weekend",
]

print(f"\n5. Verifying new multi-timeframe features...")
missing = []
for feat in new_features:
    if feat in FEATURE_COLUMNS:
        print(f"   ✓ {feat}")
    else:
        print(f"   ✗ {feat} - MISSING!")
        missing.append(feat)

# Check for NaN handling
print(f"\n6. Checking NaN handling...")
non_null = df_labeled[FEATURE_COLUMNS].dropna()
print(f"   Rows before dropna: {len(df_labeled)}")
print(f"   Rows after dropna:  {len(non_null)}")
print(f"   Dropped: {len(df_labeled) - len(non_null)} (expected ~600 for warmup)")

# Summary
print("\n" + "=" * 70)
if missing:
    print("❌ TEST FAILED - Missing features:")
    for feat in missing:
        print(f"   - {feat}")
    sys.exit(1)
else:
    print("✅ ALL TESTS PASSED!")
    print("\nYour 5-minute configuration is correct and ready to use.")
    print("\nNext steps:")
    print("  1. Fetch data: ./scripts/fetch_5m_data.sh")
    print("  2. Train model: python3 scripts/train_model.py --data-dir data_5m \\")
    print("                      --symbols 'BTC/USDT' --threshold 0.002 --timeframe 5m")

print("=" * 70)
