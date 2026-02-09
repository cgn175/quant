# start.sh Update — Sentiment Server Integration

## What Was Updated

The `start.sh` script has been enhanced to automatically start the sentiment server along with the ML server and trading bot.

## Changes Made

### 1. Added Sentiment Server Configuration
```bash
SENTIMENT_PORT=8000
SENTIMENT_LOG="sentiment_server.log"
```

### 2. Enhanced Cleanup Function
Now stops both ML server and sentiment server:
```bash
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
```

### 3. Port Checking for Sentiment Server
Checks if port 8000 is in use and kills existing process:
```bash
if check_port $SENTIMENT_PORT; then
    echo "Port $SENTIMENT_PORT is in use. Stopping existing process..."
    kill_port $SENTIMENT_PORT
fi
```

### 4. Start Sentiment Server
Added step to start sentiment server:
```bash
# 4. Start Sentiment Server
echo "Starting Sentiment Server (port $SENTIMENT_PORT)..."
cd sentiment
python3 main.py > ../$SENTIMENT_LOG 2>&1 &
SENTIMENT_PID=$!
cd ..
```

### 5. Wait for Sentiment Server
Added health check for sentiment server:
```bash
# 6. Wait for Sentiment Server to be ready
echo "Waiting for Sentiment Server..."
count=0
while ! curl -s "http://localhost:$SENTIMENT_PORT/health" >/dev/null; do
    sleep 1
    count=$((count+1))
    if [ $count -ge $MAX_RETRIES ]; then
        echo "⚠️ Sentiment Server failed to start..."
        echo "Continuing anyway (sentiment is optional)..."
        break
    fi
done
echo "✅ Sentiment Server is ready!"
```

### 6. Updated Instructions
Changed "stop both services" to "stop all services"

## Startup Order

Now the script starts services in this order:

1. **Kill any existing servers** (ML + Sentiment)
2. **Build Go bot binary**
3. **Start ML Server** (port 9001)
4. **Start Sentiment Server** (port 8000)
5. **Wait for ML Server** (up to 30 seconds)
6. **Wait for Sentiment Server** (up to 30 seconds, optional)
7. **Start Go Bot** (logs to bot.log)

## Key Features

✅ **Automatic Startup** — Both servers start automatically
✅ **Health Checks** — Waits for both servers to be ready
✅ **Port Cleanup** — Kills existing processes using ports
✅ **Graceful Shutdown** — Stops all services on Ctrl+C
✅ **Logging** — Separate logs for each service:
   - `ml_server.log` — ML server output
   - `sentiment_server.log` — Sentiment server output
   - `bot.log` — Trading bot output
✅ **Optional Sentiment** — Bot continues if sentiment server fails (graceful degradation)

## Usage

Simply run:
```bash
./start.sh
```

This will now start:
1. ML Server (port 9001)
2. Sentiment Server (port 8000)
3. Trading Bot

All three services with proper health checks and logging.

## Service Logs

Monitor logs in real-time:
```bash
# ML Server
tail -f ml_server.log

# Sentiment Server
tail -f sentiment_server.log

# Trading Bot (also shown in console)
tail -f bot.log
```

## Stopping All Services

Press `Ctrl+C` in the terminal running `./start.sh`

This will gracefully stop all three services.

## Troubleshooting

### Port Already in Use
The script automatically kills processes on the required ports before starting:
- Port 9001 (ML Server)
- Port 8000 (Sentiment Server)

### Sentiment Server Fails to Start
The script will show a warning but continue anyway, since sentiment is optional. Check `sentiment_server.log` for details:
```bash
tail sentiment_server.log
```

### ML Server Fails to Start
The script will exit with an error since ML server is required. Check `ml_server.log` for details:
```bash
tail ml_server.log
```

### Bot Won't Start
Check both `ml_server.log` and `sentiment_server.log` to ensure they're running. Bot requires ML server to be ready.

## Summary

✅ **One Command, Three Services**

```bash
./start.sh
```

Now starts:
- ✅ ML Server (required)
- ✅ Sentiment Server (optional but recommended)
- ✅ Trading Bot

All with proper health checks, logging, and graceful shutdown!
