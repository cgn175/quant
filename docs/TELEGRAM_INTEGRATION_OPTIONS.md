# Telegram Integration Options

The Telegram listener can be deployed in two ways:

## Option 1: Integrated with Sentiment Server (Recommended for Development)

The listener runs as a background task within the sentiment server process.

### Pros:
- ✅ Single process to manage
- ✅ Automatic startup/shutdown with server
- ✅ Shared database connection
- ✅ Simple deployment (one command)
- ✅ Easy development and debugging

### Cons:
- ❌ Server restart stops message collection
- ❌ Server crash loses listener
- ❌ Can't scale independently
- ❌ Shared resource limits (memory, CPU)

### Usage:

```bash
# Enable in .env
SENTIMENT_TELEGRAM_LISTENER_ENABLED=true
SENTIMENT_TELEGRAM_API_ID=12345678
SENTIMENT_TELEGRAM_API_HASH=abcdef1234567890

# Start server (listener auto-starts)
cd sentiment
uvicorn main:app --reload
```

Server logs will show:
```
2026-02-10 20:00:00 - __main__ - INFO - Starting Sentiment Microservice
2026-02-10 20:00:01 - __main__ - INFO - FinBERT model loaded successfully
2026-02-10 20:00:02 - __main__ - INFO - Starting integrated Telegram listener...
2026-02-10 20:00:03 - __main__ - INFO - ✓ Telegram listener started
2026-02-10 20:00:04 - __main__ - INFO - Sentiment server ready!
```

Check status:
```bash
curl http://localhost:8000/telegram/status
```

Response:
```json
{
  "integrated": true,
  "available": true,
  "running": true,
  "message_count": 42,
  "channels": 8
}
```

## Option 2: Standalone Service (Recommended for Production)

The listener runs as a separate process/service independent of the sentiment server.

### Pros:
- ✅ Independent lifecycle (server restart doesn't affect listener)
- ✅ Better fault isolation (crash doesn't affect the other)
- ✅ Can scale independently
- ✅ Dedicated resource allocation
- ✅ 24/7 message collection even if server is down

### Cons:
- ❌ Two processes to manage
- ❌ Separate deployment/monitoring
- ❌ Slightly more complex setup

### Usage:

```bash
# Disable integration in .env
SENTIMENT_TELEGRAM_LISTENER_ENABLED=false

# Start listener separately
python3 sentiment/telegram_listener.py &

# Start server
cd sentiment
uvicorn main:app --reload
```

### Deployment Options

#### systemd (Linux)

Create `/etc/systemd/system/telegram-listener.service`:
```ini
[Unit]
Description=Telegram Crypto News Listener
After=network.target

[Service]
Type=simple
User=sentiment
WorkingDirectory=/home/sentiment/quant/sentiment
ExecStart=/usr/bin/python3 telegram_listener.py
Restart=always
RestartSec=10
Environment="SENTIMENT_TELEGRAM_API_ID=12345678"
Environment="SENTIMENT_TELEGRAM_API_HASH=abcdef1234567890"

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable telegram-listener
sudo systemctl start telegram-listener
sudo systemctl status telegram-listener
```

#### Docker Compose

Add to `docker-compose.yml`:
```yaml
services:
  telegram-listener:
    build:
      context: .
      dockerfile: Dockerfile.telegram
    container_name: telegram-listener
    restart: unless-stopped
    volumes:
      - ./.telegram_sessions:/app/.telegram_sessions
      - ./sentiment.db:/app/sentiment.db
    environment:
      - SENTIMENT_TELEGRAM_API_ID=${SENTIMENT_TELEGRAM_API_ID}
      - SENTIMENT_TELEGRAM_API_HASH=${SENTIMENT_TELEGRAM_API_HASH}
    depends_on:
      - sentiment-server

  sentiment-server:
    build: .
    container_name: sentiment-server
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./sentiment.db:/app/sentiment.db
    environment:
      - SENTIMENT_TELEGRAM_LISTENER_ENABLED=false  # Standalone listener
```

Start:
```bash
docker-compose up -d
```

#### Supervisor (Python)

Create `/etc/supervisor/conf.d/telegram-listener.conf`:
```ini
[program:telegram-listener]
command=/usr/bin/python3 /home/sentiment/quant/sentiment/telegram_listener.py
directory=/home/sentiment/quant/sentiment
user=sentiment
autostart=true
autorestart=true
stderr_logfile=/var/log/telegram-listener.err.log
stdout_logfile=/var/log/telegram-listener.out.log
environment=SENTIMENT_TELEGRAM_API_ID="12345678",SENTIMENT_TELEGRAM_API_HASH="abcdef1234567890"
```

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start telegram-listener
```

## Recommendation

### Development:
**Use Integrated mode** (Option 1)
- Simple setup, easy debugging
- Restart server to restart listener

### Production:
**Use Standalone service** (Option 2)
- Better reliability and isolation
- Independent scaling
- Continuous message collection

## Configuration Summary

### Integrated Mode

```bash
# .env
SENTIMENT_TELEGRAM_LISTENER_ENABLED=true
SENTIMENT_TELEGRAM_API_ID=12345678
SENTIMENT_TELEGRAM_API_HASH=abcdef1234567890
SENTIMENT_TELEGRAM_SESSION_NAME=sentiment_bot
```

```bash
# Start
uvicorn main:app --reload
```

### Standalone Mode

```bash
# .env
SENTIMENT_TELEGRAM_LISTENER_ENABLED=false  # Disable integration
SENTIMENT_TELEGRAM_API_ID=12345678
SENTIMENT_TELEGRAM_API_HASH=abcdef1234567890
```

```bash
# Start listener
python3 telegram_listener.py &

# Start server
uvicorn main:app --reload
```

## Monitoring

### Integrated Mode

```bash
# Check logs
tail -f sentiment_server.log

# Check status
curl http://localhost:8000/telegram/status

# Server metrics include listener stats
curl http://localhost:8000/health
```

### Standalone Mode

```bash
# Check listener logs
tail -f telegram_listener.log

# Check listener process
ps aux | grep telegram_listener

# Check database
sqlite3 sentiment.db "SELECT COUNT(*) FROM telegram_messages WHERE processed = 0"

# Server status (listener not shown)
curl http://localhost:8000/health
curl http://localhost:8000/telegram/status  # Shows integrated=false
```

## Troubleshooting

### Integrated Mode Issues

**Problem:** Server won't start with "Telegram session not authorized"

**Solution:**
```bash
# Disable integration temporarily
export SENTIMENT_TELEGRAM_LISTENER_ENABLED=false
uvicorn main:app

# Authenticate in separate terminal
python3 telegram_listener.py  # Ctrl+C after auth completes

# Re-enable integration
export SENTIMENT_TELEGRAM_LISTENER_ENABLED=true
uvicorn main:app --reload
```

**Problem:** Server logs "Telegram listener failed to start"

**Solution:** Check `sentiment_server.log` for details, usually missing credentials or session file.

### Standalone Mode Issues

**Problem:** Listener process not found

**Solution:**
```bash
# Check if running
ps aux | grep telegram_listener

# Start if not running
cd sentiment
python3 telegram_listener.py &

# Or use systemd/supervisor
sudo systemctl start telegram-listener
```

**Problem:** Messages not being processed

**Solution:**
```bash
# Check unprocessed messages
sqlite3 sentiment.db "SELECT COUNT(*) FROM telegram_messages WHERE processed = 0"

# If high count, check sentiment server is running and processing
tail -f sentiment_server.log | grep telegram
```

## Performance Comparison

| Metric | Integrated | Standalone |
|--------|-----------|------------|
| Memory | Shared (~500MB total) | Isolated (~300MB + 200MB) |
| CPU | Shared | Isolated |
| Reliability | Single point of failure | Independent |
| Startup time | +2-3 seconds | Immediate (already running) |
| Message loss on restart | Yes (brief) | No |
| Deployment complexity | Simple | Medium |

## Migration

### From Standalone to Integrated

```bash
# Stop standalone listener
killall -9 python3 telegram_listener.py
# Or: sudo systemctl stop telegram-listener

# Enable integration
export SENTIMENT_TELEGRAM_LISTENER_ENABLED=true

# Start server (listener auto-starts)
uvicorn main:app --reload
```

### From Integrated to Standalone

```bash
# Stop server
# Ctrl+C or: kill $(pgrep -f "uvicorn main:app")

# Disable integration
export SENTIMENT_TELEGRAM_LISTENER_ENABLED=false

# Start standalone listener
python3 telegram_listener.py &

# Start server
uvicorn main:app --reload
```

## Summary

**For Development:** Use integrated mode (simple, fast iteration)  
**For Production:** Use standalone service (reliable, scalable)

Both modes share the same database, so switching is seamless.
