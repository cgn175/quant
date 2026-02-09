#!/bin/bash
set -e

# Function to check if a port is in use
check_port() {
    lsof -i :$1 >/dev/null 2>&1
}

# Function to kill process on a port
kill_port() {
    local port=$1
    local pid=$(lsof -t -i :$port)
    if [ -n "$pid" ]; then
        echo "Killing process on port $port (PID: $pid)..."
        kill $pid
        sleep 2
    fi
}

# Kill existing processes
if check_port 9001; then
    kill_port 9001
fi

# Build the Go bot
echo "Building Go bot..."
go build -o bin/bot ./cmd/bot

# Start ML Server in background
echo "Starting ML Server on port 9001..."
python3 ml/server.py --models-dir ml/models > ml_server.log 2>&1 &
ML_PID=$!

# Wait for ML server to be ready
echo "Waiting for ML server..."
for i in {1..30}; do
    if curl -s http://localhost:9001/health >/dev/null; then
        echo "ML Server is ready!"
        break
    fi
    sleep 1
done

# Start the bot
echo "Starting Bot..."
./bin/bot -c config.yaml

# Cleanup on exit
kill $ML_PID
