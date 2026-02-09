#!/bin/bash
set -e

# Configuration
ML_PORT=9001
SENTIMENT_PORT=8000
ML_LOG="ml_server.log"
SENTIMENT_LOG="sentiment_server.log"
BOT_LOG="bot.log"
CONFIG_FILE="config.yaml"

# Cleanup function
cleanup() {
    echo "Stopping services..."
    if [ -n "$ML_PID" ]; then
        kill $ML_PID 2>/dev/null || true
    fi
    if [ -n "$SENTIMENT_PID" ]; then
        kill $SENTIMENT_PID 2>/dev/null || true
    fi
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

echo "=== Starting Quant Bot, ML Server & Sentiment Server ==="

# 1. Kill any existing servers
if check_port $ML_PORT; then
    echo "Port $ML_PORT is in use. Stopping existing process..."
    kill_port $ML_PORT
fi

if check_port $SENTIMENT_PORT; then
    echo "Port $SENTIMENT_PORT is in use. Stopping existing process..."
    kill_port $SENTIMENT_PORT
fi

# 2. Build Go bot
echo "Building Go bot..."
if ! go build -o bin/bot ./cmd/bot; then
    echo "❌ Go build failed!"
    exit 1
fi

# 3. Start ML Server
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
done
echo "✅ Sentiment Server is ready!"

# 7. Start Go Bot
echo "Starting Bot (logging to $BOT_LOG)..."
echo "Press Ctrl+C to stop all services."

./bin/bot -c $CONFIG_FILE | tee $BOT_LOG

# ...existing code...
