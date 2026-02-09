# Quant Bot 🤖📈

A crypto **trend-following trading bot** targeting BTCUSDT, ETHUSDT, SOLUSDT, and BNBUSDT on Binance using 4H candles. It is currently configured for **paper trading**.

## Overview

The system consists of:
- **Go trading engine** for live/paper execution, strategy logic, risk management, and backtesting
- **Python ML microservice** for:
  - **Regime classification** (“Traffic Light”) — when it is safe to trade
  - **Volatility prediction** — used to size dynamic stop-losses
- **(Optional) Sentiment microservice** (FastAPI + FinBERT) for news/social sentiment

Core strategy is **Plan D — Pure Trend Following**:
- Donchian breakout + EMA(9/21) crossover + EMA(50) trend filter
- Volume and “dead market” filters (Bollinger band squeeze, candle color, etc.)
- Optional ML-based regime filter and dynamic stop-loss width
- Strict risk management with ATR/dynamic stops, trailing exits, partial profit-taking, and daily loss caps

### Runtime workflow (high level)

- Ingest 4H candles from Binance (via REST/WS) and persist to SQLite.
- On each new candle, build features and evaluate **Plan D** trend rules.
- Optionally call the **ML server** for regime and volatility predictions.
- Apply risk rules (position sizing, daily loss caps, max positions/correlation) and execute via paper or live engine.
- Continuously update trailing stops, partial exits, metrics, and Telegram alerts.

```
┌─────────────────────────────────────────────────────────────────┐
│                         QUANT BOT                               │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────┐    ┌──────────┐    ┌──────────────┐   ┌────────┐ │
│  │ Exchange │───▶│ Features │───▶│  Plan D      │──▶│  Risk  │ │
│  │  WS/REST │    │  Builder │    │  Strategy    │   │ Manager│ │
│  └──────────┘    └──────────┘    └──────────────┘   └────────┘ │
│       │                │             ▲   ▲               │      │
│       │                │             │   │               ▼      │
│       │          ┌─────┴─────┐  ┌────┴──────┐   ┌────────────┐  │
│       │          │  ML Regime│  │ ML Vol    │   │ Execution  │  │
│       │          │ /predict_ │  │ /predict_ │   │  Engine    │  │
│       │          │  regime   │  │ volatility│   └────────────┘  │
│       │          └───────────┘  └───────────┘          │        │
│       ▼                                                ▼        │
│  ┌──────────┐                                   ┌──────────────┐│
│  │  Data    │                                   │ Metrics/     ││
│  │  Store   │                                   │ Alerts       ││
│  └──────────┘                                   └──────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

## Features

- **4H trend-following strategy** (“Plan D”) with Donchian breakout + EMA confirmations + volume/volatility filters
- **Optional ML regime filter** (RandomForest “Traffic Light”) to avoid DANGER_ZONE conditions
- **Optional dynamic stop-loss** based on predicted next-candle range
- **Strict risk controls**: per-trade risk, daily loss cap, max open positions, sector correlation guard
- **Paper & live modes** with the same strategy logic (default is paper)
- **Backtesting engine** with detailed metrics (PnL, Sharpe, drawdown, R-multiples)
- **Prometheus metrics** and **Telegram alerts** for monitoring

## Project Structure

```text
quant/
├── cmd/                                # Go binary entry points
│   ├── bot/                            # Main bot binary
│   ├── backtest/                       # Standalone backtester
│   ├── analyze_predictions/            # Prediction analysis tool
│   └── test_model/                     # Model testing tool
│
├── internal/                           # Go core packages
│   ├── config/                         # Config structs + viper loading
│   ├── strategy/                       # Plan D trend logic, features, tests
│   ├── mlfilter/                       # HTTP client for ML microservice
│   ├── exchange/                       # Binance REST + WebSocket client
│   ├── data/                           # SQLite candle store + funding cache
│   ├── features/                       # TA indicators + feature builders
│   ├── execution/                      # Paper/live execution engines
│   ├── risk/                           # Position sizing + risk limits
│   ├── backtest/                       # Offline backtester
│   ├── metrics/                        # Prometheus metrics
│   ├── alerts/                         # Telegram notifications
│   ├── model/                          # Legacy XGBoost/ONNX inference (disabled)
│   └── sentiment/                      # Legacy sentiment microservice client
│
├── ml/                                 # Python ML training & inference
│   ├── server.py                       # HTTP server: /predict_regime, /predict_volatility
│   ├── regime/                         # Regime classifier (Traffic Light)
│   ├── volatility/                     # Volatility predictor (Dynamic Stop-Loss)
│   └── models/                         # Saved model files
│
├── scripts/                            # Research & utility scripts (Python)
├── sentiment/                          # Optional sentiment microservice (FastAPI + FinBERT)
├── data/                               # Runtime data (SQLite candles, training DB)
├── docs/                               # Design & analysis docs
├── config.yaml                         # Active configuration
├── docker-compose.yaml                 # Bot + ML server (+ sentiment) stack
└── Dockerfile.bot                      # Go bot container
```

## Technology Stack

### Go trading bot

| Component  | Library                    |
|-----------|----------------------------|
| Config    | `spf13/viper`, `spf13/cobra` |
| Logging   | `rs/zerolog`               |
| Exchange  | Custom Binance client (REST + WS) |
| Metrics   | `prometheus/client_golang` |
| Alerts    | `go-telegram-bot-api`      |

### Python ML microservice

| Component | Library / Tool |
|----------|-----------------|
| API      | FastAPI / Uvicorn |
| Models   | scikit-learn (RandomForest, Huber/Ridge, etc.) |
| Data     | pandas, numpy   |

### Sentiment service (optional)

| Component | Library |
|----------|---------|
| API      | FastAPI |
| NLP      | Transformers (FinBERT) |
| Twitter  | tweepy |
| Reddit   | praw |

## Quick Start

### 1. Clone and build

```bash
git clone https://github.com/yourusername/quant-bot.git
cd quant-bot

# Build Go bot
go build -o bin/bot ./cmd/bot
```

### 2. Configure

Edit `config.yaml` (key sections only shown here):

```yaml
mode: paper  # NEVER set to "live" unless you know what you're doing

exchange:
  name: binance
  testnet: false
  api_key: "your-api-key"
  api_secret: "your-api-secret"

symbols:
  - BTCUSDT
  - ETHUSDT
  - SOLUSDT
  - BNBUSDT

strategy:
  type: trend_following
  regime_filter:
    enabled: false     # true to use ML Traffic Light
  dynamic_stop:
    enabled: false     # true to use ML volatility-based stops
  ml_filter:
    enabled: false     # legacy directional model (keep disabled)

risk:
  max_risk_per_trade_pct: 1.0
  max_daily_loss_pct: 3.0
  max_open_positions: 4
```

### 3. Run the ML server (recommended)

```bash
# From repo root
python3 ml/server.py --models-dir ml/models
```

### 4. Run the bot

```bash
# Paper trading on 4H candles
./bin/bot -c config.yaml
```

### 5. (Optional) Docker Compose

```bash
# Start bot + ML server (+ optional sentiment)
docker-compose up -d

# View bot logs
docker-compose logs -f bot
```

## Trading Workflow

```mermaid
flowchart LR
    A[4H Market Data] --> B[Feature Builder]
    B --> C[Plan D Trend Rules]
    C --> D{ML Regime Filter?}
    D -->|Disabled or SAFE| E{ML Volatility?}
    D -->|DANGER_ZONE| H[Skip Trade]
    E -->|Disabled| F[ATR-based Stop/Size]
    E -->|Enabled| G[Dynamic Stop/Size]
    F --> I{Risk Check}
    G --> I
    I -->|Pass| J[Execute Order (paper/live)]
    I -->|Fail| H
    J --> K[Trailing Stop & Partials]
```

### Signal generation

1. **Feature extraction**: Donchian channels, EMA(9/21/50), ATR, RSI, Bollinger Bands, volume ratios, funding rates, time-of-day features, etc.
2. **Plan D rules**: mechanical breakout + trend confirmation + volume/whipsaw defenses (no directional ML prediction).
3. **Optional ML filters**:
   - Regime classifier decides if conditions are SAFE_TO_TRADE.
   - Volatility model predicts next-candle range to set dynamic stop width.
4. **Risk validation**: per-trade risk, daily loss cap, max open positions, sector correlation checks.

### Position management

- **Entry**: Orders sized by risk, with initial ATR/dynamic stop and profit targets.
- **Exit**: Chandelier-style trailing stops with partial exits at multiple R-multiples.
- **Sizing**: `size = (equity × risk_pct) / (entry_price × stop_distance_pct)`.

## Monitoring

### Prometheus metrics

Examples (names may vary slightly):
- `quant_equity` — current account equity
- `quant_daily_pnl` — daily realized PnL
- `quant_open_positions` — number of open positions
- `quant_strategy_trades_total` — trades by symbol/direction

### Telegram alerts

- Bot start/stop
- Trade opened/closed with PnL and R-multiple
- Daily PnL summary and loss cap breaches
- (Optional) regime changes and ML/server health

## Backtesting

```bash
# Go backtester
go build -o backtest ./cmd/backtest
./backtest -c config.yaml

# Python-side research backtest
python3 scripts/backtest_trend.py
```

Outputs typically include:
- Equity curve, Sharpe ratio, max drawdown
- Per-symbol stats and R-distribution
- Regime and volatility behavior vs outcomes

## Configuration Reference (selected)

| Section                     | Key                          | Description                                   | Example |
|----------------------------|------------------------------|-----------------------------------------------|---------|
| `mode`                     | -                            | `paper` or `live`                             | `paper` |
| `symbols`                  | -                            | Trading pairs                                 | `[BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT]` |
| `strategy.type`            | -                            | Active strategy type                          | `trend_following` |
| `strategy.regime_filter`   | `enabled`                    | Use ML Traffic Light filter                   | `false` |
| `strategy.dynamic_stop`    | `enabled`                    | Use ML volatility-based stops                 | `false` |
| `strategy.ml_filter`       | `enabled`                    | Legacy directional ML (keep `false`)          | `false` |
| `risk.max_risk_per_trade_pct` | -                         | Max risk per trade (% of equity)             | `1.0` |
| `risk.max_daily_loss_pct`  | -                            | Daily loss cap (% of equity)                  | `3.0` |
| `risk.max_open_positions`  | -                            | Max simultaneous positions                     | `4` |

## Development

```bash
# Go: build & test
go build ./...
go test ./...

# Python ML: train models
python3 ml/regime/train_regime.py
python3 ml/volatility/train_volatility.py

# Start ML server
python3 ml/server.py --models-dir ml/models
```

## Risk Disclaimer

⚠️ **This software is for educational purposes only.** Trading cryptocurrencies involves substantial risk of loss. Past performance does not guarantee future results. Never trade with money you cannot afford to lose.

## License

MIT License — see `LICENSE` for details.
