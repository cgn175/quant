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

# Check if ML server is running (required for regime filter and dynamic stop)
ML_URL=$(grep "url:" config.trend.yaml | grep -v "#" | head -1 | awk '{print $2}')
if [ -n "$ML_URL" ]; then
    echo "Checking ML server at $ML_URL..."
    if ! curl -s "$ML_URL/health" > /dev/null 2>&1; then
        echo "WARNING: ML server not running at $ML_URL"
        echo "Regime filter and dynamic stop will fall back to ADX"
        echo ""
        echo "To start ML server:"
        echo "  python3 ml/server.py --models-dir ml/models"
        echo ""
        read -p "Continue without ML server? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        echo "✓ ML server is running"
    fi
    echo ""
fi

# Check if sentiment server is running
SENTIMENT_URL=$(grep "sentiment:" -A 5 config.trend.yaml | grep "url:" | head -1 | awk '{print $2}')
if [ -n "$SENTIMENT_URL" ]; then
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
fi

# Start the bot
echo "Starting bot..."
./bin/bot --config config.trend.yaml
