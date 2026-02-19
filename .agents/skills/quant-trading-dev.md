# Quant Trading Bot Development Skill

**Version**: 1.0  
**Last Updated**: 2026-02-19  
**Project**: Multi-Strategy Crypto Trading Bot  

---

## Overview

This skill provides a structured workflow for developing and enhancing a production-grade crypto quant trading bot. It combines modern strategy research, codebase understanding, and systematic implementation.

---

## Tech Stack

### Backend (Go 1.25+)
- **Framework**: Custom microservices architecture
- **Exchange**: Binance REST + WebSocket
- **Database**: SQLite (modernc.org/sqlite)
- **Metrics**: Prometheus + Grafana
- **Logging**: zerolog
- **Config**: Viper (YAML)
- **Testing**: testify

### ML/Research (Python 3.10+)
- **Server**: Custom HTTP server (port 9001)
- **ML Libraries**: 
  - scikit-learn (RandomForest, Ridge, HuberRegressor)
  - hmmlearn (GaussianHMM for regime detection)
  - xgboost (legacy, mostly disabled)
  - pandas, numpy
- **Data**: Parquet files (4H candles, 6 years)
- **Training DB**: SQLite (data/training.db)

### Infrastructure
- **Deployment**: Docker Compose
- **Monitoring**: Prometheus (port 9090) + Grafana (port 3000)
- **Alerts**: Telegram Bot API
- **Paper Trading**: Built-in simulation engine

---

## Project Structure

```
quant/
├── cmd/bot/                    # Main bot entry point
├── internal/
│   ├── strategy/               # ⭐ CORE: All trading logic
│   │   ├── trend.go            # Trend following (Plan D)
│   │   ├── market_making/      # Market making strategy
│   │   ├── funding_arb/        # Funding rate arbitrage
│   │   └── basis_trade/        # Perpetual basis trade
│   ├── exchange/               # Binance client
│   ├── execution/              # Order execution (paper/live)
│   ├── mlfilter/               # ML inference client
│   ├── features/               # Technical indicators (Go)
│   ├── data/                   # SQLite stores
│   ├── risk/                   # Position sizing, limits
│   ├── metrics/                # Prometheus metrics
│   └── alerts/                 # Telegram notifications
├── ml/                         # ⭐ Python ML service
│   ├── server.py               # HTTP inference server
│   ├── regime/                 # Regime classifiers
│   ├── volatility/             # Volatility predictors
│   └── models/                 # Trained models (.pkl, .json)
├── scripts/                    # Research & utilities
│   ├── retrain_pipeline.py     # ⭐ Automated retraining
│   ├── backtest_*.py           # Backtesting scripts
│   └── fetch_data.py           # Data fetching
├── data/                       # Runtime data
│   ├── training.db             # ML training data
│   ├── candles.db              # Live candle cache
│   └── funding.db              # Funding rate history
├── data_4h/                    # Historical 4H candles (parquet)
├── docs/                       # ⭐ Documentation (organized by date)
│   ├── README.md               # Navigation index
│   └── 2026-02-19/             # Latest docs
└── config.*.yaml               # Strategy configs (gitignored)
```

---

## Current Strategies

### 1. Trend Following (Plan D) — Primary Strategy
**File**: `internal/strategy/trend.go`

**Logic**:
- **Entry**: Donchian breakout (20-bar) + EMA(9/21/50) confirmation + volume + whipsaw defense
- **Filters**: ADX > 20, volatility (ATR ratio), funding rate, OI z-score, optional HMM regime
- **Exit**: Chandelier trailing stop (dynamic ATR multiplier) + partial exits at 3R/6R
- **Risk**: 1% per trade, 2x max leverage, 3% stop loss

**Status**: ✅ Production-ready, Phase 1 enhancements complete

### 2. Market Making — Liquidity Provision
**File**: `internal/strategy/market_making/strategy.go`

**Logic**:
- Bid/ask orders around mid-price with dynamic spread (volatility-adjusted)
- Inventory skewing (Avellaneda-Stoikov)
- Order book imbalance detection (Phase 1 enhancement)

**Status**: ✅ Phase 1 enhancements complete

### 3. Funding Rate Arbitrage — Delta-Neutral Carry
**File**: `internal/strategy/funding_arb/strategy.go`

**Logic**:
- SHORT perp when funding > threshold (0.05% per 8h)
- Optional LONG spot hedge (delta-neutral)
- Momentum detection (Phase 1 enhancement)

**Status**: ✅ Phase 1 enhancements complete

### 4. Basis Trade — Cash-and-Carry
**File**: `internal/strategy/basis_trade/strategy.go`

**Logic**:
- LONG spot + SHORT perp when basis > 15% annualized
- Exit when basis converges

**Status**: ✅ Implemented

---

## ML Models

### Current Models (Phase 1)

| Model | Type | Purpose | Status | Location |
|-------|------|---------|--------|----------|
| **Regime Classifier** | RandomForest | Traffic light (SAFE/DANGER) | ✅ Trained | `ml/regime/` |
| **Volatility Predictor** | HuberRegressor | Dynamic stop-loss | ✅ Trained | `ml/volatility/` |
| **HMM Regime** | GaussianHMM | Probabilistic states (3) | ✅ Trained | `ml/regime/` |
| **Directional v1** | XGBoost | Trend prediction | ❌ Disabled (overfit) | `ml/` |

### Model Endpoints (ML Server)

```python
POST /predict                     # Legacy XGBoost (disabled)
POST /predict_regime              # Regime classifier (traffic light)
POST /predict_regime_hmm          # HMM regime (probabilistic)
POST /predict_volatility          # Volatility predictor
GET  /health                      # Health check
```

---

## Development Workflow

### Phase 1: Research Modern Strategies

**Goal**: Identify high-alpha opportunities in current crypto markets

**Process**:
1. **Literature Review**
   - Academic papers (SSRN, arXiv)
   - Industry reports (Galaxy Digital, Delphi Digital)
   - Exchange research (Binance Research, Deribit Insights)

2. **Key Areas to Research**
   - Order flow analysis (order book imbalance, trade flow)
   - Liquidation cascade trading
   - Cross-exchange arbitrage
   - Volatility surface trading
   - MEV/on-chain opportunities
   - Cross-sectional momentum
   - Funding rate prediction models

3. **Evaluation Criteria**
   - Expected Sharpe ratio improvement
   - Implementation complexity (Low/Medium/High)
   - Data requirements
   - Latency sensitivity
   - Capital requirements

4. **Output**: Strategy research document in `docs/YYYY-MM-DD/STRATEGY_RESEARCH_ANALYSIS.md`

**Example Research Questions**:
- What are the top 3 strategies used by crypto market makers in 2026?
- How do modern quant funds detect liquidation cascades?
- What's the current state of cross-exchange arbitrage profitability?
- Which ML models outperform for regime detection?

---

### Phase 2: Review Current Implementation

**Goal**: Understand what exists and identify gaps

**Process**:
1. **Read Documentation**
   - Start with `docs/README.md` (navigation index)
   - Read latest docs in `docs/YYYY-MM-DD/`
   - Review `AGENTS.md` for architecture overview

2. **Analyze Current Strategies**
   - Read strategy files in `internal/strategy/`
   - Check config files (`config.*.yaml`)
   - Review ML models in `ml/models/`

3. **Identify Gaps**
   - Compare research findings vs current implementation
   - List missing features
   - Prioritize by impact/effort ratio

4. **Check Recent Changes**
   - Review git log: `git log --oneline --since="1 week ago"`
   - Check latest docs for recent enhancements

5. **Output**: Gap analysis document

**Key Files to Review**:
```bash
# Strategy logic
internal/strategy/trend.go
internal/strategy/market_making/strategy.go
internal/strategy/funding_arb/strategy.go

# ML integration
ml/server.py
internal/mlfilter/client.go

# Config
config.example.*.yaml

# Recent docs
docs/README.md
docs/YYYY-MM-DD/
```

---

### Phase 3: Design Implementation Plan

**Goal**: Break down enhancements into manageable tasks

**Process**:
1. **Prioritize Features**
   - Quick wins (high impact, low effort)
   - Strategic bets (high impact, high effort)
   - Nice-to-haves (low impact)

2. **Break Into Issues**
   - Use `bd` (beads) to create granular issues
   - Each issue should be < 2 hours of work
   - Identify dependencies

3. **Estimate Impact**
   - Expected Sharpe improvement
   - Expected win rate improvement
   - Expected PnL improvement

4. **Plan Testing**
   - Unit tests
   - Backtest validation
   - Paper trading duration
   - Success metrics

5. **Output**: Implementation plan document

**Example Issue Breakdown** (Adding liquidation cascade detection):
```bash
bd create --title "Research liquidation cascade indicators" --body "..."
bd create --title "Add liquidation level calculation (Python)" --body "..."
bd create --title "Add liquidation level calculation (Go)" --body "..."
bd create --title "Create liquidation cascade detector" --body "..."
bd create --title "Integrate cascade detector into trend strategy" --body "..."
bd create --title "Add cascade metrics to Prometheus" --body "..."
bd create --title "Backtest cascade strategy" --body "..."
bd create --title "Document cascade strategy" --body "..."
```

---

### Phase 4: Implementation

**Goal**: Build, test, and deploy enhancements

**Process**:

#### 4.1 Python ML Components (if needed)

**Location**: `ml/`

**Steps**:
1. **Feature Engineering**
   ```python
   # ml/regime/features_*.py
   def build_features(df):
       # Add new features
       return features
   ```

2. **Model Training**
   ```python
   # ml/regime/train_*.py
   model = RandomForest(...)
   model.fit(X_train, y_train)
   joblib.dump(model, "ml/models/regime_v2/...")
   ```

3. **Server Endpoint**
   ```python
   # ml/server.py
   def handle_predict_new_model(self):
       features = json.loads(self.rfile.read(...))
       prediction = model.predict(features)
       self.send_json({"prediction": prediction})
   ```

4. **Test Locally**
   ```bash
   python3 ml/server.py --models-dir ml/models
   curl -X POST http://localhost:9001/predict_new_model -d '{...}'
   ```

#### 4.2 Go Strategy Components

**Location**: `internal/strategy/`

**Steps**:
1. **Feature Builder** (if ML integration)
   ```go
   // internal/strategy/trend_new_features.go
   func (ts *TrendStrategy) BuildNewFeatures(symbol string) map[string]float64 {
       // Build features matching Python side
       return features
   }
   ```

2. **ML Client Method** (if ML integration)
   ```go
   // internal/mlfilter/client.go
   func (c *Client) PredictNewModel(symbol string, features map[string]float64) (*NewModelResponse, error) {
       // HTTP call to ML server
   }
   ```

3. **Strategy Integration**
   ```go
   // internal/strategy/trend.go (or new file)
   func (ts *TrendStrategy) CheckNewSignal(symbol string) bool {
       features := ts.BuildNewFeatures(symbol)
       resp, err := ts.mlClient.PredictNewModel(symbol, features)
       // Use prediction
   }
   ```

4. **Config Updates**
   ```go
   // internal/config/config.go
   type TrendConfig struct {
       // ... existing fields
       NewFeatureEnabled bool `mapstructure:"new_feature_enabled"`
   }
   ```

5. **Metrics** (optional)
   ```go
   // internal/metrics/prometheus.go
   var NewFeatureMetric = prometheus.NewGaugeVec(...)
   ```

6. **Tests**
   ```go
   // internal/strategy/trend_test.go
   func TestNewFeature(t *testing.T) {
       // Unit tests
   }
   ```

#### 4.3 Quality Gates

**Before Committing**:
```bash
# Go
go build ./...                    # Must pass
go test ./...                     # Must pass
go vet ./...                      # Check for issues

# Python
python3 -m py_compile ml/*.py     # Syntax check
python3 -m pytest ml/             # If tests exist
```

#### 4.4 Documentation

**Create/Update**:
- Feature documentation in `docs/YYYY-MM-DD/`
- Update `docs/README.md` if major feature
- Update config examples (`config.example.*.yaml`)
- Add inline code comments

---

### Phase 5: Testing & Validation

**Goal**: Verify enhancements work and improve performance

**Process**:

#### 5.1 Unit Tests
```bash
go test -v ./internal/strategy/... -run TestNewFeature
```

#### 5.2 Backtest
```bash
# Create backtest script
python3 scripts/backtest_new_feature.py

# Compare vs baseline
python3 scripts/compare_strategies.py
```

**Key Metrics**:
- Win rate
- Sharpe ratio
- Max drawdown
- Total return
- Number of trades

#### 5.3 Paper Trading
```bash
# Start ML server (if needed)
python3 ml/server.py --models-dir ml/models

# Start bot in paper mode
./bin/bot -c config.trend.yaml  # mode: paper in config
```

**Monitor**:
- Logs: `logs/bot_trend.log`
- Metrics: http://localhost:9090 (Prometheus)
- Telegram alerts

**Duration**: 24-48 hours minimum

#### 5.4 Stress Testing
```bash
python3 scripts/stress_test.py
```

**Scenarios**:
- COVID crash (-50% in 2 days)
- Luna collapse (-90% in 1 day)
- China ban (-30% in 1 week)

**Success Criteria**: Portfolio survives all scenarios

---

### Phase 6: Deployment

**Goal**: Enable in production configs and monitor

**Process**:

#### 6.1 Enable Feature
```yaml
# config.trend.yaml (or relevant config)
strategy:
  new_feature_enabled: true
  new_feature_param: 0.5
```

#### 6.2 Restart Services
```bash
# Stop bots
pkill -f "bin/bot"

# Restart ML server (if models changed)
pkill -f "ml/server.py"
python3 ml/server.py --models-dir ml/models &

# Restart bots
./start.sh
```

#### 6.3 Monitor
- **First 1 hour**: Watch logs continuously
- **First 24 hours**: Check metrics every 2-4 hours
- **First week**: Daily performance review

#### 6.4 Rollback Plan
```yaml
# If issues detected, disable immediately
new_feature_enabled: false
```

Then restart bots.

---

## Coding Standards

### Go

**Style**:
- Follow standard Go conventions (gofmt, golint)
- Use zerolog for logging
- Prefer explicit error handling over panics
- Use context.Context for cancellation

**Patterns**:
```go
// Locking pattern
ts.mu.Lock()
defer ts.mu.Unlock()

// Error handling
if err != nil {
    log.Error().Err(err).Msg("operation failed")
    return err
}

// Logging
log.Info().
    Str("symbol", symbol).
    Float64("price", price).
    Msg("signal detected")
```

**Testing**:
```go
func TestFeature(t *testing.T) {
    // Arrange
    strategy := NewTrendStrategy(DefaultTrendConfig())
    
    // Act
    result := strategy.CheckSignal("BTCUSDT")
    
    // Assert
    assert.True(t, result)
}
```

### Python

**Style**:
- PEP 8 compliant
- Type hints for function signatures
- Docstrings for public functions
- Use pathlib for file paths

**Patterns**:
```python
def train_model(df: pd.DataFrame, symbol: str) -> object:
    """Train model for given symbol.
    
    Args:
        df: Training data
        symbol: Trading symbol
        
    Returns:
        Trained model object
    """
    # Implementation
    return model
```

**Error Handling**:
```python
try:
    model = joblib.load(model_path)
except FileNotFoundError:
    print(f"Model not found: {model_path}", file=sys.stderr)
    return None
```

---

## Common Tasks

### Add New ML Model

**Steps**:
1. Create trainer: `ml/new_model/train_new_model.py`
2. Add features: `ml/new_model/features_new_model.py`
3. Train models: `python3 ml/new_model/train_new_model.py`
4. Add endpoint: `ml/server.py` (new handler)
5. Add Go client: `internal/mlfilter/client.go` (new method)
6. Integrate: `internal/strategy/*.go`
7. Test: Unit tests + backtest
8. Document: `docs/YYYY-MM-DD/NEW_MODEL.md`

### Add New Strategy

**Steps**:
1. Create package: `internal/strategy/new_strategy/`
2. Implement interface: `Strategy` interface
3. Add config: `internal/config/config.go`
4. Add bot runner: `internal/bot/new_strategy.go`
5. Add example config: `config.example.new_strategy.yaml`
6. Test: Unit tests + backtest
7. Document: `docs/YYYY-MM-DD/NEW_STRATEGY.md`

### Add New Indicator

**Steps**:
1. Go implementation: `internal/features/indicators.go`
2. Python implementation: `ml/features.py` (if needed for ML)
3. Tests: `internal/features/indicators_test.go`
4. Use in strategy: `internal/strategy/*.go`

### Retrain All Models

**Automated**:
```bash
# Fetch latest data
python3 scripts/retrain_pipeline.py fetch

# Retrain all models
python3 scripts/retrain_pipeline.py run

# Check results
python3 scripts/retrain_pipeline.py evaluate --run-id <id>
```

**Manual**:
```bash
# Regime classifier
python3 ml/regime/train_regime.py

# HMM regime
python3 ml/regime/train_regime_hmm.py

# Volatility predictor
python3 ml/volatility/train_volatility.py
```

---

## Key Metrics

### Strategy Performance

| Metric | Target | Current (Baseline) |
|--------|--------|-------------------|
| Win Rate | >45% | 27.2% |
| Sharpe Ratio | >1.5 | 0.08 |
| Max Drawdown | <15% | TBD |
| Avg Trade Duration | 2-5 days | TBD |

### ML Model Performance

| Model | Metric | Target | Current |
|-------|--------|--------|---------|
| Regime Classifier | Accuracy | >60% | 62% |
| HMM Regime | State Stability | >80% | TBD |
| Volatility Predictor | R² | >0.3 | 0.35 |

---

## Critical Rules

### ⚠️ NEVER DO
- **Never change `mode` to `live`** without explicit user approval
- **Never delete training data** (`data/training.db`, `data/candles.db`)
- **Never commit API keys** (they're gitignored)
- **Never enable overfit models** (v1 XGBoost is disabled for a reason)
- **Never skip backtesting** before paper trading

### ✅ ALWAYS DO
- **Run quality gates** before committing (`go build ./...`, `go test ./...`)
- **Feature parity**: Python features must match Go features exactly
- **Document changes**: Update docs for any new feature
- **Test thoroughly**: Unit tests + backtest + paper trading
- **Monitor after deployment**: Watch logs and metrics closely
- **Use beads**: Break work into small issues with `bd`

---

## Useful Commands

### Development
```bash
# Build
go build ./...

# Test
go test ./...
go test -v ./internal/strategy/... -run TestSpecific

# Run bot
./bin/bot -c config.trend.yaml

# Start ML server
python3 ml/server.py --models-dir ml/models

# Backtest
python3 scripts/backtest_trend.py

# Stress test
python3 scripts/stress_test.py
```

### Data Management
```bash
# Fetch latest data
python3 scripts/retrain_pipeline.py fetch

# Ingest to training DB
python3 scripts/ingest_4h_to_sqlite.py

# Check data
sqlite3 data/training.db "SELECT COUNT(*) FROM candles_4h;"
```

### Monitoring
```bash
# View logs
tail -f logs/bot_trend.log

# Check metrics
curl http://localhost:9090/metrics | grep strategy

# Test ML server
curl http://localhost:9001/health
```

### Git Workflow
```bash
# Sync beads
bd sync

# Commit
git add -A
git commit -m "feat: Add new feature"
git push

# Check status
git status
bd ready
```

---

## Research Resources

### Academic
- **SSRN**: https://ssrn.com (search "cryptocurrency trading")
- **arXiv**: https://arxiv.org (search "algorithmic trading")
- **Journal of Financial Markets**: Quant trading papers

### Industry
- **Binance Research**: https://research.binance.com
- **Deribit Insights**: https://insights.deribit.com
- **Galaxy Digital Research**: https://www.galaxy.com/research
- **Delphi Digital**: https://members.delphidigital.io

### Technical
- **Binance API Docs**: https://binance-docs.github.io/apidocs
- **TA-Lib**: Technical indicator reference
- **Quantopian Lectures**: Archived quant finance tutorials

### Communities
- **QuantConnect**: Forum for algo trading
- **Reddit r/algotrading**: Community discussions
- **Twitter**: Follow @CryptoCred, @ThinkingUSD, @AlamedaTrabucco

---

## Troubleshooting

### ML Server Won't Start
```bash
# Check Python dependencies
pip3 install -r ml/requirements.txt

# Check models exist
ls -la ml/models/regime_v1/

# Check port availability
lsof -i :9001
```

### Bot Crashes on Startup
```bash
# Check config syntax
cat config.trend.yaml | python3 -c "import yaml, sys; yaml.safe_load(sys.stdin)"

# Check database
sqlite3 data/candles.db "PRAGMA integrity_check;"

# Check logs
tail -100 logs/bot_trend.log
```

### Backtest Fails
```bash
# Check data exists
ls -la data_4h/*.parquet

# Check Python dependencies
pip3 install pandas numpy

# Run with verbose output
python3 scripts/backtest_trend.py --verbose
```

### Tests Failing
```bash
# Run specific test
go test -v ./internal/strategy/... -run TestName

# Check for race conditions
go test -race ./...

# Clean and rebuild
go clean -cache
go build ./...
```

---

## Next Steps After Using This Skill

1. **Research Phase**: Create `docs/YYYY-MM-DD/STRATEGY_RESEARCH_ANALYSIS.md`
2. **Gap Analysis**: Document findings in `docs/YYYY-MM-DD/GAP_ANALYSIS.md`
3. **Implementation Plan**: Create issues with `bd create`
4. **Execute**: Follow Phase 4 workflow
5. **Validate**: Follow Phase 5 workflow
6. **Deploy**: Follow Phase 6 workflow
7. **Monitor**: Track metrics and iterate

---

## Version History

- **1.0** (2026-02-19): Initial version covering Phase 1 complete state

---

**End of Skill**
