# Agent Instructions

## Project Overview

**Multi-strategy crypto trading bot** targeting BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT on Binance. Currently in **paper trading mode**.

**Two primary services:**
1. **Go Trading Bot** — live/paper execution, strategy, risk management, backtesting
2. **Python ML Microservice** — model training & HTTP inference server (port 9001) for regime and volatility predictions

**Available Strategies:**

1. **"Plan D" — Pure Trend Following** (4H candles, mechanical rules, no directional ML):
   - **Layer 1 — Entry signals:** Donchian breakout + EMA(9/21) crossover confirmation + EMA(50) trend + volume confirmation + whipsaw defense (candle color + BB dead market filter)
   - **Layer 2 — Regime filters:** Regime Classifier OR legacy ML OR ADX > 20, volatility (ATR ratio), funding rate filter, OI z-score filter
   - **Layer 3 — Risk management:** ATR-based initial stops (or Dynamic Stop-Loss), Chandelier trailing exit (dynamic ATR multiplier tightening by R-multiple), partial exits at 3R and 6R, daily loss cap, sector correlation guard

2. **Funding Rate Arbitrage** (delta-neutral carry):
   - Entry: When funding rate exceeds threshold (e.g., 0.05% per 8h)
   - Position: SHORT perp + LONG spot (delta-neutral hedge) OR SHORT perp only
   - Exit: Funding normalizes, flips against us, or max loss breach
   - Target: 15-30% APY from funding payments

3. **Perpetual Basis Trade** (cash-and-carry):
   - Entry: When annualized basis (perp premium over spot) exceeds threshold (e.g., 15%)
   - Position: LONG spot + SHORT perp (delta-neutral)
   - Exit: Basis converges below threshold
   - Target: Capture basis convergence + funding payments

4. **Market Making** (pure liquidity provision):
   - Place bid/ask orders around mid-price with dynamic spread (volatility-adjusted)
   - Inventory risk management via Avellaneda-Stoikov skewing
   - Target: Earn spread, not directional profit

**ML Status:** The v1 XGBoost directional model is **disabled** (severely overfit: Train AUC 0.96 vs Test AUC 0.57). Two new anti-overfit models have been built to replace it:
- **Regime Classifier (Traffic Light):** RandomForest that learns WHEN to trade (SAFE_TO_TRADE vs DANGER_ZONE) based on entry outcomes. 6 features, max_depth=4. Replaces ADX > 20 rule.
- **Volatility Predictor (Dynamic Stop-Loss):** HuberRegressor/Ridge that predicts next-candle range %. Used to set dynamic stop-loss width instead of fixed ATR multiplier.

See `docs/ML_MODEL_ANALYSIS.md` for the full v1 failure analysis.

### Runtime Workflow (high level)

- **Market data ingestion:** Binance WS/REST → 4H candles → SQLite + in-memory buffers.
- **Feature & signal generation:** On each new candle, compute TA/features and evaluate Plan D trend rules (Donchian breakout + EMA confirmations + volume/whipsaw filters).
- **Optional ML filters:** Call `ml/server.py` for `/predict_regime` and `/predict_volatility` to gate entries and size dynamic stops.
- **Risk & execution:** Apply risk limits (per-trade risk, daily loss cap, max positions, correlation) and route orders via paper/live engines.
- **Lifecycle management:** Update trailing stops and partial exits, emit Prometheus metrics, and send Telegram alerts.

---

## Codebase Structure

```
quant/
├── cmd/                                # Go binary entry points
│   ├── bot/main.go                     # Main bot — config wiring, goroutine orchestration
│   ├── backtest/                       # Standalone backtester binary
│   ├── analyze_predictions/            # Prediction analysis tool
│   └── test_model/                     # Model testing tool
│
├── internal/                           # Go core packages (not importable externally)
│   ├── config/config.go                # Config structs + viper loading + validation
│   ├── strategy/                       # ** THE BRAIN — all trading logic lives here **
│   │   ├── trend.go                    # TrendStrategy: OnBar(), trailing stops, partials, position mgmt
│   │   ├── trend_regime_features.go    # BuildRegimeFeatures() — 6 features for Traffic Light
│   │   ├── trend_vol_features.go       # BuildVolatilityFeatures() — 6 features for Dynamic Stop
│   │   ├── trend_ml_features.go        # BuildMLFeatures() — 19 features for legacy v1 (disabled)
│   │   ├── signal.go                   # Signal types, legacy Evaluate() for old ML strategy
│   │   ├── trend_test.go              # Strategy unit tests
│   │   ├── funding_arb/                # Funding rate arbitrage strategy
│   │   │   └── strategy.go             # FundingArbStrategy: scan funding rates, open/close delta-neutral positions
│   │   ├── basis_trade/                # Perpetual basis trade strategy
│   │   │   └── strategy.go             # BasisTradeStrategy: monitor basis, open/close spot+perp pairs
│   │   └── market_making/              # Pure market making strategy
│   │       └── strategy.go             # MarketMakingStrategy: bid/ask spread, inventory management
│   ├── mlfilter/                       # ML inference HTTP client
│   │   ├── client.go                   # Predict(), PredictRegime(), PredictVolatility()
│   │   └── circuit_breaker.go          # Circuit breaker for ML service failures
│   ├── exchange/                       # Binance REST + WebSocket client
│   │   ├── binance.go                  # API calls: candles, orders, account, funding rates
│   │   └── types.go                    # Candle, OrderResult, etc.
│   ├── data/                           # Data persistence
│   │   ├── store.go                    # CandleStore interface
│   │   ├── sqlite_store.go             # SQLite implementation (candles.db)
│   │   ├── funding.go                  # FundingCache — in-memory funding rate cache
│   │   └── funding_store.go            # FundingStore — SQLite persistence for arb positions + funding rates
│   ├── features/                       # Technical indicator calculations (Go)
│   │   ├── indicators.go               # EMA, RSI, ATR, ADX, Bollinger, Donchian, VolumeRatio, etc.
│   │   ├── builder.go                  # FeatureVector builder (5m)
│   │   └── builder_4h.go              # FeatureVector4H builder
│   ├── execution/                      # Order execution
│   │   ├── engine.go                   # ExecutionEngine interface
│   │   ├── paper.go                    # Paper trading engine (simulated fills)
│   │   └── live.go                     # Live Binance execution (spot + futures)
│   ├── risk/manager.go                 # Position sizing, leverage limits
│   ├── bot/                            # Bot runner entry points
│   │   ├── trend.go                    # RunTrendFollowing() — orchestrates trend strategy
│   │   ├── funding.go                  # RunFundingArb() — orchestrates funding arb strategy
│   │   ├── basis.go                    # RunBasisTrade() — orchestrates basis trade strategy
│   │   ├── mm.go                       # RunMarketMaking() — orchestrates market making strategy
│   │   └── common.go                   # Shared setup (exchange client, context, stats)
│   ├── backtest/                       # Offline backtester
│   │   ├── engine.go                   # Backtest loop
│   │   ├── loader.go                   # Load historical data
│   │   └── reporter.go                # PnL, Sharpe, drawdown metrics
│   ├── metrics/prometheus.go           # All Prometheus metrics
│   ├── alerts/telegram.go              # Telegram bot notifications
│   ├── model/                          # Legacy XGBoost/ONNX inference (Go-side)
│   └── sentiment/                      # Sentiment microservice client (legacy)
│
├── ml/                                 # Python ML training & inference
│   ├── server.py                       # ** HTTP server: /predict, /predict_regime, /predict_volatility **
│   ├── features.py                     # v1 feature engineering (19 features — legacy)
│   ├── trainer.py                      # v1 XGBoost trainer (legacy, overfit)
│   ├── analyze_models.py               # Deep model analysis script
│   ├── regime/                         # Regime Classifier (Traffic Light)
│   │   ├── features_regime_v1.py       # 6 features: volatility_20, volume_ratio_20, rsi_14, hour_sin/cos, funding_24h_avg
│   │   ├── label_regime.py             # Entry labeling: "did this Donchian breakout reach +1R before -1R?"
│   │   └── train_regime.py             # RandomForest(max_depth=4, min_samples_leaf=50)
│   ├── volatility/                     # Volatility Predictor (Dynamic Stop-Loss)
│   │   ├── features_vol_v1.py          # 6 features: range_1, range_sma_6, atrp_14, volume_ratio_20, hour_sin/cos
│   │   └── train_volatility.py         # HuberRegressor / Ridge regression on log(next_range_pct)
│   └── models/                         # Saved model files
│       ├── *.json                      # v1 XGBoost models (per symbol)
│       ├── regime_v1/*.pkl             # Regime classifier models (per symbol)
│       └── vol_v1/*.pkl                # Volatility predictor models (per symbol)
│
├── scripts/                            # Research & utility scripts (Python)
│   ├── retrain_pipeline.py             # ** Automated ML lifecycle orchestrator (cron) **
│   ├── fetch_data.py                   # Download historical data
│   ├── ingest_4h_to_sqlite.py          # Ingest 4H candles → training.db
│   ├── backtest_trend.py               # Python-side trend backtest
│   ├── backtest_momentum.py            # Cross-sectional momentum backtest
│   ├── walk_forward_trend.py           # Walk-forward validation
│   ├── train_model.py                  # Original training script
│   └── ...                             # Various research notebooks/scripts
│
├── sentiment/                          # Python sentiment microservice (FastAPI + FinBERT)
│   ├── main.py                         # FastAPI app
│   ├── config.py
│   ├── fetchers/                       # Twitter, Reddit, news fetchers
│   └── models/                         # FinBERT model
│
├── data/                               # Runtime data (SQLite candles.db, training.db)
├── docs/                               # Documentation
│   ├── ML_MODEL_ANALYSIS.md            # ** v1 model failure analysis — READ THIS FIRST for ML work **
│   ├── PLAN_D_IMPLEMENTATION.md        # Current strategy design doc
│   └── ...
│
├── config.trend.yaml                   # Trend-following strategy config
├── config.funding.yaml                 # Funding arbitrage strategy config
├── config.mm.yaml                      # Market making strategy config
├── config.example.trend.yaml           # Templates
├── config.example.funding.yaml
├── config.example.mm.yaml
├── docker-compose.yaml                 # Bot + ML server + sentiment
├── Dockerfile.bot                      # Go bot container
├── go.mod / go.sum                     # Go dependencies
├── CLAUDE.md                           # Legacy Claude Code instructions (mostly outdated)
└── AGENTS.md                           # THIS FILE — primary agent instructions
```

---

## Key Data Flow

```
Binance WS → candles → SQLite → OnBar() → Layer 1 (entry signal?) → Layer 2 (regime OK?) → Layer 3 (stop/size) → Paper/Live execution → Telegram alert
                                    │                                      │
                                    │                              ML Server (Python)
                                    │                              POST /predict_regime → prob_safe
                                    │                              POST /predict_volatility → range_pct
                                    └── if has position: UpdateTrailingStop() → CheckPartialExit()
```

---

## Configuration Quick Reference

| Strategy | Config file | Key settings |
|----------|-------------|-------------|
| **Trend Following** | `config.trend.yaml` | `strategy.type: trend_following`<br>`strategy.regime_filter.enabled: false` (Traffic Light)<br>`strategy.dynamic_stop.enabled: false` (ML stops)<br>`risk.max_risk_per_trade_pct: 1.0` |
| **Funding Arb** | `config.funding.yaml` | `strategy.type: funding_arb`<br>`strategy.funding_arb.min_funding_rate: 0.0005`<br>`strategy.funding_arb.delta_neutral: true`<br>`strategy.funding_arb.db_path: funding.db` |
| **Basis Trade** | `config.basis.yaml` | `strategy.type: basis_trade`<br>`strategy.basis_trade.min_basis_annualized: 0.15`<br>`strategy.basis_trade.exit_basis: 0.05` |
| **Market Making** | `config.mm.yaml` | `strategy.type: market_making`<br>`strategy.market_making.spread_pct: 0.005`<br>`strategy.market_making.gamma: 0.1` |
| **Global** | All configs | `mode: paper` ⚠️ never change to `live` without explicit instruction |

---

## Development Commands

```bash
# Go
go build ./...                                    # Build everything
go test ./...                                     # Run all tests
go test -v -run TestName ./internal/strategy      # Specific test
go build -o bin/bot ./cmd/bot && ./bin/bot -c config.yaml  # Run bot

# Python ML
python3 ml/regime/train_regime.py                 # Train regime classifier
python3 ml/volatility/train_volatility.py         # Train volatility predictor
python3 ml/server.py --models-dir ml/models       # Start ML inference server
python3 ml/analyze_models.py                      # Analyze v1 models (from ml/ dir)

# Automated Retraining
python3 scripts/retrain_pipeline.py fetch         # Incremental data fetch
python3 scripts/retrain_pipeline.py run           # Full retraining cycle (cron)
python3 scripts/retrain_pipeline.py evaluate --run-id <id>  # Check specific run

# Backtest
go build -o backtest ./cmd/backtest && ./backtest -c config.yaml
python3 scripts/backtest_trend.py                 # Python backtest
```

---

## Critical Rules

### ⚠️ NEVER DO
- **Never change `mode` to `live`** unless explicitly told by the user
- **Never modify API keys or secrets**
- **Never delete training data** (`data/training.db`, `data/candles.db`)
- **Never enable `ml_filter`** (v1) — it is overfit and will lose money
- **Never increase model complexity** without overfitting analysis (train vs test AUC gap < 0.08)

### ✅ ALWAYS DO
- **Run `go build ./...` and `go test ./...`** after any Go changes
- **Check Python syntax** with `python3 -c "import ast; ast.parse(open('file.py').read())"` after Python changes
- **Feature parity:** when adding/changing features, update BOTH Python (`ml/*/features_*.py`) AND Go (`internal/strategy/trend_*_features.go`) — feature names must match exactly
- **Read `docs/ML_MODEL_ANALYSIS.md`** before any ML work — it explains why v1 failed

---

## How to Work: Break Features Into Issues

**ALWAYS break any feature or task into smaller, independent issues using `bd` (beads).** This is mandatory, not optional.

### Workflow

1. **Analyze the feature** — understand scope, identify which files/layers are affected
2. **Create issues** — break into the smallest units that can be implemented independently:
   ```bash
   bd create --title "Add X feature to Python trainer" --body "..."
   bd create --title "Add X feature Go-side feature builder" --body "..."
   bd create --title "Wire X feature in config.go" --body "..."
   bd create --title "Add X feature integration in trend.go OnBar()" --body "..."
   bd create --title "Add tests for X feature" --body "..."
   ```
3. **Work issues in parallel** when they don't touch the same files — use `Task` tool to run sub-agents concurrently
4. **Claim → Do → Verify → Close** each issue:
   ```bash
   bd update <id> --status in_progress   # Claim
   # ... do the work ...
   go build ./... && go test ./...       # Verify
   bd close <id>                         # Close
   ```
5. **Notify per Telegram after each issue** — use the `notifying-telegram` skill to send a short summary of what was done

### Good issue breakdown example (adding a new ML model):

| Issue | Can parallel? |
|-------|:---:|
| Python feature engineering + trainer | ✅ |
| Go feature builder | ✅ |
| Config struct + defaults | ✅ |
| ML server endpoint | ✅ |
| ML client method (Go) | after config |
| Strategy integration (OnBar) | after all above |
| Tests | after integration |
| Documentation | ✅ |

### Bad: one giant issue like "Add regime classifier end-to-end"

---

## Beads Quick Reference

```bash
bd onboard                                        # First-time setup
bd ready                                          # Find available work
bd show <id>                                      # View issue details
bd create --title "..." --body "..."              # Create issue
bd update <id> --status in_progress               # Claim work
bd close <id>                                     # Complete work
bd sync                                           # Sync with git
```

---

## Telegram Notifications

**After completing each issue**, notify the user via Telegram with a short summary. Load the `notifying-telegram` skill and send a message like:

```
✅ Issue #<id>: <title>
<1-2 sentence summary of what was done>
Files changed: <list>
```

This keeps the user informed without them having to check constantly.

---

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** — create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) — `go build ./...`, `go test ./...`, Python syntax checks
3. **Update issue status** — close finished work, update in-progress items
4. **PUSH TO REMOTE** — this is MANDATORY:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** — clear stashes, prune remote branches
6. **Verify** — all changes committed AND pushed
7. **Hand off** — provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing — that leaves work stranded locally
- NEVER say "ready to push when you are" — YOU must push
- If push fails, resolve and retry until it succeeds
