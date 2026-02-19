Based on your impressive progress, the plan pivots from "build the bot" to **"augment the bot with ML."** You've validated the core logic in paper trading, so now we focus on XGBoost integration and parameter optimization.

Here is the revised roadmap aligned with your current state:

***

# Revised Project Roadmap: ML-Enhanced Trading Bot

## **Current State Assessment**
- ✅ **Core Infrastructure:** Go-based bot with indicators, SQLite persistence, Binance integration.
- ✅ **Validation:** 68.9% walk-forward win rate, 100% param robustness, +65.58% backtest return.
- 🟡 **Live Testing:** Paper trading active since Feb 8, 2025.
- **Next Milestone:** Replace hard-coded `ADX > 20` with XGBoost classifier; automate parameter discovery.

***

## **Phase 4: ML Integration (XGBoost Filter)**
**Goal:** Export probability scores from a Python-trained XGBoost model and consume them in your Go bot.

### 4.1 Feature Engineering (Python)
- [ ] Create `ml/trainer.py` that queries your `data/candles.db` (SQLite) and `data_4h/funding/` data.
- [ ] Generate feature set per 4H candle:
    -   Price action: `returns_1d`, `returns_4d`, `volatility_20`.
    -   Technical: `rsi_14`, `bb_width`, `adx_14`, `ema_9_distance`.
    -   Funding: `funding_8h_avg`, `funding_vs_24h_mean`.
    -   Temporal: `hour_of_day_sin`, `day_of_week` (one-hot).
- [ ] **Target Variable:** Binary `1` if price 4 bars ahead is > 1.5% (vs open), else `0`.

### 4.2 Model Training (Python)
- [ ] Train `XGBClassifier` with `scale_pos_weight` (handles class imbalance in trend following).
- [ ] Export model to **JSON** format using `model.save_model("adx_replacement_{SYMBOL}.json")`.
- [ ] Validation: Achieve >60% precision on the hold-out test set (last 6 months of 2024).

### 4.3 Go Inference Bridge
- [ ] Python microservice (`ml_server.py`) exposing `/predict` endpoint; Go bot calls it via HTTP with current features.
- [ ] Update `strategy/trend.go`:
    -   Replace `if adx > 20` with `if xgbProbability > 0.65`.
    -   Cache features calculation in `OnBar()` to avoid recomputation.

***

## **Phase 5: Parameter Optimization (Optuna)**
**Goal:** Evolve the hard-coded numbers (Donchian periods, EMA lengths) per asset.

### 5.1 Optimization Harness (Python)
- [ ] Create `opt/optimize.py` that:
    -   Reads `backtest_trend.py` logic (or re-implements core logic).
    -   Defines search space:
        ```python
        donchian_period = trial.suggest_int('donchian', 12, 28)
        ema_fast = trial.suggest_int('ema_fast', 7, 12)
        ema_slow = trial.suggest_int('ema_slow', 18, 25)
        adx_threshold = trial.suggest_int('adx_threshold', 15, 30)  # Legacy mode
        xgb_threshold = trial.suggest_float('xgb_prob', 0.55, 0.80)
        ```
    -   **Objective:** Maximize `Sortino Ratio` from backtest results.

### 5.2 Automated Parameter Injection
- [ ] Modify `config.yaml` to support `dynamic_params: true`.
- [ ] Create `scripts/optimize_weekly.py`:
    -   Runs Optuna study on Saturday (market close).
    -   Updates `config.yaml` with best params for each symbol.
    -   Sends Telegram notification: "New params for BTC: Donchian=18, XGB_thresh=0.71".
    -   Go bot hot-reloads config (or restart via `systemctl`/`launchd`).

***

## **Phase 6: Live Validation & Deployment**
**Goal:** Confirm ML filter doesn't degrade performance in live conditions.

### 6.1 A/B Testing Framework
- [ ] Run parallel paper accounts:
    -   **Account A (Control):** Legacy `ADX > 20` filter.
    -   **Account B (ML):** XGBoost filter.
- [ ] Compare after 2 weeks: Win rate, avg trade duration, max drawdown.

### 6.2 Production Gate
- [ ] **Criteria:** ML variant must have:
    -   Higher Sortino than ADX variant.
    -   <5% increase in trade frequency (avoid over-trading).
    -   No major drawdowns (>8%) attributed to ML filter errors.

### 6.3 Live Deployment
- [ ] Switch `mode: paper` to `mode: live` in `config.yaml`.
- [ ] Implement `risk/monitor.go`:
    -   If drawdown > 10% in 24h, auto-revert to `ADX filter` (fail-safe).

***

## **Revised File Structure**

```text
/trading-bot-m1
│
├── /cmd/bot                 # Existing Go bot
│   └── main.go              # ✅ Already done
│
├── /core                    # Existing Go strategy
│   ├── strategy/trend.go    # 🟡 Update for XGBoost
│   └── indicators.go        # ✅ Done
│
├── /data                    # ✅ Existing SQLite
│   ├── candles.db
│   └── funding/
│
├── /config                  # 🟡 Update for optimization
│   └── config.yaml
│
├── /ml                      # NEW: Python ML Pipeline
│   ├── trainer.py           # XGBoost training
│   ├── features.py          # Feature engineering
│   ├── server.py            # Optional: HTTP inference API
│   └── models/              # Exported .json files
│
├── /opt                     # NEW: Optimization
│   ├── optimize.py          # Optuna harness
│   └── objective.py         # Backtest scorer
│
└── /scripts                 # Utilities
    ├── validate_paper.py    # ✅ Done
    └── optimize_weekly.py   # NEW: Automated retraining
```

***

## **Immediate Next Steps for Claude**

> **"Let's start Phase 4.1. I need a Python script `ml/features.py` that connects to my existing SQLite database at `data/candles.db` and generates the training features for XGBoost.**
>
> **Requirements:**
> 1. Load 4H OHLCV from `candles` table (schema: symbol, timestamp, open, high, low, close, volume).
> 2. Calculate features: returns (1,4,20 bars), RSI(14), EMA(9,21,50), ADX(14), Bollinger Band Width(20,2), ATR(14).
> 3. Load funding rates from `data/funding/` CSVs and merge them.
> 4. Create target column: `target = 1 if (close.shift(-4) / close - 1) > 0.015 else 0`.
> 5. Output clean DataFrame to `ml/data/training_features_{SYMBOL}.csv`.
>
> **Use `pandas`, `pandas-ta`, and `sqlite3`. Make it modular so we can run it for BTC, ETH, SOL, and XRP."**
