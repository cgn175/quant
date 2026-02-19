<p align="center">
  <img src="https://raw.githubusercontent.com/cgn175/quant-bot/main/assets/logo.png" alt="Quant Bot Logo" width="200"/>
</p>

# Quant Bot

[![Go Report Card](https://goreportcard.com/badge/github.com/cgn175/quant-bot)](https://goreportcard.com/report/github.com/cgn175/quant-bot)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Docker Image](https://img.shields.io/docker/pulls/cgn175/quant-bot.svg)](https://hub.docker.com/r/cgn175/quant-bot)

**Quant Bot** is a high-performance, modular crypto trading bot written in Go. Inspired by [Hummingbot](https://hummingbot.org)'s architecture but built for specific high-frequency and trend-following capabilities, it allows users to run automated trading strategies including Market Making, Trend Following, and ML-enhanced signals on centralized exchanges like Binance.

## 📚 Table of Contents
- [Features](#features)
- [Strategies](#strategies)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Architecture](#architecture)
- [Disclaimer](#disclaimer)

## ✨ Features
- **Multi-Strategy Support**: Run pure Market Making, Trend Following (Plan D), or ML-based strategies.
- **Exchange Agnostic**: Core interface allows easy integration of new exchanges (currently supports Binance Spot/Futures).
- **Paper Trading**: Built-in paper exchange for safe testing of strategies without real funds.
- **Risk Management**: Configurable risk engine with daily loss caps, max drawdown protection, and position sizing.
- **ML Integration**: Optional Python microservice for ONNX-based market regime classification and volatility prediction.
- **Telegram Alerts**: Real-time notifications for trades, order fills, and risk events.

## 🤖 Strategies / Agents

See [AGENTS.md](AGENTS.md) for detailed personalities and configurations.

### 1. Market Making (`market_making`)
Advanced inventory-aware market making.
- **Inventory Skew**: Shifts quotes to offload inventory risk (Avellaneda-Stoikov).
- **Dynamic Spreads**: Widens spreads in high volatility.
- **Configuration**: See `config.example.mm.yaml`.

### 2. Trend Following (`trend_following`)
Plan D trend following system.
- **Aggressive Limit Orders**: Tries to enter at best price, minimizing fees.
- **Trailing Stop**: Chandelier Exit to lock in profits.
- **Configuration**: See `config.example.trend.yaml`.

### 3. Funding Arbitrage (`funding_arb`)
Delta-neutral yield farming.
- **Logic**: Shorts Perps when funding is high to collect carry.
- **Auto-Exit**: Closes when funding normalizes.
- **Configuration**: See `config.example.funding.yaml`.

### 4. ML-Enhanced (`ml`)
Uses external Python inference service for regime classification.

## 🚀 Installation

### Using Docker (Recommended)
```bash
docker run -d --name quant-bot \
  -v $(pwd)/config.yaml:/app/config.yaml \
  -v $(pwd)/data:/app/data \
  cgn175/quant-bot:latest
```

### From Source
**Prerequisites:** Go 1.21+

1. Clone the repository:
   ```bash
   git clone https://github.com/cgn175/quant-bot.git
   cd quant-bot
   ```
2. Build the binary:
   ```bash
   go build -o bot ./cmd/bot
   ```

## ⚙️ Configuration
Copy the example config and edit it:
```bash
cp config.yaml.example config.yaml
```

Key configuration sections:
- **Exchange**: API keys and environment (Testnet/Mainnet).
- **Strategy**: Select `type` (`market_making` or `trend_following`) and tune parameters.
- **Risk**: Set `max_daily_loss_pct`, `max_risk_per_trade_pct`.
- **Execution**: Enable `use_limit_orders` for Maker strategies.

See `config.example.mm.yaml` for a Market Making configuration example.

## 🖥️ Usage

**Run in Paper Mode (Default):**
```bash
./bot --config config.yaml
```

**Run in Live Mode:**
Set `mode: live` in `config.yaml` or pass as env var `QUANT_MODE=live`.
```bash
./bot --config config.yaml
```

### Validation Scripts

**Momentum Filter Validation**:
```bash
# Check momentum rankings and filter status
python3 scripts/validate_momentum.py
```

**Cross-Exchange Arbitrage Validation**:
```bash
# Check funding rate spreads across exchanges
python3 scripts/validate_cross_exchange.py
```

**Paper Trading Validation**:
```bash
# Analyze paper trading results
python3 scripts/validate_paper_trading.py --log logs/bot.log
```

### Strategy Comparison
Compare performance across multiple strategies:
```bash
python3 compare_strategies.py
```
Generates a consolidated report of Win Rate, PnL, and Sharpe Ratio.

### Bot Commands
The bot supports a Telegram interface for management:
- `/status`: View current PnL, open positions, and equity.
- `/stop`: Gracefully stop the bot (cancel open orders, close positions if configured).

## 📚 Architecture
Quant Bot follows a Clean Architecture / Hexagonal pattern:
- **Domain**: Core entities (`Order`, `Trade`, `Candle`) and interfaces (`Exchange`, `Executor`).
- **Application**: Strategy logic and Risk Management.
- **Infrastructure**: Concrete implementations for Binance, SQLite, Telegram, etc.

This separation allows for easy unit testing and swapping of components (e.g., switching from Binance to Hyperliquid).

## ⚠️ Disclaimer
This software is for educational purposes only. Do not risk money which you are afraid to lose. USE THE SOFTWARE AT YOUR OWN RISK. THE AUTHORS AND ALL AFFILIATES ASSUME NO RESPONSIBILITY FOR YOUR TRADING RESULTS.
