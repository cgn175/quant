# Quant Bot 🤖📈

A production-ready crypto scalping bot targeting major CEX pairs (BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT) with a 10-20% annual return target.

## Overview

The system combines:
- **Go trading engine** for low-latency execution
- **XGBoost/ONNX model** for price direction prediction
- **Sentiment analysis** (Twitter, Reddit, news) as a regime filter
- **Risk management** with position sizing, leverage limits, and daily loss caps

```
┌─────────────────────────────────────────────────────────────────┐
│                         QUANT BOT                               │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │ Exchange │───▶│ Features │───▶│  Model   │───▶│ Strategy │  │
│  │   WS     │    │  Builder │    │ Predict  │    │  Signal  │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│       │                │                              │         │
│       │          ┌─────┴─────┐                        ▼         │
│       │          │ Sentiment │              ┌──────────────┐    │
│       │          │  Service  │              │    Risk      │    │
│       │          └───────────┘              │   Manager    │    │
│       │                                     └──────────────┘    │
│       │                                            │            │
│       ▼                                            ▼            │
│  ┌──────────┐                              ┌──────────────┐     │
│  │  Data    │                              │  Execution   │     │
│  │  Store   │                              │   Engine     │     │
│  └──────────┘                              └──────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

## Features

- **Multi-symbol trading** with parallel WebSocket streams (multiplexed)
- **Real-time sentiment** from Twitter, Reddit, crypto news via FinBERT NLP
- **XGBoost predictions** for UP/DOWN/NEUTRAL with configurable thresholds
- **Risk controls**: per-trade limits, daily loss caps, total leverage limits
- **Paper & live modes** with identical strategy logic
- **Backtesting engine** with full metrics (Sharpe, drawdown, profit factor)
- **Prometheus metrics** + **Telegram alerts**

## Project Structure

```
quant/
├── cmd/
│   └── bot/                 # Main binary entry point
├── internal/
│   ├── alerts/              # Telegram notifications
│   ├── backtest/            # Offline backtester + reporter
│   ├── config/              # Config loading (viper)
│   ├── data/                # OHLCV candle storage
│   ├── exchange/            # Binance WebSocket client
│   ├── execution/           # Order execution (paper/live)
│   ├── features/            # TA indicators + feature builder
│   ├── metrics/             # Prometheus metrics
│   ├── model/               # ONNX model inference
│   ├── risk/                # Position sizing + risk limits
│   ├── sentiment/           # Sentiment service client
│   └── strategy/            # Signal generation + filters
├── models/                  # Trained ONNX models
├── scripts/                 # Python training scripts
├── sentiment/               # Python sentiment microservice
│   ├── fetchers/            # Twitter, Reddit, news fetchers
│   ├── models/              # FinBERT analyzer
│   ├── main.py              # FastAPI application
│   └── Dockerfile
├── config.yaml              # Bot configuration
├── docker-compose.yaml      # Full stack deployment
└── Dockerfile.bot           # Go bot container
```

## Technology Stack

### Go Bot
| Component | Library |
|-----------|---------|
| WebSocket | `gorilla/websocket` |
| Config | `spf13/viper` + `spf13/cobra` |
| Logging | `rs/zerolog` |
| ML Inference | `onnxruntime-go` |
| Metrics | `prometheus/client_golang` |
| Alerts | `go-telegram-bot-api` |

### Python Sentiment Service
| Component | Library |
|-----------|---------|
| API | FastAPI |
| NLP | Transformers (FinBERT) |
| Twitter | tweepy |
| Reddit | praw |

## Quick Start

### 1. Clone and Build

```bash
git clone https://github.com/yourusername/quant-bot.git
cd quant-bot

# Build Go bot
go build -o bin/bot ./cmd/bot

# Install Python dependencies
cd sentiment && pip install -r requirements.txt && cd ..
```

### 2. Configure

Edit `config.yaml`:

```yaml
mode: paper  # or "live"

exchange:
  name: binance
  testnet: false
  api_key: "your-api-key"
  api_secret: "your-api-secret"

symbols:
  - BTCUSDT
  - ETHUSDT

risk:
  max_risk_per_trade_pct: 1.0
  max_daily_loss_pct: 3.0
  max_open_positions: 3
  max_leverage: 2.0

model:
  path: models/xgboost_model.onnx
  threshold_up: 0.6
  threshold_down: 0.6

alerts:
  telegram_bot_token: "your-bot-token"
  telegram_chat_id: 123456789
```

### 3. Run with Docker Compose

```bash
# Set environment variables
export EXCHANGE_API_KEY="your-key"
export EXCHANGE_API_SECRET="your-secret"
export REDDIT_CLIENT_ID="your-reddit-id"
export REDDIT_CLIENT_SECRET="your-reddit-secret"

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f bot
```

### 4. Run Locally (Development)

```bash
# Terminal 1: Start sentiment service
cd sentiment
uvicorn main:app --host 0.0.0.0 --port 8000

# Terminal 2: Start bot
./bin/bot --config config.yaml
```

## Trading Workflow

```mermaid
flowchart LR
    A[Market Data] --> B[Feature Builder]
    B --> C{XGBoost Model}
    C -->|P(UP) > 0.6| D[Long Signal]
    C -->|P(DOWN) > 0.6| E[Short Signal]
    D --> F{Sentiment Filter}
    E --> F
    F -->|Pass| G{Risk Check}
    F -->|Fail| H[Skip Trade]
    G -->|Pass| I[Execute Order]
    G -->|Fail| H
    I --> J[Monitor TP/SL]
```

### Signal Generation
1. **Feature extraction**: EMAs, RSI, Bollinger Bands, MACD, volume ratios
2. **Model prediction**: XGBoost outputs `[P(down), P(neutral), P(up)]`
3. **Sentiment filter**: Skip shorts if sentiment > 0.6, reduce size 50% if extreme
4. **Risk validation**: Check leverage, daily loss, open positions

### Position Management
- **Entry**: Market or limit orders based on config
- **Exit**: Automatic stop-loss and take-profit triggers
- **Sizing**: `size = (equity × risk%) / (price × stop_distance%)`

## Monitoring

### Prometheus Metrics (`:9090/metrics`)
- `quant_equity` - Current account equity
- `quant_daily_pnl` - Daily realized PnL
- `quant_win_rate` - Rolling win rate
- `quant_open_positions` - Number of open positions
- `quant_model_inference_seconds` - Model latency histogram

### Telegram Alerts
- Trade opened/closed with PnL
- Daily summary
- Daily loss limit breach
- Sentiment regime changes
- Bot start/stop events

## Backtesting

```bash
# Run backtest
./bin/bot --mode backtest --config config.yaml

# Output includes:
# - Summary: equity curve, Sharpe, max drawdown
# - Trade log: entry/exit prices, PnL, reasons
# - Monthly returns
# - Per-symbol statistics
```

## Configuration Reference

| Section | Key | Description | Default |
|---------|-----|-------------|---------|
| `mode` | - | `paper` or `live` | `paper` |
| `exchange.testnet` | - | Use testnet APIs | `false` |
| `symbols` | - | Trading pairs | `[BTCUSDT, ETHUSDT]` |
| `bar_size` | - | Candle interval | `1m` |
| `risk.max_risk_per_trade_pct` | - | Max risk per trade | `1.0` |
| `risk.max_daily_loss_pct` | - | Daily loss limit | `3.0` |
| `risk.max_leverage` | - | Total account leverage | `2.0` |
| `model.threshold_up` | - | Min P(up) for long | `0.6` |
| `sentiment.sentiment_threshold_long` | - | Min sentiment for longs | `0.3` |

## Development

```bash
# Run tests
go test ./...

# Build for production
go build -ldflags="-s -w" -o bin/bot ./cmd/bot

# Train new model
python scripts/train_model.py --symbols BTCUSDT,ETHUSDT --days 180
python scripts/export_model.py --format onnx
```

## Risk Disclaimer

⚠️ **This software is for educational purposes only.** Trading cryptocurrencies involves substantial risk of loss. Past performance does not guarantee future results. Never trade with money you cannot afford to lose.

## License

MIT License - see [LICENSE](LICENSE) for details.
