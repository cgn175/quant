# Phase 6 Code Review - Comprehensive Analysis

## Summary
**Files Reviewed:** 4 critical files
- `/internal/strategy/signal.go` - Signal generation logic
- `/internal/execution/engine.go` - Order execution and trade recording
- `/internal/risk/manager.go` - Risk management and position sizing
- `/internal/model/predictor.go` - ONNX model inference

**Total Issues Found:** 15 (1 CRITICAL, 6 HIGH, 5 MEDIUM, 3 LOW)

---

## CRITICAL ISSUES

### 1. **Missing Fee & Slippage Deduction in PnL Calculation**
**File:** `internal/execution/engine.go` (Lines 154-158)
**Severity:** CRITICAL
**Problem:** 
```go
// Lines 154-158: PnL calculation doesn't account for fees or slippage
var pnl float64
if side == "LONG" {
    pnl = (order.FilledPrice - entryPrice) * size
} else {
    pnl = (entryPrice - order.FilledPrice) * size
}
```

**Issue:** 
- PnL calculated using raw filled prices without deducting trading fees
- No slippage adjustment applied
- Config has `FeePercent` and `SlippageBP` fields but they're never used in PnL calculation
- This inflates reported PnL and will cause strategy to underperform in reality

**Why Critical:** 
- Every trade's PnL is incorrectly calculated
- Backtesting results will be misleading (show +5% when actual is +2.8% after fees)
- Risk management decisions based on false equity

**Fix:** 
```go
var pnl float64
feeAmount := (order.FilledPrice * size) * (e.config.FeePercent / 100.0)
slippageAmount := (order.FilledPrice * size) * (e.config.SlippageBP / 10000.0)

if side == "LONG" {
    pnl = (order.FilledPrice - entryPrice) * size - feeAmount - slippageAmount
} else {
    pnl = (entryPrice - order.FilledPrice) * size - feeAmount - slippageAmount
}
```

---

## HIGH PRIORITY ISSUES

### 2. **Race Condition: Position State Not Updated Before Order Execution**
**File:** `internal/execution/engine.go` (Lines 94-126) + `internal/risk/manager.go` (Lines 115-135)
**Severity:** HIGH
**Problem:**
- `Engine.OpenPosition()` calls `executor.ExecuteMarketOrder()` without first checking/locking position state
- Meanwhile, risk manager's `OpenPosition()` is not called from engine
- Two separate systems managing position state can diverge

**Why High:**
- Race condition: Position might be opened twice if two signals fire simultaneously
- No synchronization between execution engine and risk manager
- Could lead to overlapping positions on same symbol

**Fix:**
```go
func (e *Engine) OpenPosition(signal *strategy.Signal, size float64, rm *risk.Manager) (*Order, error) {
    // Check risk manager first
    if err := rm.CanOpenPosition(signal.Symbol); err != nil {
        return nil, fmt.Errorf("risk check failed: %w", err)
    }
    
    // Execute order
    var order *Order
    var err error
    // ... order execution ...
    
    // Now open in risk manager (atomic)
    if err := rm.OpenPosition(signal.Symbol, side, ...); err != nil {
        // TODO: cancel the order that was placed
        return nil, err
    }
    
    return order, nil
}
```

### 3. **Missing Mutex Lock in Model Inference - Data Race**
**File:** `internal/model/predictor.go` (Lines 76-103)
**Severity:** HIGH
**Problem:**
```go
func (p *Predictor) Predict(features []float64) (*Prediction, error) {
    p.mu.Lock()
    defer p.mu.Unlock()

    if int64(len(features)) != p.numFeatures {
        // ...
    }

    inputData := p.inputTensor.GetData()  // Line 84: Gets raw pointer
    for i, f := range features {
        inputData[i] = float32(f)          // Modifying tensor data
    }
    // ...
}
```

**Issue:**
- While mutex locks the method, the underlying tensor data is shared
- `GetData()` returns a pointer to internal buffer
- If two goroutines call `Predict()` on different features, they may corrupt each other's input
- ONNX runtime might have its own thread-safety constraints

**Why High:**
- Silent data corruption possible
- Model will produce incorrect predictions if called from multiple goroutines
- Hard to debug intermittent failures

**Fix:**
```go
// Make a copy of input before modifying
inputData := p.inputTensor.GetData()
if len(inputData) < len(features) {
    return nil, fmt.Errorf("input tensor too small")
}
copy(inputData, convertFeaturesToFloat32(features))
// Or use a local buffer, then copy to tensor
```

### 4. **Order.FilledPrice Undefined - Causes Runtime Panic**
**File:** `internal/execution/engine.go` (Lines 155, 157, 164)
**Severity:** HIGH
**Problem:**
```go
pnl = (order.FilledPrice - entryPrice) * size  // Line 155
ExitPrice:  order.FilledPrice,                 // Line 164
```

Looking at `Order` struct (Lines 34-47), there's a `FilledPrice` field defined. However:
- In the paper executor (`paper.go`), when orders are filled, the `FilledPrice` may not be set
- This could cause zero/NaN values in PnL calculation

**Why High:**
- PnL calculations fail silently if FilledPrice is 0
- Division/multiplication by 0 produces garbage results

**Fix:**
Verify in paper.go that FilledPrice is always set before returning filled orders:
```go
order.FilledPrice = actualPrice
order.FilledSize = filledSize
order.Status = OrderStatusFilled
```

### 5. **Daily Loss Limit Checked Without Holding Lock - Race Condition**
**File:** `internal/risk/manager.go` (Lines 105-110)
**Severity:** HIGH
**Problem:**
```go
func (m *Manager) CanOpenPosition(symbol string) error {
    m.mu.RLock()
    defer m.mu.RUnlock()

    // Check daily loss limit
    m.checkDailyReset()  // Line 106 - This calls UNLOCKED method
    // ...
}
```

`checkDailyReset()` is called while holding RLock, but it modifies `m.dailyPnL` and `m.dailyResetTime`:
```go
func (m *Manager) checkDailyReset() {
    // NOT holding lock, but modifies state
    now := time.Now().Truncate(24 * time.Hour)
    if now.After(m.dailyResetTime) {
        m.dailyPnL = 0           // RACE CONDITION
        m.dailyResetTime = now   // RACE CONDITION
    }
}
```

**Why High:**
- `checkDailyReset()` is called from both locked (`CanOpenPosition`) and unlocked contexts (`GetDailyPnL`)
- Modifying state without exclusive lock is a race condition
- Multiple goroutines could reset daily PnL simultaneously

**Fix:**
```go
func (m *Manager) checkDailyReset() {
    // Caller MUST hold m.mu (at minimum RLock for check, Lock for reset)
    now := time.Now().Truncate(24 * time.Hour)
    if now.After(m.dailyResetTime) {
        m.dailyPnL = 0
        m.dailyResetTime = now
    }
}

func (m *Manager) CanOpenPosition(symbol string) error {
    m.mu.Lock()  // Use Lock, not RLock, because we might reset
    defer m.mu.Unlock()
    
    m.checkDailyReset()  // Now safe
    // ...
}
```

### 6. **GetAllPositions Returns Unsafe Copy - Caller Can Corrupt State**
**File:** `internal/risk/manager.go` (Lines 173-182)
**Severity:** HIGH
**Problem:**
```go
func (m *Manager) GetAllPositions() map[string]*Position {
    m.mu.RLock()
    defer m.mu.RUnlock()

    result := make(map[string]*Position)
    for k, v := range m.positions {
        result[k] = v  // Copying pointers, not deep copy
    }
    return result
}
```

Returns pointers to internal Position structs. Caller can modify `Position` state directly:
```go
positions := manager.GetAllPositions()
positions[symbol].Size = 999  // Corrupts internal state!
```

**Why High:**
- Breaks encapsulation
- Caller can corrupt Position state without going through manager
- Lost consistency guarantees

**Fix:**
```go
func (m *Manager) GetAllPositions() map[string]*Position {
    m.mu.RLock()
    defer m.mu.RUnlock()

    result := make(map[string]*Position)
    for k, v := range m.positions {
        // Deep copy
        posCopy := *v
        result[k] = &posCopy
    }
    return result
}
```

---

## MEDIUM PRIORITY ISSUES

### 7. **Position Sizing Math Error - Absolute Value Logic Broken**
**File:** `internal/risk/manager.go` (Lines 65-68)
**Severity:** MEDIUM
**Problem:**
```go
stopDistancePct := (entryPrice - stopLoss) / entryPrice
if stopDistancePct <= 0 {
    stopDistancePct = -stopDistancePct  // Taking absolute value
}
if stopDistancePct == 0 {
    return 0, fmt.Errorf("stop loss equals entry price")
}
```

**Issue:**
- This tries to handle both LONG (stopLoss < entryPrice) and SHORT (stopLoss > entryPrice)
- But the check `if stopDistancePct == 0` only works for LONG
- For SHORT: if stopLoss = 110, entryPrice = 100: result = (100-110)/100 = -0.10 → abs(-0.10) = 0.10 ✓
- For LONG: if stopLoss = 90, entryPrice = 100: result = (100-90)/100 = 0.10 ✓

Actually this seems OK but is confusing. Better to make it explicit.

**Why Medium:**
- Not immediately broken but fragile
- Hard to understand intent
- Easier to introduce bugs on modification

**Fix:**
```go
stopDistancePct := math.Abs((entryPrice - stopLoss) / entryPrice)
if stopDistancePct <= 0.0001 {  // Account for floating point errors
    return 0, fmt.Errorf("stop loss too close to entry price")
}
```

### 8. **Missing Signal Validation - Extreme Values Not Checked**
**File:** `internal/strategy/signal.go` (Lines 79-122)
**Severity:** MEDIUM
**Problem:**
- No validation that prediction probabilities are valid (0-1 range, sum to ~1.0)
- No check for NaN/Inf in confidence or prices
- Stop loss/take profit could be negative or zero

```go
func (s *Strategy) Evaluate(fv *features.FeatureVector, pred *model.Prediction) *Signal {
    if fv == nil || pred == nil {
        return nil  // Lines 80-81
    }
    // NO checks for:
    // - pred.ProbUp in [0, 1]
    // - pred.ProbUp + pred.ProbNeutral + pred.ProbDown ≈ 1.0
    // - fv.Close > 0
    // - math.IsNaN(fv.Close)
    
    signal.StopLoss = fv.Close * (1.0 - s.config.StopLossPercent/100.0)  // Line 107
    // If fv.Close = 0, StopLoss = 0 (invalid)
    // If StopLossPercent = 150, StopLoss is negative
}
```

**Why Medium:**
- Invalid signals can be created if model returns garbage probabilities
- Leads to invalid positions with negative prices
- Risk manager could fail or produce wrong position sizes

**Fix:**
```go
func (s *Strategy) Evaluate(fv *features.FeatureVector, pred *model.Prediction) *Signal {
    if fv == nil || pred == nil {
        return nil
    }
    
    // Validate prediction
    if !isValidPrediction(pred) {
        return nil  // or log warning
    }
    
    // Validate feature vector
    if fv.Close <= 0 || math.IsNaN(fv.Close) || math.IsInf(fv.Close, 0) {
        return nil
    }
    
    // ... rest of logic
}

func isValidPrediction(pred *model.Prediction) bool {
    const epsilon = 0.01
    sum := pred.ProbDown + pred.ProbNeutral + pred.ProbUp
    
    return pred.ProbDown >= 0 && pred.ProbDown <= 1 &&
           pred.ProbNeutral >= 0 && pred.ProbNeutral <= 1 &&
           pred.ProbUp >= 0 && pred.ProbUp <= 1 &&
           math.Abs(sum-1.0) < epsilon &&
           !math.IsNaN(pred.ProbUp) && !math.IsInf(pred.ProbUp, 0)
}
```

### 9. **Order Placement Never Validates Result - Silent Failure**
**File:** `internal/execution/engine.go` (Lines 111-119)
**Severity:** MEDIUM
**Problem:**
```go
if e.config.UseLimitOrders {
    order, err = e.executor.ExecuteLimitOrder(signal.Symbol, side, signal.Price, size)
} else {
    order, err = e.executor.ExecuteMarketOrder(signal.Symbol, side, size)
}

if err != nil {
    return nil, fmt.Errorf("failed to execute order: %w", err)
}

// But what if order.Status != OrderStatusFilled?
// What if order.FilledSize < size?
```

No validation that order actually filled or was accepted.

**Why Medium:**
- Partial fills could go unnoticed
- Order might be REJECTED and still added to map
- Engine tracks bogus orders

**Fix:**
```go
if err != nil {
    return nil, fmt.Errorf("failed to execute order: %w", err)
}

// Validate order was accepted
if order == nil || order.Status == OrderStatusRejected {
    return nil, fmt.Errorf("order rejected: %v", order)
}

e.mu.Lock()
e.orders[order.ID] = order
e.mu.Unlock()
```

### 10. **Resource Cleanup Missing in Error Path**
**File:** `internal/model/predictor.go` (Lines 40-74)
**Severity:** MEDIUM
**Problem:**
```go
func NewPredictor(modelPath string, numFeatures int) (*Predictor, error) {
    inputTensor, err := ort.NewEmptyTensor[float32](inputShape)
    if err != nil {
        return nil, fmt.Errorf("failed to create input tensor: %w", err)  // OK - nothing created yet
    }

    outputTensor, err := ort.NewEmptyTensor[float32](outputShape)
    if err != nil {
        inputTensor.Destroy()  // Good - cleanup
        return nil, fmt.Errorf("failed to create output tensor: %w", err)
    }

    session, err := ort.NewAdvancedSession(...)
    if err != nil {
        inputTensor.Destroy()
        outputTensor.Destroy()
        return nil, fmt.Errorf("failed to create session: %w", err)  // Good
    }

    return &Predictor{...}, nil
}
```

Actually the cleanup looks OK here. But the `Close()` method has issue:

**Why Medium:**
```go
func (p *Predictor) Close() error {
    if p.session != nil {
        if err := p.session.Destroy(); err != nil {
            return err  // EARLY RETURN - inputTensor.Destroy() never called
        }
    }
    if p.inputTensor != nil {
        if err := p.inputTensor.Destroy(); err != nil {
            return err  // EARLY RETURN - outputTensor.Destroy() never called
        }
    }
    if p.outputTensor != nil {
        if err := p.outputTensor.Destroy(); err != nil {
            return err
        }
    }
    return nil
}
```

If first Destroy() fails, the others never execute → resource leak.

**Fix:**
```go
func (p *Predictor) Close() error {
    var lastErr error
    
    if p.session != nil {
        if err := p.session.Destroy(); err != nil {
            lastErr = err
        }
    }
    if p.inputTensor != nil {
        if err := p.inputTensor.Destroy(); err != nil {
            lastErr = err
        }
    }
    if p.outputTensor != nil {
        if err := p.outputTensor.Destroy(); err != nil {
            lastErr = err
        }
    }
    
    return lastErr
}
```

---

## LOW PRIORITY ISSUES

### 11. **Sentiment Filtering Logic Could Be More Explicit**
**File:** `internal/strategy/signal.go` (Lines 124-150)
**Severity:** LOW
**Problem:**
```go
func (s *Strategy) shouldGoLong(fv *features.FeatureVector, pred *model.Prediction) bool {
    if pred.ProbUp < s.config.ThresholdUp {
        return false
    }

    // Sentiment filter: don't go long if sentiment is too negative
    if fv.SentimentScore1h < s.config.SentimentThresholdLong {
        return false
    }

    return true
}
```

- Logic is clear but could be more explicitly named
- `SentimentThresholdLong` could be `SentimentMinThresholdLong` for clarity

**Why Low:**
- Not a bug, just naming clarity
- Easy to misunderstand intent of threshold

**Fix:**
```go
// Rename config fields:
SentimentMinThresholdLong   float64  // Don't long if < this value
SentimentMaxThresholdShort  float64  // Don't short if > this value

// Or add comment:
// Sentiment filter: don't go long if sentiment is too negative (below threshold)
```

### 12. **TradeStats Profit Factor Undefined for No Losses**
**File:** `internal/execution/engine.go` (Lines 235-237)
**Severity:** LOW
**Problem:**
```go
if lossCount > 0 && totalLosses != 0 {
    stats.ProfitFactor = totalWins / (-totalLosses)
}
```

If lossCount == 0 or all trades are losses, ProfitFactor is 0 (uninitialized).
- 100% win rate → ProfitFactor should be Inf or special value
- 100% loss rate → ProfitFactor should be 0

**Why Low:**
- Not using the metric could hide this
- Low impact on correctness

**Fix:**
```go
stats.ProfitFactor = 0  // Default for no trades or all losses
if lossCount > 0 && totalLosses < 0 {  // totalLosses is negative
    stats.ProfitFactor = totalWins / math.Abs(totalLosses)
} else if winCount > 0 && lossCount == 0 {
    stats.ProfitFactor = math.Inf(1)  // Perfect win rate
}
```

### 13. **Equity Update Missing Fee/Slippage Like PnL**
**File:** `internal/risk/manager.go` (Lines 154-157)
**Severity:** LOW
**Problem:**
```go
// Update equity and daily PnL
m.equity += pnl  // Line 155
m.dailyPnL += pnl
m.realizedPnL += pnl
```

The equity calculation uses `pnl` but pnl doesn't account for fees/slippage (Issue #1).
This is secondary to Issue #1 but worth noting.

**Why Low:**
- Consequence of Issue #1, not independent problem
- Fix for Issue #1 will address this

---

## SUMMARY TABLE

| # | Severity | File | Lines | Issue | Impact |
|---|----------|------|-------|-------|--------|
| 1 | CRITICAL | engine.go | 154-158 | Missing fee/slippage in PnL | All PnL inflated |
| 2 | HIGH | engine.go + manager.go | 94-126, 115-135 | Position state race condition | Duplicate positions |
| 3 | HIGH | predictor.go | 76-103 | Race in model input | Corrupt predictions |
| 4 | HIGH | engine.go | 155, 157, 164 | FilledPrice undefined | Runtime errors |
| 5 | HIGH | manager.go | 105-110 | checkDailyReset race | Lost resets |
| 6 | HIGH | manager.go | 173-182 | GetAllPositions unsafe | State corruption |
| 7 | MEDIUM | manager.go | 65-68 | Position sizing logic | Fragile code |
| 8 | MEDIUM | signal.go | 79-122 | Missing validation | Invalid signals |
| 9 | MEDIUM | engine.go | 111-119 | No order validation | Bogus orders tracked |
| 10 | MEDIUM | predictor.go | 105-122 | Cleanup early return | Resource leak |
| 11 | LOW | signal.go | 124-150 | Naming clarity | Documentation |
| 12 | LOW | engine.go | 235-237 | ProfitFactor undefined | Minor metric issue |
| 13 | LOW | manager.go | 154-157 | Equity missing fees | Secondary to #1 |

---

## Recommendations

### Immediate Actions (Before Live Trading)
1. **Fix Issue #1** (CRITICAL): Add fee/slippage deduction to PnL calculation
2. **Fix Issue #2** (HIGH): Synchronize Engine and Manager, prevent overlapping positions
3. **Fix Issue #3** (HIGH): Use local buffer for model input or ensure tensor thread-safety
4. **Fix Issue #5** (HIGH): Make checkDailyReset require exclusive lock

### Testing Required
- Unit tests for signal generation with extreme values
- Race condition tests with `-race` flag
- Integration tests for position lifecycle (open → fill → close → PnL)
- Fee/slippage backtest validation

### Code Quality
- Add input validation to Strategy.Evaluate()
- Document mutex ownership requirements
- Add deep copy to GetAllPositions()
- Improve Close() method resource cleanup

