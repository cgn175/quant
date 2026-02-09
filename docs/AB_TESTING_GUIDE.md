# A/B Testing Guide: ML Filter vs ADX Filter

## Overview

Run two bot instances in parallel on paper trading to compare the ML filter against the legacy ADX filter. Each instance uses its own config, Prometheus port, and candle database.

## Setup

### 1. Create Control Config (`config_control.yaml`)

Copy `config.yaml` and set:

```yaml
strategy:
  variant: "control"
  ml_filter:
    enabled: false

storage:
  candle_db_path: "data/candles_control.db"

monitoring:
  prometheus_port: 9090
```

### 2. Create ML Config (`config_ml.yaml`)

Copy `config.yaml` and set:

```yaml
strategy:
  variant: "ml"
  ml_filter:
    enabled: true
    url: "http://localhost:9001"
    threshold: 0.65
    timeout_ms: 200
    fail_open: false
    fallback_to_adx: true

storage:
  candle_db_path: "data/candles_ml.db"

monitoring:
  prometheus_port: 9091
```

### 3. Run Both Instances

```bash
# Terminal 1: Control (ADX filter)
./bot --config config_control.yaml

# Terminal 2: ML filter
./bot --config config_ml.yaml
```

## Metrics to Compare

After 2 weeks of parallel operation, compare these Prometheus metrics:

| Metric | Query (Control) | Query (ML) |
|--------|-----------------|------------|
| Win Rate | `trading_win_rate{instance="localhost:9090"}` | `trading_win_rate{instance="localhost:9091"}` |
| Profit Factor | `trading_profit_factor{instance="localhost:9090"}` | `trading_profit_factor{instance="localhost:9091"}` |
| Total Trades | `trading_total_trades{instance="localhost:9090"}` | `trading_total_trades{instance="localhost:9091"}` |
| Max Drawdown | `trading_max_drawdown{instance="localhost:9090"}` | `trading_max_drawdown{instance="localhost:9091"}` |
| ML Errors | N/A | `ml_filter_errors_total` |
| ML Blocked | N/A | `ml_filter_blocked_total` |
| ML Fallbacks | N/A | `ml_filter_fallback_total` |
| ML Latency | N/A | `histogram_quantile(0.99, ml_filter_latency_seconds_bucket)` |

## Acceptance Criteria (Phase 6.2)

The ML variant must meet **all** of these before going live:

1. **Higher Sortino ratio** than ADX variant
2. **<5% increase in trade frequency** (avoid over-trading)
3. **No major drawdowns** (>8%) attributed to ML filter errors

## Prometheus Scrape Config

Add both instances to `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'quant-bot-control'
    static_configs:
      - targets: ['localhost:9090']
        labels:
          variant: 'control'

  - job_name: 'quant-bot-ml'
    static_configs:
      - targets: ['localhost:9091']
        labels:
          variant: 'ml'
```

## Dashboard Queries

Compare win rates side by side:

```promql
trading_win_rate{variant="control"} vs trading_win_rate{variant="ml"}
```

Compare equity curves:

```promql
trading_equity{variant="control"} vs trading_equity{variant="ml"}
```

ML filter health:

```promql
rate(ml_filter_errors_total[1h])
rate(ml_filter_fallback_total[1h])
histogram_quantile(0.95, rate(ml_filter_latency_seconds_bucket[5m]))
```
