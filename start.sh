#!/bin/bash
set -e

# Configuration
ML_PORT=9001
SENTIMENT_PORT=8000
ML_LOG="logs/ml_server.log"
SENTIMENT_LOG="logs/sentiment_server.log"

# Create logs directory
mkdir -p logs

# Bot configs and logs
CONFIG_TREND="config.trend.yaml"
LOG_TREND="logs/bot_trend.log"

CONFIG_MM="config.mm.yaml"
LOG_MM="logs/bot_mm.log"

CONFIG_FUNDING="config.funding.yaml"
LOG_FUNDING="logs/bot_funding.log"

CONFIG_BASIS="config.basis.yaml"
LOG_BASIS="logs/bot_basis.log"

CONFIG_LIQUIDATION="config.liquidation.yaml"
LOG_LIQUIDATION="logs/bot_liquidation.log"

# Cleanup function
cleanup() {
    echo "Stopping services..."
    # Kill bots
    if [ -n "$PID_TREND" ]; then kill $PID_TREND 2>/dev/null || true; fi
    if [ -n "$PID_MM" ]; then kill $PID_MM 2>/dev/null || true; fi
    if [ -n "$PID_FUNDING" ]; then kill $PID_FUNDING 2>/dev/null || true; fi
    if [ -n "$PID_BASIS" ]; then kill $PID_BASIS 2>/dev/null || true; fi
    if [ -n "$PID_LIQUIDATION" ]; then kill $PID_LIQUIDATION 2>/dev/null || true; fi

    # Kill servers
    if [ -n "$ML_PID" ]; then kill $ML_PID 2>/dev/null || true; fi
    if [ -n "$SENTIMENT_PID" ]; then kill $SENTIMENT_PID 2>/dev/null || true; fi

    exit 0
}

# Trap signals
trap cleanup SIGINT SIGTERM

# Check if port is in use
check_port() {
    lsof -i :$1 >/dev/null 2>&1
}

# Kill process on a port
kill_port() {
    local port=$1
    local pid=$(lsof -t -i :$port)
    if [ -n "$pid" ]; then
        echo "Killing process on port $port (PID: $pid)..."
        kill -9 $pid 2>/dev/null || true
        sleep 1
    fi
}

# Check if a bot is already running with a specific config
is_bot_running() {
    local config=$1
    pgrep -f "bin/bot.*--config.*$config" >/dev/null 2>&1
}

# Kill existing bot instances
kill_existing_bots() {
    echo "Checking for existing bot instances..."
    local count=0
    for config in "$CONFIG_TREND" "$CONFIG_MM" "$CONFIG_FUNDING" "$CONFIG_BASIS" "$CONFIG_LIQUIDATION"; do
        if [ -n "$config" ]; then
            local pids=$(pgrep -f "bin/bot.*--config.*$config" 2>/dev/null)
            if [ -n "$pids" ]; then
                echo "  Killing existing bot for $config (PIDs: $pids)..."
                kill -9 $pids 2>/dev/null || true
                count=$((count + 1))
            fi
        fi
    done
    if [ $count -gt 0 ]; then
        sleep 2
    fi
}

echo "=== Starting Quant Bot Cluster (Trend, MM, Funding, Basis, Liquidation) ==="

# 1. Kill any existing bot instances to prevent duplicates
kill_existing_bots

# 2. Kill any existing servers
if check_port $ML_PORT; then
    echo "Port $ML_PORT is in use. Stopping existing process..."
    kill_port $ML_PORT
fi

if check_port $SENTIMENT_PORT; then
    echo "Port $SENTIMENT_PORT is in use. Stopping existing process..."
    kill_port $SENTIMENT_PORT
fi

# 3. Build Go bot
echo "Building Go bot..."
if ! go build -o bin/bot ./cmd/bot; then
    echo "❌ Go build failed!"
    exit 1
fi

# 4. Start ML Server
echo "Starting ML Server (port $ML_PORT)..."
python3 ml/server.py --models-dir ml/models > $ML_LOG 2>&1 &
ML_PID=$!

# 4. Start Sentiment Server
echo "Starting Sentiment Server (port $SENTIMENT_PORT)..."
cd sentiment
python3 main.py > ../$SENTIMENT_LOG 2>&1 &
SENTIMENT_PID=$!
cd ..

# 5. Wait for ML Server to be ready
echo "Waiting for ML Server..."
MAX_RETRIES=30
count=0
while ! curl -s "http://localhost:$ML_PORT/health" >/dev/null; do
    sleep 1
    count=$((count+1))
    if [ $count -ge $MAX_RETRIES ]; then
        echo "❌ ML Server failed to start within $MAX_RETRIES seconds."
        echo "Check $ML_LOG for details."
        cleanup
        exit 1
    fi
    sleep 1
done
echo "✅ ML Server is ready!"

# 6. Wait for Sentiment Server to be ready
echo "Waiting for Sentiment Server..."
count=0
while ! curl -s "http://localhost:$SENTIMENT_PORT/health" >/dev/null; do
    sleep 1
    count=$((count+1))
    if [ $count -ge $MAX_RETRIES ]; then
        echo "⚠️ Sentiment Server failed to start within $MAX_RETRIES seconds."
        echo "Check $SENTIMENT_LOG for details."
        echo "Continuing anyway (sentiment is optional)..."
        break
    fi
    sleep 1
done
echo "✅ Sentiment Server is ready!"

# 7. Start Bots in Parallel (only if configs exist)
if [ -f "$CONFIG_TREND" ]; then
    echo "🚀 Starting Trend Following Bot..."
    ./bin/bot --config $CONFIG_TREND > $LOG_TREND 2>&1 &
    PID_TREND=$!
    echo "   PID: $PID_TREND | Log: $LOG_TREND | Config: $CONFIG_TREND"
else
    echo "⚠️  Skipping Trend Bot (config not found: $CONFIG_TREND)"
fi

if [ -f "$CONFIG_MM" ]; then
    echo "🚀 Starting Market Making Bot..."
    ./bin/bot --config $CONFIG_MM > $LOG_MM 2>&1 &
    PID_MM=$!
    echo "   PID: $PID_MM | Log: $LOG_MM | Config: $CONFIG_MM"
else
    echo "⚠️  Skipping MM Bot (config not found: $CONFIG_MM)"
fi

if [ -f "$CONFIG_FUNDING" ]; then
    echo "🚀 Starting Funding Arbitrage Bot..."
    ./bin/bot --config $CONFIG_FUNDING > $LOG_FUNDING 2>&1 &
    PID_FUNDING=$!
    echo "   PID: $PID_FUNDING | Log: $LOG_FUNDING | Config: $CONFIG_FUNDING"
else
    echo "⚠️  Skipping Funding Bot (config not found: $CONFIG_FUNDING)"
fi

if [ -f "$CONFIG_BASIS" ]; then
    echo "🚀 Starting Basis Trade Bot..."
    ./bin/bot --config $CONFIG_BASIS > $LOG_BASIS 2>&1 &
    PID_BASIS=$!
    echo "   PID: $PID_BASIS | Log: $LOG_BASIS | Config: $CONFIG_BASIS"
else
    echo "⚠️  Skipping Basis Bot (config not found: $CONFIG_BASIS)"
fi

if [ -f "$CONFIG_LIQUIDATION" ]; then
    echo "🚀 Starting Liquidation Cascade Bot..."
    ./bin/bot --config $CONFIG_LIQUIDATION > $LOG_LIQUIDATION 2>&1 &
    PID_LIQUIDATION=$!
    echo "   PID: $PID_LIQUIDATION | Log: $LOG_LIQUIDATION | Config: $CONFIG_LIQUIDATION"
else
    echo "⚠️  Skipping Liquidation Bot (config not found: $CONFIG_LIQUIDATION)"
fi

echo "=== All systems operational ==="
echo "Press Ctrl+C to stop all services."
echo "View logs: tail -f logs/bot_*.log"

# Wait for all processes to exit
wait $PID_TREND $PID_MM $PID_FUNDING $PID_BASIS $PID_LIQUIDATION $ML_PID $SENTIMENT_PID
