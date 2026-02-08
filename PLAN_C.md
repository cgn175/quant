# Plan C: Statistical Arbitrage with Kalman Filters (Detailed MD Spec)

## Executive Summary
This strategy abandons directional prediction (forecasting "up/down") in favor of relative value arbitrage (forecasting "spread reversion"). It exploits the high correlation between related crypto assets (e.g., L1s, DeFi tokens) using a Kalman Filter to dynamically estimate the hedge ratio ($\beta$).

**Why this works in 2026:**
- **Market Neutral:** Returns are uncorrelated with BTC price action.
- **Adaptive:** The Kalman Filter adjusts to changing volatility/correlation regimes instantly, unlike static linear regression models.
- **Structural Edge:** Altcoins in the same sector are fundamentally tethered by capital flows; when they decouple without news, they statistically *must* revert.

***

## 1. System Architecture

The system consists of three distinct modules to separate research, signal generation, and execution.

### Module A: Universe Selection (Offline / Daily)
*Goal: Identify valid pairs that are historically cointegrated.*

1.  **Data Ingestion:**
    *   Fetch 1-hour OHLCV data for the top 50 liquid assets (excluding stablecoins) from Binance.
    *   **Filter:** Min daily volume > \$50M to ensure liquidity.
2.  **Clustering (Dimensionality Reduction):**
    *   Use **Affinity Propagation** or **DBSCAN** on log-returns to group assets into natural clusters (e.g., "Meme coins," "L1s," "DEXs").
    *   *Why:* Testing all 50x50 pairs is inefficient and leads to false positives. Only test pairs within the same cluster.
3.  **Cointegration Testing:**
    *   For each pair $(X, Y)$ in a cluster, run the **Engle-Granger Two-Step Method**.
    *   **Criteria:**
        *   P-value < 0.05 (Statistically significant cointegration).
        *   Hurst Exponent of spread < 0.5 (Mean reverting).
        *   Half-life of mean reversion < 24 hours (Ensures we don't hold bags for days).
4.  **Output:** A JSON list of "Active Pairs" for the live bot (e.g., `["SOL-AVAX", "UNI-AAVE", "DOGE-SHIB"]`).

### Module B: Signal Generation (Online / Real-time)
*Goal: Calculate the dynamic spread and generate trade signals.*

1.  **Input:** Real-time 1-minute candle closes for active pairs.
2.  **Kalman Filter (The Core Math):**
    *   Model the relationship as: $Price_Y = \alpha_t + \beta_t \cdot Price_X + \epsilon_t$
    *   **State Variable:** The vector $[\beta_t, \alpha_t]$ (Slope, Intercept).
    *   **Measurement Update:** On every new bar, update the estimate of $\beta_t$ and $\alpha_t$.
    *   **Prediction:** Forecast the "fair price" of Y: $\hat{Y} = \alpha_t + \beta_t \cdot X$.
    *   **Spread Calculation:** $e_t = Y_{actual} - \hat{Y}_{predicted}$.
    *   **Z-Score:** $z_t = \frac{e_t}{\sqrt{Q_t}}$, where $Q_t$ is the variance of the prediction error (provided by the filter).
3.  **Trade Logic:**
    *   **Short Spread:** If $z_t > 2.0$ (Y is expensive vs X) $\rightarrow$ Sell Y, Buy $\beta \cdot X$.
    *   **Long Spread:** If $z_t < -2.0$ (Y is cheap vs X) $\rightarrow$ Buy Y, Sell $\beta \cdot X$.
    *   **Exit:** If $z_t$ crosses 0.0 (Mean reversion complete).
    *   **Stop Loss:** If $|z_t| > 4.5$ (Regime break/News event) $\rightarrow$ Close immediately.

### Module C: Execution (Live)
*Goal: Execute delta-neutral legs with minimal slippage.*

1.  **Order Management:**
    *   Never use market orders. Use "Post-Only" limit orders at the best bid/ask.
    *   **Legging Risk:** Execute the maker side (usually the less liquid asset) first. Once filled, aggressively take liquidity on the second leg to lock the hedge.
2.  **Position Sizing:**
    *   Allocate capital per pair based on volatility (Volatility Targeting).
    *   Max leverage: 2x (market neutral allows higher leverage, but start safe).

***

## 2. Python Implementation Spec (For AI Agent)

Copy-paste this code block to your coding agent (Claude/Cursor) to scaffold the project.

```python
# structure.md

## Project Structure
- `data/`: Historical CSVs
- `models/`: Kalman Filter class
- `strategy/`: Signal generation logic
- `execution/`: CCXT order management
- `main.py`: Main loop

## Core Dependencies
- `pykalman`: For the Kalman Filter implementation
- `statsmodels`: For cointegration tests (coint, adfuller)
- `ccxt`: For exchange connectivity
- `pandas/numpy`: Data manipulation

## Mathematical Logic (Kalman Filter)
We treat the 'slope' (hedge ratio) and 'intercept' as hidden states that evolve as a Random Walk.
State Transition: beta[t] = beta[t-1] + w[t]  (w ~ Normal(0, delta))
Observation:      Y[t] = beta[t] * X[t] + alpha[t] + v[t]

## Code Snippet: Dynamic Hedge Ratio
class KalmanHedge:
    def __init__(self):
        self.delta = 1e-4
        self.wt = self.delta / (1 - self.delta) * np.eye(2)
        self.theta = np.zeros(2)
        self.P = np.zeros((2, 2))
        self.R = None

    def update(self, x, y):
        # x: Price of independent asset (e.g. BTC)
        # y: Price of dependent asset (e.g. ETH)
        
        # 1. Construct Observation Matrix F = [x, 1]
        F = np.asarray([x, 1.0]).reshape(1, 2)
        
        # 2. Predict State Covariance
        self.R = self.P + self.wt
        
        # 3. Calculate Prediction Error (Innovation)
        y_hat = F.dot(self.theta)
        et = y - y_hat
        
        # 4. Calculate Innovation Variance
        Qt = F.dot(self.R).dot(F.T) + 1.0 # Add measurement noise variance
        
        # 5. Calculate Kalman Gain
        Kt = self.R.dot(F.T) / Qt
        
        # 6. Update State Vector (Slope, Intercept)
        self.theta = self.theta + Kt.flatten() * et
        
        # 7. Update State Covariance
        self.P = self.R - Kt.dot(F).dot(self.R)
        
        # Return Z-Score for trading signal
        return et / np.sqrt(Qt)
```

***

## 3. Step-by-Step Execution Guide

### Phase 1: Research (Today)
1.  **Download Data:** Pull 1-hour data for top 50 coins for the last 90 days.
2.  **Run Clustering:** Use `sklearn.cluster.AffinityPropagation` to find natural groups.
3.  **Run Cointegration:** Use `statsmodels.tsa.stattools.coint` on pairs within clusters.
4.  **Visualize:** Plot the Spread ($Y - \beta X$) and Z-Score for the top 3 pairs (e.g., `ETC-ETH`, `NEAR-SOL`, `MATIC-ETH`). *Confirm visually that it mean-reverts.*

### Phase 2: Backtest (Tomorrow)
1.  **Code the Vectorized Backtest:**
    *   Do not use a loop. Calculate `z_score` columns for the whole dataframe at once.
    *   Apply entry/exit rules (`z > 2`, `z crosses 0`).
2.  **Costs:** Assume 0.06% fee per trade (0.12% round trip). This is critical. Stat Arb relies on many small wins; high fees kill it. (Use Binance BUSD/FDUSD pairs if zero-fee exists, or use limit orders to pay maker fees).

### Phase 3: Paper Trading (Next Week)
1.  Connect to Binance Testnet.
2.  Run the bot on 1-minute candles.
3.  Verify that `beta` updates correctly when one asset spikes but the other doesn't.

## Critical Risks to Watch
*   **Correlation Breakdown:** In a massive market crash (black swan), correlations go to 1.0. In a specific hack (e.g., SOL hack), correlations go to 0.0. The "Stop Loss at Z > 4.5" rule is your safety valve for this.
*   **Execution Latency:** If prices move fast, you might get filled on one leg but miss the other. Use "Market" orders for the second leg if the limit order isn't filled within 5 seconds.
