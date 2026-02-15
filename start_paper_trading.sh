#!/bin/bash
# Start paper trading bot with trend following strategy

set -e

echo "=========================================="
echo "Starting Paper Trading Bot"
echo "=========================================="
echo ""

# Check if config exists
if [ ! -f "config.trend.yaml" ]; then
    echo "Error: config.trend.yaml not found"
    exit 1
fi

# Verify mode is set to paper
MODE=$(grep "^mode:" config.trend.yaml | awk '{print $2}')
if [ "$MODE" != "paper" ]; then
    echo "WARNING: Mode is set to '$MODE', not 'paper'"
    echo "Please check config.trend.yaml before continuing"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "Configuration: config.trend.yaml"
echo "Mode: $MODE"
echo "Strategy: Trend Following"
echo "Symbols: BTC, ETH, SOL, BNB"
echo ""

# Create data directory if needed
mkdir -p data

# Start the bot
echo "Starting bot..."
./bin/bot --config config.trend.yaml
