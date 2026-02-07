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

	// Simulate immediate fill with slippage
	// Note: In real implementation, this would get current market price
	// For paper trading, we'll need to pass the current price or get it from market data
	// For now, we'll mark it as filled and set price to 0 (will be updated externally)
	order.Status = OrderStatusFilled
	order.FilledSize = size

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
		Status:        OrderStatusNew,
		CreatedAt:     now,
		UpdatedAt:     now,
		ClientOrderID: fmt.Sprintf("paper_%s_%d", symbol, now.UnixNano()),
	}

	// For paper trading, simulate immediate fill at limit price
	order.Status = OrderStatusFilled
	order.FilledPrice = price
	order.FilledSize = size
	order.UpdatedAt = now

	p.mu.Lock()
	p.orders[orderID] = order
	p.mu.Unlock()

	return order, nil
}

func (p *PaperExecutor) SimulateFill(order *Order, marketPrice float64) {
	if order == nil || order.Status == OrderStatusFilled {
		return
	}

	p.mu.Lock()
	defer p.mu.Unlock()

	// Apply slippage
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

func (p *PaperExecutor) CancelOrder(orderID string) error {
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

func (p *PaperExecutor) GetOrder(orderID string) (*Order, error) {
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
