package risk

import (
	"fmt"
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

type Config struct {
	InitialEquity      float64
	MaxRiskPerTradePct float64
	MaxDailyLossPct    float64
	MaxOpenPositions   int
	MaxLeverage        float64
}

type Manager struct {
	config         Config
	mu             sync.RWMutex
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

func (m *Manager) CalculatePositionSize(symbol string, entryPrice, stopLoss float64, sizeMultiplier float64) (float64, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()

	if entryPrice <= 0 || stopLoss <= 0 {
		return 0, fmt.Errorf("invalid prices: entry=%f, stopLoss=%f", entryPrice, stopLoss)
	}

	// Calculate risk distance
	stopDistancePct := (entryPrice - stopLoss) / entryPrice
	if stopDistancePct <= 0 {
		stopDistancePct = -stopDistancePct
	}
	if stopDistancePct == 0 {
		return 0, fmt.Errorf("stop loss equals entry price")
	}

	// Risk amount per trade
	riskAmount := m.equity * (m.config.MaxRiskPerTradePct / 100.0)

	// Apply size multiplier (e.g., 0.5 for extreme sentiment)
	riskAmount *= sizeMultiplier

	// Position size = risk amount / (entry price * stop distance %)
	size := riskAmount / (entryPrice * stopDistancePct)

	// Apply leverage constraint
	maxSizeByLeverage := (m.equity * m.config.MaxLeverage) / entryPrice
	if size > maxSizeByLeverage {
		size = maxSizeByLeverage
	}

	return size, nil
}

func (m *Manager) CanOpenPosition(symbol string) error {
	m.mu.RLock()

	// Check if already have position in this symbol
	if _, exists := m.positions[symbol]; exists {
		m.mu.RUnlock()
		return fmt.Errorf("position already exists for %s", symbol)
	}

	// Check max open positions
	if len(m.positions) >= m.config.MaxOpenPositions {
		m.mu.RUnlock()
		return fmt.Errorf("max open positions (%d) reached", m.config.MaxOpenPositions)
	}

	m.mu.RUnlock()

	// Check daily loss limit (requires lock upgrade, done separately)
	m.mu.Lock()
	m.checkDailyResetLocked()
	maxDailyLoss := m.equity * (m.config.MaxDailyLossPct / 100.0)
	if m.dailyPnL < -maxDailyLoss {
		m.mu.Unlock()
		return fmt.Errorf("daily loss limit exceeded: %.2f (limit: %.2f)", m.dailyPnL, maxDailyLoss)
	}

	// Check total account leverage
	totalNotional := m.getTotalNotionalLocked()
	currentLeverage := totalNotional / m.equity
	if currentLeverage > m.config.MaxLeverage {
		m.mu.Unlock()
		return fmt.Errorf("total account leverage %.2fx exceeds max %.2fx", currentLeverage, m.config.MaxLeverage)
	}
	m.mu.Unlock()

	return nil
}

func (m *Manager) CanOpenPositionWithSize(symbol string, proposedEntryPrice, proposedSize float64) error {
	if err := m.CanOpenPosition(symbol); err != nil {
		return err
	}

	m.mu.RLock()
	defer m.mu.RUnlock()

	proposedNotional := proposedEntryPrice * proposedSize
	currentNotional := m.getTotalNotionalLocked()
	newLeverage := (currentNotional + proposedNotional) / m.equity

	if newLeverage > m.config.MaxLeverage {
		return fmt.Errorf("proposed position would result in %.2fx leverage, exceeds max %.2fx", newLeverage, m.config.MaxLeverage)
	}

	return nil
}

func (m *Manager) OpenPosition(symbol, side string, entryPrice, size, stopLoss, takeProfit, riskAmount float64) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	if _, exists := m.positions[symbol]; exists {
		return fmt.Errorf("position already exists for %s", symbol)
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

func (m *Manager) ClosePosition(symbol string, exitPrice float64) (float64, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	pos, exists := m.positions[symbol]
	if !exists {
		return 0, fmt.Errorf("no position found for %s", symbol)
	}

	// Calculate realized PnL
	var pnl float64
	if pos.Side == "LONG" {
		pnl = (exitPrice - pos.EntryPrice) * pos.Size
	} else {
		pnl = (pos.EntryPrice - exitPrice) * pos.Size
	}

	// Update equity and daily PnL
	m.equity += pnl
	m.dailyPnL += pnl
	m.realizedPnL += pnl

	// Remove position
	delete(m.positions, symbol)

	return pnl, nil
}

func (m *Manager) GetPosition(symbol string) (*Position, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()

	pos, exists := m.positions[symbol]
	return pos, exists
}

func (m *Manager) GetAllPositions() map[string]*Position {
	m.mu.RLock()
	defer m.mu.RUnlock()

	result := make(map[string]*Position)
	for k, v := range m.positions {
		// Deep copy position to prevent external modification
		pos := *v
		result[k] = &pos
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

func (m *Manager) ShouldClosePosition(symbol string, currentPrice float64) (bool, string) {
	m.mu.RLock()
	defer m.mu.RUnlock()

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
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.equity
}

func (m *Manager) GetDailyPnL() float64 {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.checkDailyResetLocked()
	return m.dailyPnL
}

func (m *Manager) GetRealizedPnL() float64 {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.realizedPnL
}

func (m *Manager) GetTotalUnrealizedPnL() float64 {
	m.mu.RLock()
	defer m.mu.RUnlock()

	total := 0.0
	for _, pos := range m.positions {
		total += pos.UnrealizedPnL
	}
	return total
}

// checkDailyReset is NOT thread-safe; must be called with lock held
func (m *Manager) checkDailyReset() {
	now := time.Now().Truncate(24 * time.Hour)
	if now.After(m.dailyResetTime) {
		m.dailyPnL = 0
		m.dailyResetTime = now
	}
}

// checkDailyResetLocked is thread-safe (assumes lock held by caller)
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
