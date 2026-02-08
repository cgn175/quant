package risk

import (
	"fmt"
	"math"
	"sync"
	"time"
)

type Position struct {
	Symbol        string
	Side          string // "LONG" or "SHORT"
	EntryPrice    float64
	Size          float64
	StopLoss      float64
	TakeProfit    float64
	EntryTime     time.Time
	RiskAmount    float64
	UnrealizedPnL float64
}

func (p *Position) UpdateUnrealizedPnL(currentPrice float64) {
	if p.Side == "LONG" {
		p.UnrealizedPnL = (currentPrice - p.EntryPrice) * p.Size
	} else {
		p.UnrealizedPnL = (p.EntryPrice - currentPrice) * p.Size
	}
}

// deepCopy returns a value copy of the Position so callers cannot mutate
// internal state.
func (p *Position) deepCopy() *Position {
	cp := *p
	return &cp
}

type Config struct {
	InitialEquity      float64
	MaxRiskPerTradePct float64
	MaxDailyLossPct    float64
	MaxOpenPositions   int
	MaxLeverage        float64
	FeePercent         float64 // e.g. 0.1 means 0.1% per side
}

type Manager struct {
	config         Config
	mu             sync.Mutex // single mutex — no RWMutex to avoid RLock/Lock upgrade gaps
	positions      map[string]*Position
	equity         float64
	dailyPnL       float64
	dailyResetTime time.Time
	realizedPnL    float64
}

func NewManager(config Config) *Manager {
	return &Manager{
		config:         config,
		positions:      make(map[string]*Position),
		equity:         config.InitialEquity,
		dailyResetTime: time.Now().Truncate(24 * time.Hour),
	}
}

// GetConfig returns a copy of the manager's config.
func (m *Manager) GetConfig() Config {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.config
}

func (m *Manager) CalculatePositionSize(symbol string, entryPrice, stopLoss float64, sizeMultiplier float64) (float64, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	if entryPrice <= 0 || stopLoss <= 0 {
		return 0, fmt.Errorf("invalid prices: entry=%f, stopLoss=%f", entryPrice, stopLoss)
	}

	// Calculate risk distance using absolute value to handle both long & short
	stopDistancePct := math.Abs((entryPrice - stopLoss) / entryPrice)
	if stopDistancePct < 0.0001 {
		return 0, fmt.Errorf("stop loss too close to entry price (distance=%.6f%%)", stopDistancePct*100)
	}

	// Risk amount per trade
	riskAmount := m.equity * (m.config.MaxRiskPerTradePct / 100.0)

	// Apply size multiplier (e.g., 0.5 for extreme sentiment)
	riskAmount *= sizeMultiplier

	// Position size = risk amount / (entry price * stop distance %)
	size := riskAmount / (entryPrice * stopDistancePct)

	// Apply leverage constraint
	if m.config.MaxLeverage > 0 {
		maxSizeByLeverage := (m.equity * m.config.MaxLeverage) / entryPrice
		if size > maxSizeByLeverage {
			size = maxSizeByLeverage
		}
	}

	return size, nil
}

// CanOpenPosition checks whether a new position can be opened for the given
// symbol.  All checks are performed under a single exclusive lock so there is
// no TOCTOU gap between the position-count check and the daily-reset / leverage
// check.
func (m *Manager) CanOpenPosition(symbol string) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	// Check if already have position in this symbol
	if _, exists := m.positions[symbol]; exists {
		return fmt.Errorf("position already exists for %s", symbol)
	}

	// Check max open positions
	if len(m.positions) >= m.config.MaxOpenPositions {
		return fmt.Errorf("max open positions (%d) reached", m.config.MaxOpenPositions)
	}

	// Reset daily PnL if a new day started (safe — we hold Lock)
	m.checkDailyResetLocked()

	// Check daily loss limit
	maxDailyLoss := m.equity * (m.config.MaxDailyLossPct / 100.0)
	if m.dailyPnL < -maxDailyLoss {
		return fmt.Errorf("daily loss limit exceeded: %.2f (limit: %.2f)", m.dailyPnL, maxDailyLoss)
	}

	// Check total account leverage
	if m.config.MaxLeverage > 0 {
		totalNotional := m.getTotalNotionalLocked()
		if m.equity > 0 {
			currentLeverage := totalNotional / m.equity
			if currentLeverage > m.config.MaxLeverage {
				return fmt.Errorf("total account leverage %.2fx exceeds max %.2fx", currentLeverage, m.config.MaxLeverage)
			}
		}
	}

	return nil
}

// CanOpenPositionWithSize runs the same checks as CanOpenPosition and
// additionally verifies that the proposed position would not exceed the
// leverage limit.
func (m *Manager) CanOpenPositionWithSize(symbol string, proposedEntryPrice, proposedSize float64) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	// --- inline the CanOpenPosition checks so we stay under the same lock ---

	if _, exists := m.positions[symbol]; exists {
		return fmt.Errorf("position already exists for %s", symbol)
	}

	if len(m.positions) >= m.config.MaxOpenPositions {
		return fmt.Errorf("max open positions (%d) reached", m.config.MaxOpenPositions)
	}

	m.checkDailyResetLocked()

	maxDailyLoss := m.equity * (m.config.MaxDailyLossPct / 100.0)
	if m.dailyPnL < -maxDailyLoss {
		return fmt.Errorf("daily loss limit exceeded: %.2f (limit: %.2f)", m.dailyPnL, maxDailyLoss)
	}

	if m.config.MaxLeverage > 0 && m.equity > 0 {
		proposedNotional := proposedEntryPrice * proposedSize
		currentNotional := m.getTotalNotionalLocked()
		newLeverage := (currentNotional + proposedNotional) / m.equity
		if newLeverage > m.config.MaxLeverage {
			return fmt.Errorf("proposed position would result in %.2fx leverage, exceeds max %.2fx", newLeverage, m.config.MaxLeverage)
		}
	}

	return nil
}

func (m *Manager) OpenPosition(symbol, side string, entryPrice, size, stopLoss, takeProfit, riskAmount float64) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	if _, exists := m.positions[symbol]; exists {
		return fmt.Errorf("position already exists for %s", symbol)
	}

	// Re-validate constraints under lock to close TOCTOU gap between
	// CanOpenPosition and OpenPosition (lock is released in between for
	// network calls).
	if len(m.positions) >= m.config.MaxOpenPositions {
		return fmt.Errorf("max open positions (%d) reached", m.config.MaxOpenPositions)
	}

	m.checkDailyResetLocked()
	maxDailyLoss := m.equity * (m.config.MaxDailyLossPct / 100.0)
	if m.dailyPnL < -maxDailyLoss {
		return fmt.Errorf("daily loss limit exceeded: %.2f (limit: %.2f)", m.dailyPnL, maxDailyLoss)
	}

	if m.config.MaxLeverage > 0 && m.equity > 0 {
		proposedNotional := entryPrice * size
		currentNotional := m.getTotalNotionalLocked()
		newLeverage := (currentNotional + proposedNotional) / m.equity
		if newLeverage > m.config.MaxLeverage {
			return fmt.Errorf("proposed position would result in %.2fx leverage, exceeds max %.2fx", newLeverage, m.config.MaxLeverage)
		}
	}

	m.positions[symbol] = &Position{
		Symbol:     symbol,
		Side:       side,
		EntryPrice: entryPrice,
		Size:       size,
		StopLoss:   stopLoss,
		TakeProfit: takeProfit,
		EntryTime:  time.Now(),
		RiskAmount: riskAmount,
	}

	return nil
}

// ClosePosition closes an existing position at exitPrice, deducts trading
// fees from both entry and exit sides, updates equity / daily PnL, and
// removes the position.  Returns the net PnL (after fees).
func (m *Manager) ClosePosition(symbol string, exitPrice float64) (float64, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	pos, exists := m.positions[symbol]
	if !exists {
		return 0, fmt.Errorf("no position found for %s", symbol)
	}

	// Gross PnL
	var grossPnL float64
	if pos.Side == "LONG" {
		grossPnL = (exitPrice - pos.EntryPrice) * pos.Size
	} else {
		grossPnL = (pos.EntryPrice - exitPrice) * pos.Size
	}

	// Deduct fees on both legs so equity/dailyPnL stay accurate.
	feePct := m.config.FeePercent / 100.0
	entryFees := pos.EntryPrice * pos.Size * feePct
	exitFees := exitPrice * pos.Size * feePct
	netPnL := grossPnL - entryFees - exitFees

	// Update equity and daily PnL
	m.equity += netPnL
	m.dailyPnL += netPnL
	m.realizedPnL += netPnL

	// Remove position
	delete(m.positions, symbol)

	return netPnL, nil
}

// ReducePosition reduces an existing position's size and optionally updates
// the stop loss. Returns the realized PnL for the exited portion (after fees).
// This is used for partial exits in trend following.
func (m *Manager) ReducePosition(symbol string, exitPrice float64, exitSize float64, newStopLoss float64) (float64, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	pos, exists := m.positions[symbol]
	if !exists {
		return 0, fmt.Errorf("no position found for %s", symbol)
	}

	if exitSize <= 0 || exitSize > pos.Size {
		return 0, fmt.Errorf("invalid exit size %.6f (position size: %.6f)", exitSize, pos.Size)
	}

	// Compute PnL on the exited portion
	var grossPnL float64
	if pos.Side == "LONG" {
		grossPnL = (exitPrice - pos.EntryPrice) * exitSize
	} else {
		grossPnL = (pos.EntryPrice - exitPrice) * exitSize
	}

	// Fees on the exited portion only
	feePct := m.config.FeePercent / 100.0
	entryFees := pos.EntryPrice * exitSize * feePct
	exitFees := exitPrice * exitSize * feePct
	netPnL := grossPnL - entryFees - exitFees

	// Update equity and daily PnL
	m.equity += netPnL
	m.dailyPnL += netPnL
	m.realizedPnL += netPnL

	// Reduce position size
	pos.Size -= exitSize

	// Update stop loss if requested
	if newStopLoss > 0 {
		pos.StopLoss = newStopLoss
	}

	// If position is fully closed, remove it
	if pos.Size <= 0 {
		delete(m.positions, symbol)
	}

	return netPnL, nil
}

// UpdateStopLoss updates the stop loss for an existing position. This can
// be used by trend_following mode to sync RiskManager state with the
// TrendStrategy's trailing stop (optional — TrendStrategy is authoritative).
func (m *Manager) UpdateStopLoss(symbol string, newStop float64) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	pos, exists := m.positions[symbol]
	if !exists {
		return fmt.Errorf("no position found for %s", symbol)
	}

	pos.StopLoss = newStop
	return nil
}

// GetPosition returns a deep copy of the position for the given symbol.
// Callers cannot mutate internal state through the returned pointer.
func (m *Manager) GetPosition(symbol string) (*Position, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()

	pos, exists := m.positions[symbol]
	if !exists {
		return nil, false
	}
	return pos.deepCopy(), true
}

// GetAllPositions returns a map of deep-copied positions.
func (m *Manager) GetAllPositions() map[string]*Position {
	m.mu.Lock()
	defer m.mu.Unlock()

	result := make(map[string]*Position, len(m.positions))
	for k, v := range m.positions {
		result[k] = v.deepCopy()
	}
	return result
}

func (m *Manager) UpdatePositionPnL(symbol string, currentPrice float64) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	pos, exists := m.positions[symbol]
	if !exists {
		return fmt.Errorf("no position found for %s", symbol)
	}

	pos.UpdateUnrealizedPnL(currentPrice)
	return nil
}

// ShouldClosePosition checks if the position for a given symbol should
// be closed based on the RiskManager's internal StopLoss and TakeProfit.
//
// NOTE: For trend_following mode, TrendStrategy.TrailingStop is the
// authoritative stop level. TrendStrategy calls UpdateTrailingStop and
// generates ExitSignals directly. This method is only used by the ML
// strategy path (runMLStrategy).
func (m *Manager) ShouldClosePosition(symbol string, currentPrice float64) (bool, string) {
	m.mu.Lock()
	defer m.mu.Unlock()

	pos, exists := m.positions[symbol]
	if !exists {
		return false, ""
	}

	// Check stop loss
	if pos.Side == "LONG" && currentPrice <= pos.StopLoss {
		return true, "stop_loss"
	}
	if pos.Side == "SHORT" && currentPrice >= pos.StopLoss {
		return true, "stop_loss"
	}

	// Check take profit
	if pos.Side == "LONG" && currentPrice >= pos.TakeProfit {
		return true, "take_profit"
	}
	if pos.Side == "SHORT" && currentPrice <= pos.TakeProfit {
		return true, "take_profit"
	}

	return false, ""
}

func (m *Manager) GetEquity() float64 {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.equity
}

func (m *Manager) GetDailyPnL() float64 {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.checkDailyResetLocked()
	return m.dailyPnL
}

func (m *Manager) GetRealizedPnL() float64 {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.realizedPnL
}

func (m *Manager) GetTotalUnrealizedPnL() float64 {
	m.mu.Lock()
	defer m.mu.Unlock()

	total := 0.0
	for _, pos := range m.positions {
		total += pos.UnrealizedPnL
	}
	return total
}

// checkDailyResetLocked resets dailyPnL at the start of each UTC day.
// MUST be called with m.mu held.
func (m *Manager) checkDailyResetLocked() {
	now := time.Now().Truncate(24 * time.Hour)
	if now.After(m.dailyResetTime) {
		m.dailyPnL = 0
		m.dailyResetTime = now
	}
}

func (m *Manager) GetStats() Stats {
	m.mu.Lock()
	defer m.mu.Unlock()

	m.checkDailyResetLocked()

	return Stats{
		Equity:           m.equity,
		RealizedPnL:      m.realizedPnL,
		UnrealizedPnL:    m.getTotalUnrealizedPnLLocked(),
		DailyPnL:         m.dailyPnL,
		OpenPositions:    len(m.positions),
		MaxOpenPositions: m.config.MaxOpenPositions,
		DailyLossLimit:   m.equity * (m.config.MaxDailyLossPct / 100.0),
	}
}

func (m *Manager) getTotalUnrealizedPnLLocked() float64 {
	total := 0.0
	for _, pos := range m.positions {
		total += pos.UnrealizedPnL
	}
	return total
}

func (m *Manager) getTotalNotionalLocked() float64 {
	total := 0.0
	for _, pos := range m.positions {
		total += pos.EntryPrice * pos.Size
	}
	return total
}

type Stats struct {
	Equity           float64
	RealizedPnL      float64
	UnrealizedPnL    float64
	DailyPnL         float64
	OpenPositions    int
	MaxOpenPositions int
	DailyLossLimit   float64
}
