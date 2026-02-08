#!/bin/bash
# Helper script to fetch 5-minute data for all coins

echo "=================================================="
echo "  Fetching 5-Minute Data for Crypto Trading Bot"
echo "=================================================="
echo ""
echo "This will download 365 days of 5-minute OHLCV data"
echo "for BTC/USDT, ETH/USDT, SOL/USDT, and BNB/USDT"
echo ""

# Create output directory
mkdir -p data_5m

# Fetch data
python3 scripts/fetch_data.py \
    --symbols "BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT" \
    --timeframe 5m \
    --days 365 \
    --output data_5m

echo ""
echo "=================================================="
echo "✓ Data fetching complete!"
echo "=================================================="
echo ""
echo "Next steps:"
echo "1. Train model: python3 scripts/train_model.py --data-dir data_5m --symbols 'BTC/USDT' --threshold 0.002 --timeframe 5m"
echo "2. Or use the notebook: jupyter notebook scripts/train_model.ipynb"
echo ""
