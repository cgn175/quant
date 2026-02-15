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

# Check if sentiment server is running
SENTIMENT_URL=$(grep "url:" config.trend.yaml | grep -v "#" | head -1 | awk '{print $2}')
SENTIMENT_HOST=$(echo $SENTIMENT_URL | sed 's|http://||' | sed 's/:.*//')
SENTIMENT_PORT=$(echo $SENTIMENT_URL | sed 's/.*://')

echo "Checking sentiment server at $SENTIMENT_URL..."
if ! curl -s "$SENTIMENT_URL" > /dev/null 2>&1; then
    echo "WARNING: Sentiment server not running at $SENTIMENT_URL"
    echo "Sentiment features will default to 0.0"
    echo ""
    echo "To start sentiment server:"
    echo "  cd sentiment && python3 main.py"
    echo ""
    read -p "Continue without sentiment server? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "✓ Sentiment server is running"
fi

echo ""

# Start the bot
echo "Starting bot..."
./bin/bot --config config.trend.yaml
