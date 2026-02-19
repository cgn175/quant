#!/bin/bash
# Start all data collectors for high-alpha strategies

set -e

PROJECT_DIR="/Users/hoangta/projects/quant"
cd "$PROJECT_DIR"

echo "=========================================="
echo "Starting Data Collectors"
echo "=========================================="
echo ""

# Check if wshub is running
if ! pgrep -f "wshub" > /dev/null; then
    echo "❌ WebSocket hub not running!"
    echo "   Start it first: docker-compose up -d wshub"
    exit 1
fi
echo "✅ WebSocket hub running"

# Build collectors if needed
echo ""
echo "Building collectors..."
go build -o bin/liquidation_collector ./cmd/liquidation_collector
go build -o bin/orderflow_collector ./cmd/orderflow_collector
echo "✅ Collectors built"

# Create data directory
mkdir -p data logs

# Start liquidation collector
echo ""
echo "Starting liquidation collector..."
if pgrep -f "liquidation_collector" > /dev/null; then
    echo "⚠️  Liquidation collector already running"
else
    nohup ./bin/liquidation_collector \
        --db data/liquidations.db \
        --hub-url localhost:9089/ws \
        > logs/liquidation_collector.log 2>&1 &
    echo "✅ Liquidation collector started (PID: $!)"
fi

# Start order flow collector
echo ""
echo "Starting order flow collector..."
if pgrep -f "orderflow_collector" > /dev/null; then
    echo "⚠️  Order flow collector already running"
else
    nohup ./bin/orderflow_collector \
        --db data/orderflow.db \
        --hub-url localhost:9089/ws \
        --symbols btcusdt,ethusdt,solusdt,bnbusdt \
        > logs/orderflow_collector.log 2>&1 &
    echo "✅ Order flow collector started (PID: $!)"
fi

echo ""
echo "=========================================="
echo "Data Collection Status"
echo "=========================================="
echo ""
echo "Collectors running:"
ps aux | grep -E "liquidation_collector|orderflow_collector" | grep -v grep | awk '{print "  " $11 " (PID: " $2 ")"}'

echo ""
echo "Databases:"
ls -lh data/*.db 2>/dev/null | awk '{print "  " $9 " (" $5 ")"}'

echo ""
echo "Logs:"
echo "  tail -f logs/liquidation_collector.log"
echo "  tail -f logs/orderflow_collector.log"

echo ""
echo "To stop:"
echo "  pkill liquidation_collector"
echo "  pkill orderflow_collector"

echo ""
echo "=========================================="
echo "✅ All collectors started!"
echo "=========================================="
