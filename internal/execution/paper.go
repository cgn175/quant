package execution

import (
	"fmt"
	"sync"
	"sync/atomic"
	"time"
)

type PaperExecutor struct {
	mu         sync.RWMutex
	orders     map[string]*Order
	orderIDSeq uint64
	slippageBP float64
	feePercent float64
}

func NewPaperExecutor(slippageBP, feePercent float64) *PaperExecutor {
	return &PaperExecutor{
		orders:     make(map[string]*Order),
		slippageBP: slippageBP,
		feePercent: feePercent,
	}
}

func (p *PaperExecutor) ExecuteMarketOrder(symbol string, side OrderSide, size float64) (*Order, error) {
	if size <= 0 {
		return nil, fmt.Errorf("invalid size: %f", size)
	}

	orderID := p.nextOrderID()
	now := time.Now()

	order := &Order{
		ID:            orderID,
		Symbol:        symbol,
		Type:          OrderTypeMarket,
		Side:          side,
		Size:          size,
		Status:        OrderStatusNew,
		CreatedAt:     now,
		UpdatedAt:     now,
		ClientOrderID: fmt.Sprintf("paper_%s_%d", symbol, now.UnixNano()),
	}

	// Market orders are left in NEW status with FilledPrice = 0.
	// The caller MUST call SimulateFill(order, marketPrice) to set the
	// filled price with slippage applied and transition to FILLED.
	// This prevents the old bug where FilledPrice stayed 0 because
	// SimulateFill short-circuited on already-FILLED orders.

	p.mu.Lock()
	p.orders[orderID] = order
	p.mu.Unlock()

	return order, nil
}

func (p *PaperExecutor) ExecuteLimitOrder(symbol string, side OrderSide, price, size float64) (*Order, error) {
	if size <= 0 {
		return nil, fmt.Errorf("invalid size: %f", size)
	}
	if price <= 0 {
		return nil, fmt.Errorf("invalid price: %f", price)
	}

	orderID := p.nextOrderID()
	now := time.Now()

	order := &Order{
		ID:            orderID,
		Symbol:        symbol,
		Type:          OrderTypeLimit,
		Side:          side,
		Price:         price,
		Size:          size,
		Status:        OrderStatusFilled,
		FilledPrice:   price,
		FilledSize:    size,
		CreatedAt:     now,
		UpdatedAt:     now,
		ClientOrderID: fmt.Sprintf("paper_%s_%d", symbol, now.UnixNano()),
	}

	p.mu.Lock()
	p.orders[orderID] = order
	p.mu.Unlock()

	return order, nil
}

// SimulateFill fills a market order at the given market price with slippage
// applied. For BUY orders the fill price is nudged up; for SELL orders it is
// nudged down, modelling realistic adverse slippage.
//
// It is safe to call on an order that is already filled (idempotent).
func (p *PaperExecutor) SimulateFill(order *Order, marketPrice float64) {
	if order == nil {
		return
	}

	p.mu.Lock()
	defer p.mu.Unlock()

	// Skip if the order already has a valid filled price (e.g. limit orders).
	if order.Status == OrderStatusFilled && order.FilledPrice > 0 {
		return
	}

	// Apply slippage: buys fill slightly above market, sells slightly below.
	slippageMultiplier := 1.0 + (p.slippageBP / 10000.0)
	if order.Side == OrderSideBuy {
		order.FilledPrice = marketPrice * slippageMultiplier
	} else {
		order.FilledPrice = marketPrice / slippageMultiplier
	}

	order.FilledSize = order.Size
	order.Status = OrderStatusFilled
	order.UpdatedAt = time.Now()
}

func (p *PaperExecutor) CancelOrder(symbol string, orderID string) error {
	p.mu.Lock()
	defer p.mu.Unlock()

	order, exists := p.orders[orderID]
	if !exists {
		return fmt.Errorf("order not found: %s", orderID)
	}

	if order.Status == OrderStatusFilled {
		return fmt.Errorf("cannot cancel filled order: %s", orderID)
	}

	order.Status = OrderStatusCanceled
	order.UpdatedAt = time.Now()

	return nil
}

func (p *PaperExecutor) GetOrder(symbol string, orderID string) (*Order, error) {
	p.mu.RLock()
	defer p.mu.RUnlock()

	order, exists := p.orders[orderID]
	if !exists {
		return nil, fmt.Errorf("order not found: %s", orderID)
	}

	return order, nil
}

func (p *PaperExecutor) Close() error {
	return nil
}

func (p *PaperExecutor) nextOrderID() string {
	seq := atomic.AddUint64(&p.orderIDSeq, 1)
	return fmt.Sprintf("PAPER_%d", seq)
}

func (p *PaperExecutor) ApplySlippage(price float64, side OrderSide) float64 {
	slippageMultiplier := 1.0 + (p.slippageBP / 10000.0)
	if side == OrderSideBuy {
		return price * slippageMultiplier
	}
	return price / slippageMultiplier
}

func (p *PaperExecutor) CalculateFee(notional float64) float64 {
	return notional * (p.feePercent / 100.0)
}
