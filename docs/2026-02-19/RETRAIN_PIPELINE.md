# ML Model Retraining Pipeline

## Overview

The automated ML model retraining pipeline (`scripts/retrain_pipeline.py`) handles the end-to-end lifecycle of retraining crypto trading models:

1. **Incremental data fetch** from Binance (4H candles + funding rates)
2. **Training all model variants** into a staging directory
3. **Model evaluation** (compare new vs current models)
4. **Atomic deployment** with backup and rollback
5. **ML server restart** and health verification

## Architecture

### Model Variants

The pipeline trains 5 model variants:

1. **Regime v1** (all 4 symbols) — 6-feature regime classifier
   - Script: `ml/regime/train_regime.py`
   - Output: `ml/models/regime_v1/`

2. **Regime v2** (all 4 symbols, only ETH used in production) — 8-feature regime classifier with volatility features
   - Script: `ml/regime/train_regime_v2.py`
   - Output: `ml/models/regime_v2/`

3. **Regime v1 LONG** (SOL only) — Directional LONG-only regime classifier
   - Script: `ml/regime/train_regime_directional_save.py`
   - Output: `ml/models/regime_v1_long/`

4. **Regime HMM v1** (all 4 symbols) — HMM-based regime detection (Phase 1)
   - Script: `ml/regime/train_regime_hmm.py`
   - Output: `ml/models/regime_hmm_v1/`
   - Models: 4 files per symbol (model, scaler, mapping, stats)

5. **Volatility v1** (all 4 symbols) — Volatility predictor for dynamic stop-loss
   - Script: `ml/volatility/train_volatility.py`
   - Output: `ml/models/vol_v1/`

### Data Flow

```
Binance API
    ↓ (incremental fetch)
data/training.db (SQLite)
    ↓ (train)
ml/models_staging/<run_id>/
    ↓ (evaluate + deploy)
ml/models/ (live)
    ↓ (load)
ML Server (port 9001)
    ↓ (predict)
Go Bot
```

### Staging & Deployment

1. **Staging**: Models train into `ml/models_staging/<run_id>/`
2. **Evaluation**: Compare staged vs current models using `_meta.json`
3. **Backup**: Current live models backed up to `ml/models_backups/<timestamp>/`
4. **Atomic Swap**: Staged models moved to `ml/models/` (atomic operation)
5. **Hot-Reload**: ML server restarted (bot doesn't need restart, handles errors gracefully)

### Rollback Mechanism

If ML server health check fails after deployment:
1. Restore models from backup directory
2. Restart ML server again
3. Verify health
4. Abort pipeline with exit code 1

## Usage

### Subcommands

```bash
# Incremental fetch from Binance to training.db
python3 scripts/retrain_pipeline.py fetch

# Train all model variants into staging
python3 scripts/retrain_pipeline.py train --run-id 20260209_1200

# Evaluate staged models vs current models
python3 scripts/retrain_pipeline.py evaluate --run-id 20260209_1200

# Deploy staged models (atomic swap + server restart + health check)
python3 scripts/retrain_pipeline.py deploy --run-id 20260209_1200

# Run all steps in sequence (for cron)
python3 scripts/retrain_pipeline.py run
```

### Manual Workflow

```bash
# 1. Fetch latest data
python3 scripts/retrain_pipeline.py fetch

# 2. Train models
RUN_ID=$(date +%Y%m%d_%H%M%S)
python3 scripts/retrain_pipeline.py train --run-id $RUN_ID

# 3. Evaluate models
python3 scripts/retrain_pipeline.py evaluate --run-id $RUN_ID

# 4. Deploy if evaluation passed
python3 scripts/retrain_pipeline.py deploy --run-id $RUN_ID
```

### Automated (Cron)

Add to crontab for daily retraining at 2am UTC:

```bash
# Daily ML model retraining (2am UTC)
0 2 * * * cd /path/to/quant && python3 scripts/retrain_pipeline.py run >> logs/retrain.log 2>&1
```

The `run` command executes all steps in sequence with a file lock to prevent concurrent runs.

## Evaluation Criteria

### Regime Models (Classifiers)

Models are **approved** if ALL conditions pass:

1. **AUC Gate**: `test_auc >= old_test_auc - 0.02` (tolerance for noise)
2. **Overfitting Gate**: `auc_gap <= 0.20` (reject if gap > 20pp)
3. **Data Gate**: `n_test_entries >= 10` (minimum test samples)

**Special Rules**:
- Regime v2 ETH: Only ETH evaluation matters for deployment gate (per ML_V2 report)
- Regime v1: All 4 symbols must pass
- Regime v1 LONG: Only SOL must pass

### HMM Regime Models

HMM models are **approved** if:

1. **State Distribution**: All 3 states have >5% representation
2. **Forward Return Validation**: Trending state has highest |forward_return|
3. **Test Set Validation**: All states present in test set

HMM models don't use AUC (unsupervised), so evaluation is based on state characteristics.

### Volatility Models (Regressors)

Models are **approved** if:

1. **MAE Gate**: `test_mae <= old_test_mae + 0.0005` (tolerance 0.05pp)

## Rolling Window

The pipeline uses a **rolling 7-month test window**:

- **Train**: All data up to `(now - 7 months)`
- **Test**: Last 7 months

This ensures models are always evaluated on recent market conditions.

Previous static cutoff (`2025-07-01`) has been replaced with `get_train_cutoff()` in all training scripts.

## File Locking

The `run` command uses `fcntl` file locking on `data/retrain.lock` to prevent concurrent runs.

Manual subcommands (fetch, train, evaluate, deploy) can be run concurrently for debugging.

## Logging

All output goes to stdout/stderr. For cron jobs, redirect to `logs/retrain.log`:

```bash
python3 scripts/retrain_pipeline.py run >> logs/retrain.log 2>&1
```

Log format: `[YYYY-MM-DD HH:MM:SS UTC] message`

## Directory Structure

```
ml/
├── models/                   # Live models (loaded by server)
│   ├── regime_v1/
│   ├── regime_v2/
│   ├── regime_v1_long/
│   └── vol_v1/
├── models_staging/           # Staging directory (training output)
│   └── <run_id>/
│       ├── regime_v1/
│       ├── regime_v2/
│       ├── regime_v1_long/
│       └── vol_v1/
├── models_backups/           # Backup directory (rollback source)
│   └── <timestamp>/
│       ├── regime_v1/
│       ├── regime_v2/
│       ├── regime_v1_long/
│       └── vol_v1/
└── server.py                 # ML inference server

data/
├── training.db               # SQLite database (candles + funding)
└── retrain.lock              # File lock (prevents concurrent runs)

logs/
└── retrain.log               # Pipeline execution log
```

## ML Server Management

### PID File

The pipeline tracks the ML server process using `ml/server.pid`.

### Restart Sequence

1. Read PID from `ml/server.pid`
2. Send `SIGTERM` (graceful shutdown)
3. Wait 2s, check if still alive
4. If alive, send `SIGKILL` (force kill)
5. Start new server: `python3 ml/server.py --models-dir ml/models --port 9001`
6. Write new PID to `ml/server.pid`
7. Poll `/health` endpoint until status OK or timeout (10s)

### Health Check

The health check verifies:
- HTTP 200 response
- JSON `{"status": "ok", ...}`
- Expected model counts for each variant

If health check fails, deployment is rolled back.

## Incremental Fetch Logic

The fetch command queries `training.db` for the last timestamp per symbol:

```sql
SELECT MAX(open_time) FROM candles WHERE symbol = ?
SELECT MAX(timestamp) FROM funding WHERE symbol = ?
```

Then fetches from Binance starting at `last_timestamp + 1`, with a 3-candle backfill to handle exchange corrections.

**Key features**:
- Drops the current unclosed candle (only inserts `is_closed = 1` candles)
- Uses `INSERT OR REPLACE` for idempotency
- Handles rate limiting via `ccxt.enableRateLimit=True`
- Retries on errors with exponential backoff

## Troubleshooting

### Evaluation Rejected Deployment

Check the evaluation summary:

```bash
python3 scripts/retrain_pipeline.py evaluate --run-id <run_id>
```

Look for `❌ REJECTED` models and check:
- AUC drop too large (> 2pp)
- Overfitting gap too large (> 20pp)
- Insufficient test data (< 10 entries)

### Health Check Failed

Check ML server logs:

```bash
tail -100 logs/ml_server.log
```

Manually test health endpoint:

```bash
curl http://localhost:9001/health | jq
```

### Rollback Failed

If rollback fails, manually restore from backup:

```bash
# Find latest backup
ls -lht ml/models_backups/

# Restore
cp -r ml/models_backups/<timestamp>/* ml/models/

# Restart server
pkill -f "ml/server.py"
python3 ml/server.py --models-dir ml/models --port 9001 > logs/ml_server.log 2>&1 &
echo $! > ml/server.pid
```

### File Lock Stuck

If pipeline crashes and lock remains:

```bash
rm data/retrain.lock
```

## Performance

Typical run times (MacBook Pro M1):

- **Fetch**: 2-5 minutes (incremental, depends on # new candles)
- **Train Regime v1**: ~30 seconds per symbol
- **Train Regime v2**: ~30 seconds per symbol
- **Train Regime v1 LONG**: ~30 seconds (SOL only)
- **Train Volatility v1**: ~15 seconds per symbol
- **Total training**: ~8-10 minutes
- **Deployment**: ~5 seconds (swap + restart + health check)

**Full pipeline**: ~15-20 minutes (including fetch)

## Next Steps

1. **Monitoring**: Add Prometheus metrics for pipeline success/failure
2. **Alerting**: Telegram notification on deployment success/failure
3. **Model Registry**: Track model performance over time (AUC/MAE history)
4. **A/B Testing**: Deploy new models to a canary environment first
5. **Backtesting**: Run backtest on OOS data before deployment

## References

- ML V2 Implementation Report: `docs/ML_V2_IMPLEMENTATION_REPORT.md`
- Training scripts:
  - `ml/regime/train_regime.py`
  - `ml/regime/train_regime_v2.py`
  - `ml/regime/train_regime_directional_save.py`
  - `ml/volatility/train_volatility.py`
- ML Server: `ml/server.py`
- Oracle Design Discussion: Thread `T-019c41c8-b416-72ec-816a-ce0a33f8e48d`
