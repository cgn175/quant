# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a crypto scalping bot targeting major CEX pairs (BTC/USDT, ETH/USDT, ETH/BTC, SOL/USDT, BNB/USDT) with a 10-20% annual return target. The system uses Go for the live trading engine, XGBoost (trained in Python) for signals, and social/news sentiment as a regime filter.

## System Architecture

The bot consists of two main services:

1. **Go Trading Bot** (main bot)
   - Data ingestion from Binance/Bybit (1m/5m OHLCV, orderbook, trades)
   - Feature engineering (TA indicators, sentiment integration)
   - XGBoost model inference
   - Signal generation with sentiment filters
   - Execution engine with OCO TP/SL orders
   - Risk management (1-2% per trade, max daily loss caps)
   - Backtesting engine
   - Monitoring and alerts

2. **Python Sentiment Microservice**
   - Ingests X/Twitter, Reddit (r/CryptoCurrency, r/Bitcoin), crypto news
   - Runs NLP (FinBERT) every 1-5 minutes
   - Exposes REST API (`GET /sentiment/{symbol}`) or Redis cache
   - Returns sentiment scores (1h/24h aggregates, mentions, velocity)

## Code Structure

```
/cmd/bot               # Main binary entry point
/internal
  /config              # Config loading (viper)
  /exchange            # Exchange clients (REST + WebSocket)
  /data                # OHLCV persistence (Postgres or embedded DB)
  /features            # TA calculations, feature vectors
  /sentiment           # Client for sentiment microservice
  /model               # XGBoost/ONNX inference
  /strategy            # Signal logic + sentiment filters
  /execution           # Order placement, position management
  /risk                # Risk limits, position sizing
  /metrics             # Prometheus metrics
  /alerts              # Telegram integration
  /backtest            # Offline backtester
```

## Key Technologies

**Go Stack:**
- Exchange: `gocryptotrader` or custom Binance/Bybit client
- Config: `spf13/viper` + `spf13/cobra`
- Logging: `uber-go/zap` or `rs/zerolog`
- TA: `go-talib` or `ta4go`
- DB: `pgx` (Postgres) or `bbolt`/`badger` (embedded)
- ML: XGBoost C-API bindings or `onnxruntime-go`
- Monitoring: `prometheus/client_golang`
- Alerts: `go-telegram-bot-api`

**Python Stack:**
- Sentiment: `tweepy`, `praw`, `transformers` (FinBERT)
- API: `fastapi` or `flask`
- Data: `ccxt`, `pandas`, `numpy`
- ML: `xgboost`, `optuna`/`skopt`

## Development Commands

**Go Bot:**
```bash
# Initialize module (first time)
go mod init github.com/yourusername/quant-bot

# Build
go build -o bin/bot ./cmd/bot

# Run (live/paper mode via config)
./bin/bot --config config.yaml

# Run tests
go test ./...

# Run specific test
go test -v -run TestStrategyLogic ./internal/strategy

# Backtest mode
./bin/bot --mode backtest --config config.yaml
```

**Python Sentiment Service:**
```bash
# Install dependencies
pip install -r requirements.txt

# Run service
uvicorn sentiment.main:app --host 0.0.0.0 --port 8000

# Docker build
docker build -t sentiment-service .

# Run container
docker run -p 8000:8000 sentiment-service
```

**Full Stack:**
```bash
# Docker Compose (both services)
docker-compose up -d

# View logs
docker-compose logs -f bot
docker-compose logs -f sentiment
```

**Model Training:**
```bash
# Fetch historical data and train XGBoost
python scripts/train_model.py --symbols BTCUSDT,ETHUSDT --days 180

# Export model
python scripts/export_model.py --format onnx
```

## Configuration (`config.yaml`)

Critical config sections:
- **Exchanges:** API keys, symbols, bar size
- **Sentiment service:** URL, poll interval, long/short thresholds
- **Risk:** `max_risk_per_trade_pct`, `max_daily_loss_pct`, `max_open_positions`
- **XGBoost:** `model_path`, probability thresholds for UP/DOWN/NEUTRAL
- **Execution:** `use_limit_orders`, `slippage_bp`

## Features & Signals

**Price Features:**
- OHLC, log returns (1m, 5m)
- EMAs: 5, 9, 21, 50
- RSI: 7, 14
- Bollinger bands (20, 2)
- MACD (12, 26, 9)
- Volume ratios

**Sentiment Features:**
- `sentiment_score_1h`, `sentiment_score_24h`
- `mentions_zscore`
- `sentiment_velocity`

**Signal Logic:**
- XGBoost predicts `[p_down, p_neutral, p_up]`
- Long entry: `p_up > threshold` AND `sentiment_score_1h > 0.3` AND volume filters pass
- Short entry: disabled if `sentiment_score > threshold_pos`
- Size reduction: 50% if `|sentiment_24h| > 0.8` (extreme volatility)

## Core Goroutines

- `marketDataLoop` (per symbol): Subscribe to candles/orderbook, persist data
- `sentimentLoop`: Poll sentiment service every 1 min, cache scores
- `signalLoop` (per symbol): Compute features, call model, emit signals
- `strategyLoop`: Apply risk + sentiment filters, generate orders
- `executionLoop`: Place/manage orders, track positions

## Risk Management

- Risk per trade: 0.5-1.0% of equity
- Max daily loss: 3-5% (auto-shutdown)
- Position sizing: `size = (equity * risk_pct) / (entry_price * stop_distance_pct)`
- No averaging down
- Max leverage: 2-3x (if futures)
- Sentiment risk: skip trades if extreme sentiment detected

## Testing Strategy

**Backtesting:**
- Load historical OHLCV + sentiment data
- Replay bar-by-bar with same strategy/risk logic as live
- Simulate fills with fees (0.02-0.1%) and slippage
- Metrics: PnL, win rate, profit factor, Sharpe, max drawdown, sentiment correlation

**Paper Trading:**
- Run 2-4 weeks with live data but simulated orders
- Validate sentiment integration and filters
- Monitor latency, order RTT, model inference time

## Monitoring & Alerts

**Prometheus Metrics:**
- Equity curve, open positions, daily PnL
- Win rate, max drawdown
- WS latency, order RTT
- Sentiment score per symbol, API latency

**Telegram Alerts:**
- Bot start/stop
- Trade opened/closed
- Daily PnL summary
- Drawdown breach
- Sentiment regime changes

## Implementation Phases

1. **Skeleton & Exchange Connectivity:** Config, exchange clients, stream candles
2. **Sentiment Microservice:** FastAPI service, FinBERT, sentiment endpoint
3. **Data Storage & Features:** OHLCV persistence, TA indicators, sentiment client
4. **Python Research & Model:** Historical data, feature engineering, XGBoost training
5. **Model Integration:** Load model in Go, inference in `signalLoop`
6. **Strategy & Execution:** Signal rules, risk module, order placement
7. **Backtest Engine:** Offline backtester with metrics
8. **Monitoring & Hardening:** Prometheus, Telegram, error recovery
9. **Live Rollout:** Paper trading, then small capital

## Important Constraints

- **Prediction Horizon:** 1 bar ahead (next minute)
- **Labels:** UP if `(close_{t+1} - close_t) / close_t > threshold`, DOWN if negative, else NEUTRAL
- **No Look-Ahead Bias:** Features at time `t` must use only data up to `t`
- **Sentiment Latency:** Poll every 1 min, cache locally to avoid delays in signal generation
- **Time-Series Split:** Train/validation split by time, never shuffle
- **Model Format:** XGBoost native (`.json`/`.ubj`) or ONNX for portability

## Deployment

- **Target:** VPS or Proxmox VM (2 vCPU, 2-4 GB RAM, 30+ GB SSD)
- **Docker Compose:** `bot` (Go), `sentiment` (Python), optional `redis`, `postgres`
- **Systemd:** Service files with health checks and auto-restart
- **Secrets:** Store API keys in env vars or secure vault, never commit to repo
