package execution

import (
	"fmt"
	"math"
	"sync"
	"time"

	"github.com/cgn175/quant-bot/internal/metrics"
	"github.com/cgn175/quant-bot/internal/strategy"
)

type OrderType string

const (
	OrderTypeMarket OrderType = "MARKET"
	OrderTypeLimit  OrderType = "LIMIT"
)

type OrderSide string

const (
	OrderSideBuy  OrderSide = "BUY"
	OrderSideSell OrderSide = "SELL"
)

type OrderStatus string

const (
	OrderStatusNew      OrderStatus = "NEW"
	OrderStatusFilled   OrderStatus = "FILLED"
	OrderStatusCanceled OrderStatus = "CANCELED"
	OrderStatusRejected OrderStatus = "REJECTED"
)

type Order struct {
	ID            string
	Symbol        string
	Type          OrderType
	Side          OrderSide
	Price         float64
	Size          float64
	Status        OrderStatus
	FilledPrice   float64
	FilledSize    float64
	CreatedAt     time.Time
	UpdatedAt     time.Time
	ClientOrderID string
}

type Trade struct {
	Symbol       string
	Side         string
	EntryPrice   float64
	ExitPrice    float64
	Size         float64
	EntryTime    time.Time
	ExitTime     time.Time
	PnL          float64
	ExitReason   string
	SignalType   strategy.SignalType
	StrategyType string // "trend_following", "market_making", "ml"
}

type Executor interface {
	ExecuteMarketOrder(symbol string, side OrderSide, size float64) (*Order, error)
	ExecuteLimitOrder(symbol string, side OrderSide, price, size float64) (*Order, error)
	CancelOrder(symbol string, orderID string) error
	GetOrder(symbol string, orderID string) (*Order, error)
	Close() error
}

type Config struct {
	Mode                     string
	UseLimitOrders           bool
	AggressiveLimitTimeoutMs int // timeout before falling back to market order (0 = no timeout)
	SlippageBP               float64
	FeePercent               float64
}

type Engine struct {
	config   Config
	executor Executor
	mu       sync.RWMutex
	orders   map[string]*Order
	trades   []*Trade
	metrics  *metrics.Metrics
}

func NewEngine(config Config, executor Executor) *Engine {
	return &Engine{
		config:   config,
		executor: executor,
		orders:   make(map[string]*Order),
		trades:   make([]*Trade, 0),
	}
}

// SetMetrics sets the metrics collector for the engine.
func (e *Engine) SetMetrics(m *metrics.Metrics) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.metrics = m
}

func (e *Engine) OpenPosition(signal *strategy.Signal, size float64) (*Order, error) {
	if signal == nil {
		return nil, fmt.Errorf("signal is nil")
	}

	var side OrderSide
	if signal.Type == strategy.SignalLong {
		side = OrderSideBuy
	} else if signal.Type == strategy.SignalShort {
		side = OrderSideSell
	} else {
		return nil, fmt.Errorf("invalid signal type for opening position: %s", signal.Type)
	}

	var order *Order
	var err error

	if e.config.UseLimitOrders {
		order, err = e.ExecuteAggressiveLimitOrder(signal.Symbol, side, signal.Price, size)
	} else {
		order, err = e.executor.ExecuteMarketOrder(signal.Symbol, side, size)
	}

	if err != nil {
		return nil, fmt.Errorf("failed to execute order: %w", err)
	}

	if order == nil || order.Status == OrderStatusRejected {
		return nil, fmt.Errorf("order rejected or returned nil")
	}

	e.mu.Lock()
	e.orders[order.ID] = order
	e.mu.Unlock()

	return order, nil
}

// ExecuteAggressiveLimitOrder places a limit order at the given price and polls
// for fill within the configured timeout. If unfilled, it cancels the limit
// order and falls back to a market order.
// This saves maker/taker fee difference (~3-5bps) when the limit fills quickly.
func (e *Engine) ExecuteAggressiveLimitOrder(symbol string, side OrderSide, price, size float64) (*Order, error) {
	// Place limit order
	order, err := e.executor.ExecuteLimitOrder(symbol, side, price, size)
	if err != nil {
		return nil, err
	}

	// If already filled (paper mode), return immediately
	if order.Status == OrderStatusFilled {
		return order, nil
	}

	// No timeout configured — just return the limit order as-is
	timeoutMs := e.config.AggressiveLimitTimeoutMs
	if timeoutMs <= 0 {
		return order, nil
	}

	// Poll for fill within timeout
	deadline := time.Now().Add(time.Duration(timeoutMs) * time.Millisecond)
	pollInterval := 200 * time.Millisecond

	for time.Now().Before(deadline) {
		time.Sleep(pollInterval)

		latest, err := e.executor.GetOrder(symbol, order.ID)
		if err != nil {
			continue
		}

		if latest.Status == OrderStatusFilled {
			return latest, nil
		}
	}

	// Timeout — cancel limit and fall back to market
	_ = e.executor.CancelOrder(symbol, order.ID)

	marketOrder, err := e.executor.ExecuteMarketOrder(symbol, side, size)
	if err != nil {
		return nil, fmt.Errorf("aggressive limit timeout, market fallback failed: %w", err)
	}

	return marketOrder, nil
}

func (e *Engine) ClosePosition(symbol string, side string, price, size float64, reason string, signalType strategy.SignalType, strategyType string, entryPrice float64, entryTime time.Time) (*Order, error) {
	var orderSide OrderSide
	if side == "LONG" {
		orderSide = OrderSideSell
	} else {
		orderSide = OrderSideBuy
	}

	var order *Order
	var err error

	if e.config.UseLimitOrders {
		order, err = e.executor.ExecuteLimitOrder(symbol, orderSide, price, size)
	} else {
		order, err = e.executor.ExecuteMarketOrder(symbol, orderSide, size)
	}

	if err != nil {
		return nil, fmt.Errorf("failed to execute close order: %w", err)
	}

	e.mu.Lock()
	defer e.mu.Unlock()
	e.orders[order.ID] = order

	// Calculate PnL with fees
	// Both entry and exit incur fees
	// Note: Slippage is already reflected in FilledPrice (paper: simulated, live: actual fill)
	entryFees := entryPrice * size * (e.config.FeePercent / 100.0)
	exitFees := order.FilledPrice * size * (e.config.FeePercent / 100.0)

	var grossPnL float64
	if side == "LONG" {
		grossPnL = (order.FilledPrice - entryPrice) * size
	} else {
		grossPnL = (entryPrice - order.FilledPrice) * size
	}

	netPnL := grossPnL - entryFees - exitFees

	trade := &Trade{
		Symbol:       symbol,
		Side:         side,
		EntryPrice:   entryPrice,
		ExitPrice:    order.FilledPrice,
		Size:         size,
		EntryTime:    entryTime,
		ExitTime:     time.Now(),
		PnL:          netPnL,
		ExitReason:   reason,
		SignalType:   signalType,
		StrategyType: strategyType,
	}
	e.trades = append(e.trades, trade)

	// Update metrics if available
	if e.metrics != nil {
		e.metrics.TotalTrades.Inc()
		e.metrics.RealizedPnL.Add(trade.PnL)
		if trade.PnL > 0 {
			e.metrics.WinningTrades.Inc()
		} else if trade.PnL < 0 {
			e.metrics.LosingTrades.Inc()
		}

		// Recalculate win rate
		stats := e.GetTradeStatsByStrategy("")
		e.metrics.WinRate.Set(stats.WinRate)
		e.metrics.ProfitFactor.Set(stats.ProfitFactor)
	}

	return order, nil
}

func (e *Engine) GetTrades() []*Trade {
	e.mu.RLock()
	defer e.mu.RUnlock()

	result := make([]*Trade, len(e.trades))
	copy(result, e.trades)
	return result
}

func (e *Engine) GetOrders() []*Order {
	e.mu.RLock()
	defer e.mu.RUnlock()

	result := make([]*Order, 0, len(e.orders))
	for _, order := range e.orders {
		result = append(result, order)
	}
	return result
}

func (e *Engine) GetTradeStats() TradeStats {
	e.mu.RLock()
	defer e.mu.RUnlock()

	stats := TradeStats{
		TotalTrades: len(e.trades),
	}

	if len(e.trades) == 0 {
		return stats
	}

	var totalPnL float64
	var winCount int
	var lossCount int
	var totalWins float64
	var totalLosses float64

	for _, trade := range e.trades {
		totalPnL += trade.PnL
		if trade.PnL > 0 {
			winCount++
			totalWins += trade.PnL
		} else if trade.PnL < 0 {
			lossCount++
			totalLosses += trade.PnL
		}
	}

	stats.NetPnL = totalPnL
	stats.WinCount = winCount
	stats.LossCount = lossCount

	if stats.TotalTrades > 0 {
		stats.WinRate = float64(winCount) / float64(stats.TotalTrades)
	}

	if lossCount > 0 && totalLosses < 0 {
		stats.ProfitFactor = totalWins / (-totalLosses)
	} else if winCount > 0 && lossCount == 0 {
		stats.ProfitFactor = math.Inf(1) // perfect win rate
	}

	if stats.TotalTrades > 0 {
		stats.AvgPnL = totalPnL / float64(stats.TotalTrades)
	}

	return stats
}

type TradeStats struct {
	TotalTrades  int
	WinCount     int
	LossCount    int
	WinRate      float64
	NetPnL       float64
	AvgPnL       float64
	ProfitFactor float64
}

// GetTradeStatsByStrategy returns trade statistics filtered by strategy type.
// Pass empty string to get all trades (equivalent to GetTradeStats).
func (e *Engine) GetTradeStatsByStrategy(strategyType string) TradeStats {
	e.mu.RLock()
	defer e.mu.RUnlock()

	// Filter trades by strategy
	var filteredTrades []*Trade
	if strategyType == "" {
		filteredTrades = e.trades
	} else {
		for _, trade := range e.trades {
			if trade.StrategyType == strategyType {
				filteredTrades = append(filteredTrades, trade)
			}
		}
	}

	stats := TradeStats{
		TotalTrades: len(filteredTrades),
	}

	if len(filteredTrades) == 0 {
		return stats
	}

	var totalPnL float64
	var winCount int
	var lossCount int
	var totalWins float64
	var totalLosses float64

	for _, trade := range filteredTrades {
		totalPnL += trade.PnL
		if trade.PnL > 0 {
			winCount++
			totalWins += trade.PnL
		} else if trade.PnL < 0 {
			lossCount++
			totalLosses += trade.PnL
		}
	}

	stats.NetPnL = totalPnL
	stats.WinCount = winCount
	stats.LossCount = lossCount

	if stats.TotalTrades > 0 {
		stats.WinRate = float64(winCount) / float64(stats.TotalTrades)
	}

	if lossCount > 0 && totalLosses < 0 {
		stats.ProfitFactor = totalWins / (-totalLosses)
	} else if winCount > 0 && lossCount == 0 {
		stats.ProfitFactor = math.Inf(1) // perfect win rate
	}

	if stats.TotalTrades > 0 {
		stats.AvgPnL = totalPnL / float64(stats.TotalTrades)
	}

	return stats
}
