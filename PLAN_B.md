# Implementation Plan: Regime-Aware ML Trading System with Alternative Data

## Phase 1: Data Infrastructure & Feature Engineering (Week 1-2)

### Objective
Build robust data pipeline with order book, regime detection, and alternative features.

### Task 1.1: Order Book Data Collection

**Requirements:**
- Exchange: Binance (best liquidity/API) or Coinbase Advanced
- Symbols: BTC/USDT, ETH/USDT, SOL/USDT, ARB/USDT
- Depth: Top 20 levels bid/ask
- Frequency: Snapshot every 1-second, aggregate to 1m/5m/4h

**Implementation:**
```python
# File: data_collectors/orderbook_collector.py

import ccxt
import pandas as pd
import asyncio
from datetime import datetime

class OrderBookCollector:
    """
    Collect L2 order book snapshots from Binance
    Store: timestamp, symbol, bids[20], asks[20]
    """
    
    def __init__(self, symbols: list, depth: int = 20):
        self.exchange = ccxt.binance({'enableRateLimit': True})
        self.symbols = symbols  # ['BTC/USDT', 'ETH/USDT', ...]
        self.depth = depth
        
    async def fetch_orderbook_snapshot(self, symbol: str) -> dict:
        """
        Fetch single orderbook snapshot
        Returns: {
            'timestamp': int,
            'symbol': str,
            'bids': [[price, size], ...],  # top 20
            'asks': [[price, size], ...]
        }
        """
        ob = await self.exchange.fetch_order_book(symbol, limit=self.depth)
        return {
            'timestamp': ob['timestamp'],
            'symbol': symbol,
            'bids': ob['bids'][:self.depth],
            'asks': ob['asks'][:self.depth]
        }
    
    def calculate_ob_features(self, orderbook: dict) -> dict:
        """
        Extract microstructure features from raw orderbook
        Based on research: order book imbalance predicts short-term returns
        """
        bids = pd.DataFrame(orderbook['bids'], columns=['price', 'size'])
        asks = pd.DataFrame(orderbook['asks'], columns=['price', 'size'])
        
        # Volume-weighted features
        bid_volume = bids['size'].sum()
        ask_volume = asks['size'].sum()
        
        # OBI (Order Book Imbalance) - PRIMARY FEATURE
        obi = (bid_volume - ask_volume) / (bid_volume + ask_volume)
        
        # Depth imbalance at multiple levels
        obi_top5 = (bids.iloc[:5]['size'].sum() - asks.iloc[:5]['size'].sum()) / \
                   (bids.iloc[:5]['size'].sum() + asks.iloc[:5]['size'].sum())
        obi_top10 = (bids.iloc[:10]['size'].sum() - asks.iloc[:10]['size'].sum()) / \
                    (bids.iloc[:10]['size'].sum() + asks.iloc[:10]['size'].sum())
        
        # Spread metrics
        spread_abs = asks.iloc[0]['price'] - bids.iloc[0]['price']
        spread_bps = (spread_abs / bids.iloc[0]['price']) * 10000
        
        # Weighted mid price (better than simple mid)
        weighted_mid = (bids.iloc[0]['price'] * ask_volume + 
                       asks.iloc[0]['price'] * bid_volume) / (bid_volume + ask_volume)
        
        # Liquidity walls (detect large orders)
        bid_wall_3x = (bids['size'] > bids['size'].median() * 3).sum()
        ask_wall_3x = (asks['size'] > asks['size'].median() * 3).sum()
        
        return {
            'obi_full': obi,
            'obi_top5': obi_top5,
            'obi_top10': obi_top10,
            'spread_bps': spread_bps,
            'weighted_mid': weighted_mid,
            'bid_depth': bid_volume,
            'ask_depth': ask_volume,
            'bid_walls': bid_wall_3x,
            'ask_walls': ask_wall_3x,
            'depth_ratio': bid_volume / ask_volume if ask_volume > 0 else 0
        }

# Usage:
# collector = OrderBookCollector(['BTC/USDT', 'ETH/USDT'])
# Run continuously, store to PostgreSQL/TimescaleDB or Parquet files
```

**Storage Schema:**
```sql
-- PostgreSQL/TimescaleDB table
CREATE TABLE orderbook_features (
    timestamp TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    obi_full DOUBLE PRECISION,
    obi_top5 DOUBLE PRECISION,
    obi_top10 DOUBLE PRECISION,
    spread_bps DOUBLE PRECISION,
    weighted_mid DOUBLE PRECISION,
    bid_depth DOUBLE PRECISION,
    ask_depth DOUBLE PRECISION,
    bid_walls INTEGER,
    ask_walls INTEGER,
    depth_ratio DOUBLE PRECISION
);

SELECT create_hypertable('orderbook_features', 'timestamp');
CREATE INDEX ON orderbook_features (symbol, timestamp DESC);
```

### Task 1.2: Regime Detection with HMM

**Approach:**
Use Hidden Markov Model to detect 3-4 market states: Strong Bull, Weak Bull/Sideways, Weak Bear, Strong Bear. [pyquantlab](https://www.pyquantlab.com/articles/Market%20Regime%20Detection%20using%20Hidden%20Markov%20Models.html)

**Implementation:**
```python
# File: features/regime_detection.py

import pandas as pd
import numpy as np
from hmmlearn import hmm
from sklearn.preprocessing import StandardScaler

class RegimeDetector:
    """
    Detect market regimes using Gaussian HMM
    States: 0=Strong Bear, 1=Weak Bear, 2=Weak Bull, 3=Strong Bull
    """
    
    def __init__(self, n_states=4, random_state=42):
        self.n_states = n_states
        self.model = hmm.GaussianHMM(
            n_components=n_states,
            covariance_type="full",
            n_iter=1000,
            random_state=random_state
        )
        self.scaler = StandardScaler()
        self.state_labels = None
        
    def prepare_features(self, df: pd.DataFrame) -> np.ndarray:
        """
        Prepare regime detection features from OHLCV data
        Features: returns, volatility, volume_ratio
        """
        df = df.copy()
        
        # Returns (momentum signal)
        df['returns'] = df['close'].pct_change()
        
        # Realized volatility (20-period rolling std of returns)
        df['volatility'] = df['returns'].rolling(20).std()
        
        # Volume ratio (current vol / 20-day average)
        df['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean()
        
        # Trend strength (close position in range)
        df['trend'] = (df['close'] - df['low'].rolling(20).min()) / \
                     (df['high'].rolling(20).max() - df['low'].rolling(20).min())
        
        # Select features and drop NaN
        features = df[['returns', 'volatility', 'volume_ratio', 'trend']].dropna()
        
        return features
    
    def fit(self, df: pd.DataFrame):
        """
        Train HMM on historical data
        """
        features = self.prepare_features(df)
        X_scaled = self.scaler.fit_transform(features)
        
        self.model.fit(X_scaled)
        
        # Predict states on training data to label them
        states = self.model.predict(X_scaled)
        
        # Calculate mean returns per state to label bull/bear
        feature_df = features.copy()
        feature_df['state'] = states
        
        state_returns = feature_df.groupby('state')['returns'].mean().sort_values()
        
        # Map states: lowest return = strong bear (0), highest = strong bull (3)
        self.state_labels = {
            old: new for new, old in enumerate(state_returns.index)
        }
        
        print("State characterization:")
        for old_state, new_state in self.state_labels.items():
            stats = feature_df[feature_df['state'] == old_state].agg({
                'returns': 'mean',
                'volatility': 'mean'
            })
            regime_name = ['Strong Bear', 'Weak Bear', 'Weak Bull', 'Strong Bull'][new_state]
            print(f"  State {new_state} ({regime_name}): "
                  f"Return={stats['returns']:.4f}, Vol={stats['volatility']:.4f}")
        
        return self
    
    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """
        Predict regime for new data
        Returns: array of regime labels (0-3)
        """
        features = self.prepare_features(df)
        X_scaled = self.scaler.transform(features)
        
        states = self.model.predict(X_scaled)
        
        # Remap states to labeled regimes
        labeled_states = np.array([self.state_labels[s] for s in states])
        
        return labeled_states
    
    def predict_online(self, recent_df: pd.DataFrame) -> int:
        """
        Predict current regime given recent bars (for live trading)
        """
        states = self.predict(recent_df)
        return states[-1]  # Return most recent regime

# Usage:
# detector = RegimeDetector(n_states=4)
# detector.fit(historical_4h_data)
# current_regime = detector.predict_online(last_100_bars)
```

### Task 1.3: Alternative Feature Engineering

**Implementation:**
```python
# File: features/alternative_features.py

import pandas as pd
import numpy as np

class AlternativeFeatures:
    """
    Extract non-TA features: cross-asset, sentiment proxies, market breadth
    """
    
    @staticmethod
    def add_cross_asset_features(df_dict: dict) -> pd.DataFrame:
        """
        df_dict = {
            'BTC': btc_df,
            'ETH': eth_df,
            'SOL': sol_df,
            'ARB': arb_df
        }
        Returns: DataFrame with cross-asset features
        """
        # BTC dominance proxy
        btc_dominance = df_dict['BTC']['close'] / (
            df_dict['BTC']['close'] + 
            df_dict['ETH']['close'] + 
            df_dict['SOL']['close'] + 
            df_dict['ARB']['close']
        )
        
        # ETH/BTC ratio (altcoin strength)
        eth_btc_ratio = df_dict['ETH']['close'] / df_dict['BTC']['close']
        
        # Correlation features (20-bar rolling)
        corr_eth_btc = df_dict['ETH']['returns'].rolling(20).corr(df_dict['BTC']['returns'])
        corr_sol_btc = df_dict['SOL']['returns'].rolling(20).corr(df_dict['BTC']['returns'])
        
        # Market breadth: % of assets with positive returns
        returns_df = pd.DataFrame({
            symbol: df['returns'] for symbol, df in df_dict.items()
        })
        breadth = (returns_df > 0).sum(axis=1) / len(df_dict)
        
        # Relative strength: asset return vs market average
        market_return = returns_df.mean(axis=1)
        
        features = pd.DataFrame({
            'btc_dominance': btc_dominance,
            'eth_btc_ratio': eth_btc_ratio,
            'corr_eth_btc': corr_eth_btc,
            'corr_sol_btc': corr_sol_btc,
            'market_breadth': breadth,
            'market_return': market_return
        })
        
        return features
    
    @staticmethod
    def add_funding_rate_features(symbol: str, funding_df: pd.DataFrame) -> pd.DataFrame:
        """
        Funding rate as sentiment proxy (positive = bullish, negative = bearish)
        Get from: ccxt.binance.fetch_funding_rate_history()
        """
        features = pd.DataFrame(index=funding_df.index)
        
        # Raw funding rate
        features['funding_rate'] = funding_df['fundingRate']
        
        # Rolling averages
        features['funding_ma8'] = features['funding_rate'].rolling(8).mean()
        features['funding_ma24'] = features['funding_rate'].rolling(24).mean()
        
        # Funding rate momentum
        features['funding_momentum'] = features['funding_rate'] - features['funding_ma24']
        
        # Extreme funding (potential reversal signal)
        features['funding_extreme'] = np.where(
            features['funding_rate'].abs() > features['funding_rate'].rolling(100).quantile(0.90),
            np.sign(features['funding_rate']),
            0
        )
        
        return features

# Usage:
# alt_features = AlternativeFeatures()
# cross_features = alt_features.add_cross_asset_features({
#     'BTC': btc_4h, 'ETH': eth_4h, 'SOL': sol_4h, 'ARB': arb_4h
# })
```

***

## Phase 2: Meta-Labeling & Triple Barrier Method (Week 2)

### Objective
Implement proper label engineering using triple-barrier method + meta-labeling. [mlfinpy.readthedocs](https://mlfinpy.readthedocs.io/en/latest/Labelling.html)

### Task 2.1: Triple Barrier Labeling

**Implementation:**
```python
# File: labeling/triple_barrier.py

import pandas as pd
import numpy as np
from typing import Optional

class TripleBarrierLabeler:
    """
    Implement triple-barrier method from 'Advances in Financial Machine Learning'
    Labels: 1 (profit target hit first), 0 (stop loss hit first), -1 (time exit)
    """
    
    def __init__(
        self,
        profit_target_pct: float = 0.03,  # 3% take profit
        stop_loss_pct: float = 0.015,     # 1.5% stop loss
        max_holding_bars: int = 20,        # Max 20 bars (e.g., 80h on 4h timeframe)
        min_return_threshold: float = 0.005  # Minimum 0.5% move to be considered
    ):
        self.pt_pct = profit_target_pct
        self.sl_pct = stop_loss_pct
        self.max_holding = max_holding_bars
        self.min_return = min_return_threshold
        
    def apply_barriers(
        self,
        close_prices: pd.Series,
        events: pd.DataFrame,  # columns: ['side'] where side=1 for long, -1 for short
        volatility: Optional[pd.Series] = None
    ) -> pd.DataFrame:
        """
        Apply triple barriers to events
        
        events DataFrame must have:
        - index: entry timestamps
        - 'side': 1 for long, -1 for short predictions
        
        Returns: DataFrame with columns:
        - 't1': timestamp when barrier was hit
        - 'target': label (1=profit, 0=loss, -1=time)
        - 'return': actual return achieved
        """
        out = events.copy()
        
        # Dynamic barriers based on volatility if provided
        if volatility is not None:
            pt_dynamic = self.pt_pct * volatility
            sl_dynamic = self.sl_pct * volatility
        else:
            pt_dynamic = self.pt_pct
            sl_dynamic = self.sl_pct
        
        # Calculate barrier levels for each event
        out['pt_level'] = 1 + pt_dynamic
        out['sl_level'] = 1 - sl_dynamic
        
        # Find which barrier was hit first
        results = []
        
        for idx, row in out.iterrows():
            entry_price = close_prices.loc[idx]
            side = row['side']
            pt_level = row['pt_level']
            sl_level = row['sl_level']
            
            # Get future prices (max_holding bars ahead)
            idx_pos = close_prices.index.get_loc(idx)
            end_pos = min(idx_pos + self.max_holding, len(close_prices))
            future_prices = close_prices.iloc[idx_pos+1:end_pos]
            
            if len(future_prices) == 0:
                results.append({'t1': idx, 'target': -1, 'return': 0.0})
                continue
            
            # Calculate returns from entry
            returns = (future_prices / entry_price - 1) * side
            
            # Check profit target
            hit_profit = returns >= (pt_level - 1)
            # Check stop loss
            hit_loss = returns <= -(sl_level - 1)
            
            # Find first touch
            profit_idx = hit_profit.idxmax() if hit_profit.any() else None
            loss_idx = hit_loss.idxmax() if hit_loss.any() else None
            
            if profit_idx is not None and loss_idx is not None:
                # Both hit - which came first?
                if close_prices.index.get_loc(profit_idx) < close_prices.index.get_loc(loss_idx):
                    exit_time = profit_idx
                    label = 1
                else:
                    exit_time = loss_idx
                    label = 0
            elif profit_idx is not None:
                exit_time = profit_idx
                label = 1
            elif loss_idx is not None:
                exit_time = loss_idx
                label = 0
            else:
                # Time barrier hit (neither profit nor loss)
                exit_time = future_prices.index[-1]
                label = -1
            
            exit_price = close_prices.loc[exit_time]
            actual_return = (exit_price / entry_price - 1) * side
            
            results.append({
                't1': exit_time,
                'target': label,
                'return': actual_return
            })
        
        # Merge results
        results_df = pd.DataFrame(results, index=out.index)
        out = out.join(results_df)
        
        # Filter by minimum return threshold
        out = out[out['return'].abs() >= self.min_return]
        
        return out[['t1', 'target', 'return']]

# Usage:
# labeler = TripleBarrierLabeler(profit_target_pct=0.03, stop_loss_pct=0.015)
# events = pd.DataFrame({'side': 1}, index=signal_timestamps)  # All long signals
# labels = labeler.apply_barriers(df['close'], events)
```

### Task 2.2: Meta-Labeling Implementation

**Approach:**
First get signals from a simple baseline strategy, then train XGBoost to predict which signals to take. [reddit](https://www.reddit.com/r/algotrading/comments/1lnm48w/meta_labeling_for_algorithmic_trading_how_to/)

**Implementation:**
```python
# File: labeling/meta_labeling.py

import pandas as pd
import numpy as np

class MetaLabeler:
    """
    Meta-labeling: Use ML to predict which primary model signals to take
    
    Workflow:
    1. Primary model generates signals (can be simple: RSI, MA crossover, etc.)
    2. Triple-barrier method labels which signals were profitable
    3. Secondary ML model predicts: should we take this signal? (1=yes, 0=no)
    """
    
    @staticmethod
    def create_primary_signals(df: pd.DataFrame, strategy='momentum') -> pd.Series:
        """
        Generate simple baseline signals
        These don't need to be highly profitable - just directional
        """
        if strategy == 'momentum':
            # Simple momentum: price > 50 MA and RSI > 50
            ma50 = df['close'].rolling(50).mean()
            
            # RSI calculation
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            signals = ((df['close'] > ma50) & (rsi > 50)).astype(int)
            
        elif strategy == 'mean_reversion':
            # Mean reversion: price 2 std below 20 MA
            ma20 = df['close'].rolling(20).mean()
            std20 = df['close'].rolling(20).std()
            
            signals = (df['close'] < (ma20 - 2 * std20)).astype(int)
        
        # Convert to side: 1 for long signal, 0 for no signal
        return signals
    
    @staticmethod
    def prepare_meta_features(
        df: pd.DataFrame,
        orderbook_features: pd.DataFrame,
        regime: pd.Series,
        alt_features: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Prepare features for the meta-model
        These help decide: "Given a primary signal, should we take it?"
        """
        features = pd.DataFrame(index=df.index)
        
        # Market microstructure
        features['obi_full'] = orderbook_features['obi_full']
        features['obi_top5'] = orderbook_features['obi_top5']
        features['spread_bps'] = orderbook_features['spread_bps']
        features['depth_ratio'] = orderbook_features['depth_ratio']
        
        # Regime context
        features['regime'] = regime
        features['is_bull_regime'] = (regime >= 2).astype(int)  # States 2,3 = bull
        features['is_high_vol_regime'] = regime.isin([0, 3]).astype(int)  # Extreme states
        
        # Volatility context
        returns = df['close'].pct_change()
        features['volatility_20'] = returns.rolling(20).std()
        features['volatility_rank'] = returns.rolling(100).apply(
            lambda x: (x.iloc[-1] < x).sum() / len(x)
        )
        
        # Trend strength
        features['trend_strength'] = (df['close'] - df['close'].rolling(50).min()) / \
                                    (df['close'].rolling(50).max() - df['close'].rolling(50).min())
        
        # Cross-asset features
        if 'market_breadth' in alt_features.columns:
            features['market_breadth'] = alt_features['market_breadth']
            features['eth_btc_ratio'] = alt_features['eth_btc_ratio']
        
        # Volume context
        features['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean()
        
        # Time features (session effects)
        features['hour'] = df.index.hour
        features['day_of_week'] = df.index.dayofweek
        
        return features

# Complete workflow example:
# 1. Generate primary signals
# meta_labeler = MetaLabeler()
# primary_signals = meta_labeler.create_primary_signals(df, strategy='momentum')
#
# 2. Apply triple barriers to label which signals were profitable
# events = pd.DataFrame({'side': 1}, index=df[primary_signals==1].index)
# labeler = TripleBarrierLabeler()
# labels = labeler.apply_barriers(df['close'], events)
#
# 3. Prepare meta-features
# meta_features = meta_labeler.prepare_meta_features(df, ob_features, regime, alt_features)
#
# 4. Train XGBoost to predict labels['target'] using meta_features
# (This becomes Task 3.1)
```

***

## Phase 3: Regime-Specific Model Training (Week 3)

### Objective
Train separate XGBoost models per regime with proper validation. [blog.quantinsti](https://blog.quantinsti.com/regime-adaptive-trading-python/)

### Task 3.1: Train Regime-Specific Models

**Implementation:**
```python
# File: models/regime_specific_xgb.py

import xgboost as xgb
import pandas as pd
import numpy as np
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
import joblib

class RegimeSpecificModels:
    """
    Train separate XGBoost models for each market regime
    """
    
    def __init__(self, n_regimes=4):
        self.n_regimes = n_regimes
        self.models = {}  # {regime_id: trained_model}
        self.feature_importance = {}
        
    def train_all_regimes(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        regimes: pd.Series,
        validation_split=0.2
    ):
        """
        Train one model per regime
        
        X: features (from meta-labeling preparation)
        y: labels (from triple-barrier: 1=profit, 0=loss, exclude -1)
        regimes: regime labels (0-3)
        """
        # Remove time exits (label=-1) - only train on profit/loss
        valid_idx = y != -1
        X = X[valid_idx]
        y = y[valid_idx]
        regimes = regimes[valid_idx]
        
        # Split train/validation by time
        split_idx = int(len(X) * (1 - validation_split))
        X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]
        regimes_train, regimes_val = regimes.iloc[:split_idx], regimes.iloc[split_idx:]
        
        print(f"\n{'='*60}")
        print("TRAINING REGIME-SPECIFIC MODELS")
        print(f"{'='*60}\n")
        
        # Train model for each regime
        for regime_id in range(self.n_regimes):
            print(f"\n--- Regime {regime_id} ---")
            
            # Filter data for this regime
            train_mask = regimes_train == regime_id
            val_mask = regimes_val == regime_id
            
            X_regime_train = X_train[train_mask]
            y_regime_train = y_train[train_mask]
            X_regime_val = X_val[val_mask]
            y_regime_val = y_val[val_mask]
            
            if len(X_regime_train) < 100:
                print(f"⚠️  Insufficient data for regime {regime_id} (n={len(X_regime_train)})")
                continue
            
            print(f"Train samples: {len(X_regime_train)}, Val samples: {len(X_regime_val)}")
            print(f"Train win rate: {y_regime_train.mean():.2%}")
            
            # XGBoost parameters - conservative to avoid overfitting
            params = {
                'objective': 'binary:logistic',
                'eval_metric': 'auc',
                'max_depth': 4,  # Shallow trees
                'learning_rate': 0.05,
                'subsample': 0.8,
                'colsample_bytree': 0.8,
                'min_child_weight': 5,
                'gamma': 0.1,
                'reg_alpha': 0.1,
                'reg_lambda': 1.0,
                'scale_pos_weight': len(y_regime_train[y_regime_train==0]) / len(y_regime_train[y_regime_train==1]),  # Handle imbalance
                'random_state': 42
            }
            
            # Train with early stopping
            dtrain = xgb.DMatrix(X_regime_train, label=y_regime_train)
            dval = xgb.DMatrix(X_regime_val, label=y_regime_val)
            
            evals = [(dtrain, 'train'), (dval, 'val')]
            model = xgb.train(
                params,
                dtrain,
                num_boost_round=500,
                evals=evals,
                early_stopping_rounds=30,
                verbose_eval=50
            )
            
            # Evaluate
            y_pred_proba = model.predict(dval)
            y_pred = (y_pred_proba > 0.5).astype(int)
            
            acc = accuracy_score(y_regime_val, y_pred)
            prec = precision_score(y_regime_val, y_pred, zero_division=0)
            rec = recall_score(y_regime_val, y_pred, zero_division=0)
            f1 = f1_score(y_regime_val, y_pred, zero_division=0)
            
            print(f"\nValidation Metrics:")
            print(f"  Accuracy:  {acc:.2%}")
            print(f"  Precision: {prec:.2%}")
            print(f"  Recall:    {rec:.2%}")
            print(f"  F1 Score:  {f1:.2%}")
            
            # Feature importance
            importance = model.get_score(importance_type='gain')
            self.feature_importance[regime_id] = importance
            
            print(f"\nTop 5 Features:")
            sorted_importance = sorted(importance.items(), key=lambda x: x [pyquantlab](https://www.pyquantlab.com/articles/Market%20Regime%20Detection%20using%20Hidden%20Markov%20Models.html), reverse=True)[:5]
            for feat, score in sorted_importance:
                print(f"  {feat}: {score:.2f}")
            
            # Save model
            self.models[regime_id] = model
        
        print(f"\n{'='*60}")
        print(f"Training complete. {len(self.models)} models trained.")
        print(f"{'='*60}\n")
        
        return self
    
    def predict(self, X: pd.DataFrame, current_regime: int, confidence_threshold=0.6):
        """
        Predict using regime-specific model
        
        Returns: (prediction, confidence)
        - prediction: 1=take trade, 0=skip
        - confidence: model probability
        """
        if current_regime not in self.models:
            # No model for this regime - don't trade
            return 0, 0.0
        
        model = self.models[current_regime]
        dmatrix = xgb.DMatrix(X)
        
        proba = model.predict(dmatrix)[0]
        
        # Only take trade if confidence exceeds threshold
        prediction = 1 if proba >= confidence_threshold else 0
        
        return prediction, proba
    
    def save(self, path_prefix='models/regime_model'):
        """Save all models"""
        for regime_id, model in self.models.items():
            model.save_model(f"{path_prefix}_regime{regime_id}.json")
        
        # Save metadata
        metadata = {
            'n_regimes': self.n_regimes,
            'feature_importance': self.feature_importance
        }
        joblib.dump(metadata, f"{path_prefix}_metadata.pkl")
        
        print(f"✓ Saved {len(self.models)} models to {path_prefix}_regime*.json")
    
    def load(self, path_prefix='models/regime_model'):
        """Load all models"""
        metadata = joblib.dump(f"{path_prefix}_metadata.pkl")
        self.n_regimes = metadata['n_regimes']
        self.feature_importance = metadata['feature_importance']
        
        for regime_id in range(self.n_regimes):
            model_path = f"{path_prefix}_regime{regime_id}.json"
            try:
                model = xgb.Booster()
                model.load_model(model_path)
                self.models[regime_id] = model
            except:
                print(f"⚠️  Model for regime {regime_id} not found")
        
        print(f"✓ Loaded {len(self.models)} models")
        return self

# Usage:
# regime_models = RegimeSpecificModels(n_regimes=4)
# regime_models.train_all_regimes(meta_features, labels, regimes_series)
# regime_models.save()
```

***

## Phase 4: Walk-Forward Backtesting (Week 3-4)

### Objective
Implement proper walk-forward validation with regime detection. [blog.quantinsti](https://blog.quantinsti.com/regime-adaptive-trading-python/)

### Task 4.1: Walk-Forward Backtest Engine

**Implementation:**
```python
# File: backtesting/walk_forward.py

import pandas as pd
import numpy as np
from typing import Dict, Tuple

class WalkForwardBacktest:
    """
    Walk-forward backtesting with regime detection and model retraining
    """
    
    def __init__(
        self,
        train_window_days=180,
        test_window_days=30,
        retrain_frequency_days=30
    ):
        self.train_window = train_window_days
        self.test_window = test_window_days
        self.retrain_freq = retrain_frequency_days
        
    def run(
        self,
        df: pd.DataFrame,
        orderbook_features: pd.DataFrame,
        alt_features: pd.DataFrame,
        regime_detector: RegimeDetector,
        meta_labeler: MetaLabeler,
        labeler: TripleBarrierLabeler
    ) -> pd.DataFrame:
        """
        Full walk-forward backtest
        
        Returns: DataFrame with trade log (entry_time, exit_time, return, regime, etc.)
        """
        trades = []
        
        # Get date range
        start_date = df.index[0]
        end_date = df.index[-1]
        
        current_date = start_date + pd.Timedelta(days=self.train_window)
        
        print(f"\n{'='*80}")
        print(f"WALK-FORWARD BACKTEST: {start_date.date()} to {end_date.date()}")
        print(f"{'='*80}\n")
        
        while current_date + pd.Timedelta(days=self.test_window) <= end_date:
            print(f"\n--- Period: {current_date.date()} ---")
            
            # 1. Training window
            train_start = current_date - pd.Timedelta(days=self.train_window)
            train_end = current_date
            
            train_data = df[train_start:train_end]
            print(f"Train: {train_start.date()} to {train_end.date()} ({len(train_data)} bars)")
            
            # 2. Fit regime detector on training data
            regime_detector.fit(train_data)
            
            # 3. Generate regimes for full training period
            train_regimes = regime_detector.predict(train_data)
            
            # 4. Generate primary signals
            primary_signals = meta_labeler.create_primary_signals(train_data)
            
            # 5. Label signals with triple barrier
            events = pd.DataFrame(
                {'side': 1},
                index=train_data[primary_signals == 1].index
            )
            labels = labeler.apply_barriers(train_data['close'], events)
            
            # 6. Prepare meta features
            train_ob = orderbook_features[train_start:train_end]
            train_alt = alt_features[train_start:train_end]
            train_regime_series = pd.Series(train_regimes, index=train_data.index)
            
            meta_features = meta_labeler.prepare_meta_features(
                train_data,
                train_ob,
                train_regime_series,
                train_alt
            )
            
            # 7. Train regime-specific models
            # Align features with labels
            common_idx = meta_features.index.intersection(labels.index)
            X_train = meta_features.loc[common_idx]
            y_train = labels.loc[common_idx, 'target']
            regimes_train = train_regime_series.loc[common_idx]
            
            regime_models = RegimeSpecificModels(n_regimes=4)
            regime_models.train_all_regimes(
                X_train,
                y_train,
                regimes_train,
                validation_split=0.2
            )
            
            # 8. Test window
            test_start = train_end
            test_end = test_start + pd.Timedelta(days=self.test_window)
            
            test_data = df[test_start:test_end]
            print(f"\nTest: {test_start.date()} to {test_end.date()} ({len(test_data)} bars)")
            
            if len(test_data) == 0:
                break
            
            # 9. Generate test predictions
            test_regimes = regime_detector.predict(test_data)
            test_regime_series = pd.Series(test_regimes, index=test_data.index)
            
            test_primary_signals = meta_labeler.create_primary_signals(test_data)
            
            test_ob = orderbook_features[test_start:test_end]
            test_alt = alt_features[test_start:test_end]
            
            test_meta_features = meta_labeler.prepare_meta_features(
                test_data,
                test_ob,
                test_regime_series,
                test_alt
            )
            
            # 10. Generate trades
            for idx in test_data[test_primary_signals == 1].index:
                if idx not in test_meta_features.index:
                    continue
                
                current_regime = test_regime_series.loc[idx]
                features = test_meta_features.loc[[idx]]
                
                # Get prediction from regime-specific model
                prediction, confidence = regime_models.predict(
                    features,
                    current_regime,
                    confidence_threshold=0.6
                )
                
                if prediction == 1:
                    # Take this trade
                    entry_price = test_data.loc[idx, 'close']
                    
                    # Simulate trade execution with triple barrier
                    # (In real backtest, need to check actual exit)
                    
                    # For now, record the signal
                    trades.append({
                        'entry_time': idx,
                        'entry_price': entry_price,
                        'regime': current_regime,
                        'confidence': confidence,
                        'period_start': test_start,
                        'period_end': test_end
                    })
            
            print(f"Signals generated: {len([t for t in trades if t['period_start'] == test_start])}")
            
            # Move to next period
            current_date += pd.Timedelta(days=self.retrain_freq)
        
        # Convert to DataFrame
        trades_df = pd.DataFrame(trades)
        
        print(f"\n{'='*80}")
        print(f"Backtest complete. Total signals: {len(trades_df)}")
        print(f"{'='*80}\n")
        
        return trades_df
    
    def calculate_returns(self, trades_df: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate actual returns for each trade using triple barrier
        """
        # Apply triple barrier to each trade
        labeler = TripleBarrierLabeler()
        
        for idx, trade in trades_df.iterrows():
            entry_time = trade['entry_time']
            entry_price = trade['entry_price']
            
            # Get future prices
            entry_loc = df.index.get_loc(entry_time)
            future_window = df.iloc[entry_loc:entry_loc+20]  # Max 20 bars
            
            # Apply barriers
            events = pd.DataFrame({'side': 1}, index=[entry_time])
            result = labeler.apply_barriers(df['close'], events)
            
            if len(result) > 0:
                trades_df.loc[idx, 'exit_time'] = result.loc[entry_time, 't1']
                trades_df.loc[idx, 'return'] = result.loc[entry_time, 'return']
                trades_df.loc[idx, 'outcome'] = result.loc[entry_time, 'target']
        
        return trades_df

# Usage:
# backtest = WalkForwardBacktest(train_window_days=180, test_window_days=30)
# trades = backtest.run(df_4h, ob_features, alt_features, detector, meta_labeler, labeler)
# trades_with_returns = backtest.calculate_returns(trades, df_4h)
```

***

## Phase 5: Evaluation & Iteration (Week 4)

### Task 5.1: Performance Analysis

**Metrics to track:**
```python
# File: evaluation/metrics.py

import pandas as pd
import numpy as np

def analyze_backtest_results(trades_df: pd.DataFrame, initial_capital=10000):
    """
    Comprehensive performance analysis
    """
    print(f"\n{'='*80}")
    print("BACKTEST RESULTS")
    print(f"{'='*80}\n")
    
    # Basic stats
    total_trades = len(trades_df)
    winning_trades = len(trades_df[trades_df['return'] > 0])
    losing_trades = len(trades_df[trades_df['return'] < 0])
    
    win_rate = winning_trades / total_trades if total_trades > 0 else 0
    
    print(f"Total Trades: {total_trades}")
    print(f"Winning: {winning_trades} ({win_rate:.2%})")
    print(f"Losing: {losing_trades} ({(1-win_rate):.2%})")
    
    # Return statistics
    avg_return = trades_df['return'].mean()
    avg_win = trades_df[trades_df['return'] > 0]['return'].mean()
    avg_loss = trades_df[trades_df['return'] < 0]['return'].mean()
    
    print(f"\nReturn Statistics:")
    print(f"  Avg Return: {avg_return:.2%}")
    print(f"  Avg Win: {avg_win:.2%}")
    print(f"  Avg Loss: {avg_loss:.2%}")
    print(f"  Win/Loss Ratio: {abs(avg_win/avg_loss):.2f}x")
    
    # Risk metrics
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
    print(f"\nExpectancy: {expectancy:.2%}")
    
    # Equity curve
    trades_df = trades_df.sort_values('entry_time')
    trades_df['cumulative_return'] = (1 + trades_df['return']).cumprod() - 1
    
    total_return = trades_df['cumulative_return'].iloc[-1]
    max_drawdown = (trades_df['cumulative_return'] - trades_df['cumulative_return'].cummax()).min()
    
    print(f"\nPortfolio Metrics:")
    print(f"  Total Return: {total_return:.2%}")
    print(f"  Max Drawdown: {max_drawdown:.2%}")
    
    # Sharpe ratio (annualized, assuming 4h bars)
    returns_per_trade = trades_df['return']
    sharpe = (returns_per_trade.mean() / returns_per_trade.std()) * np.sqrt(365*24/4) if returns_per_trade.std() > 0 else 0
    print(f"  Sharpe Ratio: {sharpe:.2f}")
    
    # Regime breakdown
    print(f"\nPerformance by Regime:")
    for regime in sorted(trades_df['regime'].unique()):
        regime_trades = trades_df[trades_df['regime'] == regime]
        regime_wr = (regime_trades['return'] > 0).mean()
        regime_avg = regime_trades['return'].mean()
        print(f"  Regime {regime}: {len(regime_trades)} trades, WR={regime_wr:.2%}, Avg={regime_avg:.2%}")
    
    # Decision: Is this profitable?
    print(f"\n{'='*80}")
    if expectancy > 0.003 and win_rate > 0.40 and sharpe > 1.0:
        print("✓ VERDICT: POTENTIALLY PROFITABLE - Consider paper trading")
    elif expectancy > 0 and win_rate > 0.35:
        print("⚠ VERDICT: MARGINAL - Needs improvement")
    else:
        print("✗ VERDICT: UNPROFITABLE - Do not trade")
    print(f"{'='*80}\n")

# Usage:
# analyze_backtest_results(trades_with_returns)
```

***

## Summary: Execution Checklist

```markdown
## Week 1-2: Data & Features
- [ ] Set up order book data collector (Binance WebSocket)
- [ ] Implement regime detector with HMM
- [ ] Build alternative feature pipeline
- [ ] Store data in PostgreSQL/TimescaleDB
- [ ] Collect 6+ months of historical data

## Week 2: Labeling
- [ ] Implement triple-barrier labeling
- [ ] Create primary signal generator
- [ ] Build meta-labeling pipeline
- [ ] Validate labels on historical data

## Week 3: Model Training
- [ ] Train regime-specific XGBoost models
- [ ] Implement confidence thresholding
- [ ] Save/load model infrastructure
- [ ] Feature importance analysis

## Week 4: Backtesting & Evaluation
- [ ] Walk-forward backtest implementation
- [ ] Performance metrics calculation
- [ ] Regime-specific analysis
- [ ] Decision: profitable or not?

## If Profitable (>60% accuracy, positive expectancy):
- [ ] Paper trading for 30 days
- [ ] Monitor live performance vs backtest
- [ ] Gradual capital allocation
```

This plan addresses all your identified issues: regime blindness, feature limitations, poor label engineering, and lack of signal selectivity. The meta-labeling approach transforms the problem from "predict market direction" to "filter which signals to take," which is significantly easier and has been shown to work in practice. [mlfinpy.readthedocs](https://mlfinpy.readthedocs.io/en/latest/Labelling.html)
