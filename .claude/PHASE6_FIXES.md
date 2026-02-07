# Phase 6 Code Fixes - Implementation Guide

## Issue #1: Missing Fee & Slippage in PnL (CRITICAL)

### Current Code
**File:** `internal/execution/engine.go` (Lines 149-173)
```go
func (e *Engine) ClosePosition(symbol string, side string, price, size float64, reason string, signalType strategy.SignalType, entryPrice float64, entryTime time.Time) (*Order, error) {
    // ... order execution ...
    
    e.mu.Lock()
    e.orders[order.ID] = order

    // Record trade
    var pnl float64
    if side == "LONG" {
        pnl = (order.FilledPrice - entryPrice) * size        // WRONG: no fees
    } else {
        pnl = (entryPrice - order.FilledPrice) * size        // WRONG: no fees
    }

    trade := &Trade{
        Symbol:     symbol,
        Side:       side,
        EntryPrice: entryPrice,
        ExitPrice:  order.FilledPrice,
        Size:       size,
        EntryTime:  entryTime,
        ExitTime:   time.Now(),
        PnL:        pnl,
        ExitReason: reason,
        SignalType: signalType,
    }
    e.trades = append(e.trades, trade)
    e.mu.Unlock()

    return order, nil
}
```

### Fixed Code
```go
func (e *Engine) ClosePosition(symbol string, side string, price, size float64, reason string, signalType strategy.SignalType, entryPrice float64, entryTime time.Time) (*Order, error) {
    // ... order execution ...
    
    e.mu.Lock()
    defer e.mu.Unlock()
    e.orders[order.ID] = order

    // Calculate PnL with fees and slippage
    // Both entry and exit have fees
    entryFees := entryPrice * size * (e.config.FeePercent / 100.0)
    exitFees := order.FilledPrice * size * (e.config.FeePercent / 100.0)
    
    // Slippage applies on both sides
    exitSlippage := order.FilledPrice * size * (e.config.SlippageBP / 10000.0)
    
    var grossPnL float64
    if side == "LONG" {
        // LONG: profit from price increase
        // Costs: entry fees + exit fees + exit slippage
        grossPnL = (order.FilledPrice - entryPrice) * size
    } else {
        // SHORT: profit from price decrease
        // Costs: entry fees + exit fees + exit slippage
        grossPnL = (entryPrice - order.FilledPrice) * size
    }
    
    netPnL := grossPnL - entryFees - exitFees - exitSlippage

    trade := &Trade{
        Symbol:     symbol,
        Side:       side,
        EntryPrice: entryPrice,
        ExitPrice:  order.FilledPrice,
        Size:       size,
        EntryTime:  entryTime,
        ExitTime:   time.Now(),
        PnL:        netPnL,
        ExitReason: reason,
        SignalType: signalType,
    }
    e.trades = append(e.trades, trade)

    return order, nil
}
```

---

## Issue #2: Position State Race Condition (HIGH)

### Problem
- Engine opens orders without coordinating with risk manager
- Risk manager tracks positions separately
- Can open duplicate positions

### Solution: Unified Position Lifecycle

**File:** `internal/execution/engine.go`

Modify OpenPosition to call risk manager:

```go
// BEFORE: Takes only signal and size
func (e *Engine) OpenPosition(signal *strategy.Signal, size float64) (*Order, error) {

// AFTER: Takes signal, size, AND risk manager
func (e *Engine) OpenPosition(signal *strategy.Signal, size float64, rm *risk.Manager) (*Order, error) {
    if signal == nil {
        return nil, fmt.Errorf("signal is nil")
    }

    // 1. Check if we can open (BEFORE executing order)
    if err := rm.CanOpenPosition(signal.Symbol); err != nil {
        return nil, fmt.Errorf("risk check failed: %w", err)
    }

    // 2. Determine side
    var side OrderSide
    if signal.Type == strategy.SignalLong {
        side = OrderSideBuy
    } else if signal.Type == strategy.SignalShort {
        side = OrderSideSell
    } else {
        return nil, fmt.Errorf("invalid signal type: %s", signal.Type)
    }

    // 3. Execute the order
    var order *Order
    var err error
    if e.config.UseLimitOrders {
        order, err = e.executor.ExecuteLimitOrder(signal.Symbol, side, signal.Price, size)
    } else {
        order, err = e.executor.ExecuteMarketOrder(signal.Symbol, side, size)
    }

    if err != nil {
        return nil, fmt.Errorf("failed to execute order: %w", err)
    }

    if order == nil || order.Status == OrderStatusRejected {
        return nil, fmt.Errorf("order rejected or returned nil")
    }

    // 4. Register position in risk manager (AFTER successful order)
    //    Use a write lock to ensure atomic registration
    sideName := "LONG"
    if side == OrderSideSell {
        sideName = "SHORT"
    }

    riskAmount := rm.GetEquity() * (rm.GetConfig().MaxRiskPerTradePct / 100.0)
    if err := rm.OpenPosition(
        signal.Symbol, 
        sideName, 
        signal.Price, 
        size, 
        signal.StopLoss, 
        signal.TakeProfit, 
        riskAmount,
    ); err != nil {
        // Position opened but couldn't register - need to cancel order
        if cancelErr := e.executor.CancelOrder(order.ID); cancelErr != nil {
            // Log critical: order placed but can't cancel
            // TODO: add logging
        }
        return nil, fmt.Errorf("failed to register position: %w", err)
    }

    // 5. Track order in engine
    e.mu.Lock()
    e.orders[order.ID] = order
    e.mu.Unlock()

    return order, nil
}
```

**Add getter to Manager for config:**

```go
// File: internal/risk/manager.go
func (m *Manager) GetConfig() Config {
    m.mu.RLock()
    defer m.mu.RUnlock()
    return m.config
}
```

**Update ClosePosition similarly:**

```go
func (e *Engine) ClosePosition(symbol string, rm *risk.Manager, reason string) (*Order, error) {
    // Get position from risk manager (single source of truth)
    pos, exists := rm.GetPosition(symbol)
    if !exists {
        return nil, fmt.Errorf("no position found for %s", symbol)
    }

    // Determine close side (opposite of open)
    var side OrderSide
    if pos.Side == "LONG" {
        side = OrderSideSell
    } else {
        side = OrderSideBuy
    }

    // Execute close order
    var order *Order
    var err error
    if e.config.UseLimitOrders {
        order, err = e.executor.ExecuteLimitOrder(symbol, side, pos.TakeProfit, pos.Size)
    } else {
        order, err = e.executor.ExecuteMarketOrder(symbol, side, pos.Size)
    }

    if err != nil {
        return nil, fmt.Errorf("failed to execute close order: %w", err)
    }

    // Close position in risk manager (updates equity)
    pnl, err := rm.ClosePosition(symbol, order.FilledPrice)
    if err != nil {
        return nil, fmt.Errorf("failed to close position in risk manager: %w", err)
    }

    // Record trade
    trade := &Trade{
        Symbol:     symbol,
        Side:       pos.Side,
        EntryPrice: pos.EntryPrice,
        ExitPrice:  order.FilledPrice,
        Size:       pos.Size,
        EntryTime:  pos.EntryTime,
        ExitTime:   time.Now(),
        PnL:        pnl,  // Use value from risk manager (with fees)
        ExitReason: reason,
        SignalType: strategy.SignalNone,
    }

    e.mu.Lock()
    e.orders[order.ID] = order
    e.trades = append(e.trades, trade)
    e.mu.Unlock()

    return order, nil
}
```

---

## Issue #3: Model Inference Race Condition (HIGH)

### Problem
ONNX runtime tensor data is shared; multiple goroutines writing to same buffer causes corruption.

### Solution: Thread-Safe Input Handling

**File:** `internal/model/predictor.go`

```go
// Option 1: Use temporary buffer (recommended)
func (p *Predictor) Predict(features []float64) (*Prediction, error) {
    p.mu.Lock()
    defer p.mu.Unlock()

    if int64(len(features)) != p.numFeatures {
        return nil, fmt.Errorf("expected %d features, got %d", p.numFeatures, len(features))
    }

    // Copy to input tensor
    inputData := p.inputTensor.GetData()
    if len(inputData) < len(features) {
        return nil, fmt.Errorf("input tensor too small: %d < %d", len(inputData), len(features))
    }
    
    // Safe copy using builtin copy
    for i, f := range features {
        inputData[i] = float32(f)
    }

    // Run inference
    if err := p.session.Run(); err != nil {
        return nil, fmt.Errorf("inference failed: %w", err)
    }

    // Read output
    outputData := p.outputTensor.GetData()
    if len(outputData) < 3 {
        return nil, fmt.Errorf("unexpected output size: %d", len(outputData))
    }

    // Return with explicit validation
    pred := &Prediction{
        ProbDown:    float64(outputData[0]),
        ProbNeutral: float64(outputData[1]),
        ProbUp:      float64(outputData[2]),
    }
    
    // Validate output is sane
    if !isValidPredictionOutput(pred) {
        return nil, fmt.Errorf("invalid model output: %+v", pred)
    }

    return pred, nil
}

// Helper to validate prediction output
func isValidPredictionOutput(pred *Prediction) bool {
    const epsilon = 0.01
    
    // Check range
    if pred.ProbDown < -epsilon || pred.ProbDown > 1+epsilon {
        return false
    }
    if pred.ProbNeutral < -epsilon || pred.ProbNeutral > 1+epsilon {
        return false
    }
    if pred.ProbUp < -epsilon || pred.ProbUp > 1+epsilon {
        return false
    }
    
    // Check sum to ~1.0
    sum := pred.ProbDown + pred.ProbNeutral + pred.ProbUp
    if math.Abs(sum-1.0) > epsilon {
        return false
    }
    
    // Check for NaN/Inf
    if math.IsNaN(pred.ProbDown) || math.IsInf(pred.ProbDown, 0) {
        return false
    }
    if math.IsNaN(pred.ProbNeutral) || math.IsInf(pred.ProbNeutral, 0) {
        return false
    }
    if math.IsNaN(pred.ProbUp) || math.IsInf(pred.ProbUp, 0) {
        return false
    }
    
    return true
}
```

---

## Issue #5: Daily Reset Race Condition (HIGH)

### Problem
`checkDailyReset()` modifies state without holding a lock.

### Solution: Proper Locking

**File:** `internal/risk/manager.go`

```go
// Before: Called with RLock
func (m *Manager) CanOpenPosition(symbol string) error {
    m.mu.RLock()
    defer m.mu.RUnlock()

    // ... checks ...
    m.checkDailyReset()  // WRONG: RLock doesn't protect writes
}

// After: Called with Lock
func (m *Manager) CanOpenPosition(symbol string) error {
    m.mu.Lock()
    defer m.mu.Unlock()

    // Check if already have position
    if _, exists := m.positions[symbol]; exists {
        return fmt.Errorf("position already exists for %s", symbol)
    }

    // Check max open positions
    if len(m.positions) >= m.config.MaxOpenPositions {
        return fmt.Errorf("max open positions (%d) reached", m.config.MaxOpenPositions)
    }

    // Reset daily PnL if needed (now with Lock held)
    m.checkDailyReset()
    
    // Check daily loss limit
    maxDailyLoss := m.equity * (m.config.MaxDailyLossPct / 100.0)
    if m.dailyPnL < -maxDailyLoss {
        return fmt.Errorf("daily loss limit exceeded: %.2f (limit: %.2f)", m.dailyPnL, -maxDailyLoss)
    }

    return nil
}

// Also fix GetDailyPnL to use correct lock
func (m *Manager) GetDailyPnL() float64 {
    m.mu.Lock()  // Changed from RLock to Lock
    defer m.mu.Unlock()
    
    m.checkDailyReset()
    return m.dailyPnL
}

// checkDailyReset now requires caller to hold Lock
// Add comment to enforce this
// Note: Caller MUST hold m.mu (exclusive Lock, not RLock)
func (m *Manager) checkDailyReset() {
    now := time.Now().Truncate(24 * time.Hour)
    if now.After(m.dailyResetTime) {
        m.dailyPnL = 0
        m.dailyResetTime = now
    }
}
```

---

## Issue #6: GetAllPositions Unsafe Copy (HIGH)

**File:** `internal/risk/manager.go`

```go
// Before: Returns pointers that caller can modify
func (m *Manager) GetAllPositions() map[string]*Position {
    m.mu.RLock()
    defer m.mu.RUnlock()

    result := make(map[string]*Position)
    for k, v := range m.positions {
        result[k] = v  // Pointer - caller can modify!
    }
    return result
}

// After: Returns deep copy (values, not pointers)
func (m *Manager) GetAllPositions() map[string]*Position {
    m.mu.RLock()
    defer m.mu.RUnlock()

    result := make(map[string]*Position)
    for k, v := range m.positions {
        // Deep copy the position struct
        posCopy := *v
        result[k] = &posCopy
    }
    return result
}
```

---

## Issue #8: Missing Signal Validation (MEDIUM)

**File:** `internal/strategy/signal.go`

Add validation helper:

```go
package strategy

import (
    "math"
)

// ValidatePrediction checks if prediction probabilities are valid
func ValidatePrediction(pred *model.Prediction) bool {
    if pred == nil {
        return false
    }
    
    const epsilon = 0.02
    
    // Check each probability is in valid range
    if pred.ProbDown < -epsilon || pred.ProbDown > 1+epsilon {
        return false
    }
    if pred.ProbNeutral < -epsilon || pred.ProbNeutral > 1+epsilon {
        return false
    }
    if pred.ProbUp < -epsilon || pred.ProbUp > 1+epsilon {
        return false
    }
    
    // Check they sum to ~1.0
    sum := pred.ProbDown + pred.ProbNeutral + pred.ProbUp
    if math.Abs(sum-1.0) > epsilon {
        return false
    }
    
    // Check no NaN/Inf
    if math.IsNaN(pred.ProbDown) || math.IsInf(pred.ProbDown, 0) {
        return false
    }
    if math.IsNaN(pred.ProbNeutral) || math.IsInf(pred.ProbNeutral, 0) {
        return false
    }
    if math.IsNaN(pred.ProbUp) || math.IsInf(pred.ProbUp, 0) {
        return false
    }
    
    return true
}

// ValidateFeatureVector checks if feature vector has valid prices
func ValidateFeatureVector(fv *features.FeatureVector) bool {
    if fv == nil {
        return false
    }
    
    // Price must be positive and finite
    if fv.Close <= 0 || math.IsNaN(fv.Close) || math.IsInf(fv.Close, 0) {
        return false
    }
    
    // Volume ratio should be non-negative
    if fv.VolumeRatio < 0 {
        return false
    }
    
    // Sentiment scores should be roughly in [-1, 1] range
    if math.Abs(fv.SentimentScore1h) > 2 || math.IsNaN(fv.SentimentScore1h) {
        return false
    }
    if math.Abs(fv.SentimentScore24h) > 2 || math.IsNaN(fv.SentimentScore24h) {
        return false
    }
    
    return true
}

// Updated Evaluate with validation
func (s *Strategy) Evaluate(fv *features.FeatureVector, pred *model.Prediction) *Signal {
    // Validate inputs
    if !ValidateFeatureVector(fv) || !ValidatePrediction(pred) {
        return nil
    }

    signal := &Signal{
        Symbol:     fv.Symbol,
        Timestamp:  fv.Timestamp,
        Price:      fv.Close,
        Prediction: pred,
        Features:   fv,
        Confidence: 0,
    }

    // ... rest of evaluation ...
}
```

---

## Issue #10: Resource Cleanup Race (MEDIUM)

**File:** `internal/model/predictor.go`

```go
// Before: Early return prevents cleanup
func (p *Predictor) Close() error {
    if p.session != nil {
        if err := p.session.Destroy(); err != nil {
            return err  // BUG: inputTensor and outputTensor never destroyed!
        }
    }
    if p.inputTensor != nil {
        if err := p.inputTensor.Destroy(); err != nil {
            return err
        }
    }
    if p.outputTensor != nil {
        if err := p.outputTensor.Destroy(); err != nil {
            return err
        }
    }
    return nil
}

// After: Attempt all cleanup, return last error
func (p *Predictor) Close() error {
    var lastErr error
    
    if p.session != nil {
        if err := p.session.Destroy(); err != nil {
            lastErr = err
            // Continue to cleanup other resources
        }
    }
    
    if p.inputTensor != nil {
        if err := p.inputTensor.Destroy(); err != nil {
            lastErr = err  // Overwrite previous error
        }
    }
    
    if p.outputTensor != nil {
        if err := p.outputTensor.Destroy(); err != nil {
            lastErr = err
        }
    }
    
    return lastErr
}

// Or better: Wrap errors
func (p *Predictor) Close() error {
    var errs []error
    
    if p.session != nil {
        if err := p.session.Destroy(); err != nil {
            errs = append(errs, fmt.Errorf("session destroy: %w", err))
        }
    }
    
    if p.inputTensor != nil {
        if err := p.inputTensor.Destroy(); err != nil {
            errs = append(errs, fmt.Errorf("input tensor destroy: %w", err))
        }
    }
    
    if p.outputTensor != nil {
        if err := p.outputTensor.Destroy(); err != nil {
            errs = append(errs, fmt.Errorf("output tensor destroy: %w", err))
        }
    }
    
    if len(errs) > 0 {
        return fmt.Errorf("cleanup errors: %v", errs)
    }
    return nil
}
```

---

## Testing Checklist

After applying these fixes:

```bash
# 1. Run race detector
go test -race ./internal/execution/... ./internal/risk/... ./internal/model/... ./internal/strategy/...

# 2. Check linting
go vet ./internal/...

# 3. Add unit tests for critical paths
# - Test PnL calculation with fees
# - Test checkDailyReset with concurrent access
# - Test model input validation
# - Test position open/close lifecycle

# 4. Backtest validation
# - Compare backtested PnL with/without fees
# - Verify equity tracking matches realized PnL
# - Validate daily loss limits work correctly
```

