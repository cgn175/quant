package marketmaking

import (
	"context"
	"math"
	"sync"
	"time"

	"github.com/rs/zerolog/log"

	"github.com/cgn175/quant-bot/internal/config"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/execution"
	"github.com/cgn175/quant-bot/internal/strategy"
)

type Strategy struct {
	cfg        config.MarketMakingConfig
	client     exchange.Client
	executor   execution.Executor
	execEngine *execution.Engine
	symbols    []string

	// State
	mu        sync.RWMutex
	prices    map[string]float64
	orders    map[string][]*execution.Order // symbol -> active orders
	pending   map[string]*pendingRoundTrip  // symbol -> incomplete round trip
	inventory map[string]float64            // symbol -> net inventory (positive = long)
	returns   map[string]*ringBuffer        // symbol -> rolling returns for vol calc
}

// pendingRoundTrip tracks when we've filled one side of a buy/sell pair.
type pendingRoundTrip struct {
	buyFilled  bool
	sellFilled bool
	buyPrice   float64
	sellPrice  float64
	size       float64
	buyTime    time.Time
	sellTime   time.Time
}

// ringBuffer is a simple circular buffer for rolling calculations.
type ringBuffer struct {
	data []float64
	pos  int
	full bool
	size int
}

func newRingBuffer(size int) *ringBuffer {
	return &ringBuffer{data: make([]float64, size), size: size}
}

func (rb *ringBuffer) Add(v float64) {
	rb.data[rb.pos] = v
	rb.pos = (rb.pos + 1) % rb.size
	if rb.pos == 0 {
		rb.full = true
	}
}

func (rb *ringBuffer) Len() int {
	if rb.full {
		return rb.size
	}
	return rb.pos
}

// Stddev returns the standard deviation of the buffered values.
func (rb *ringBuffer) Stddev() float64 {
	n := rb.Len()
	if n < 2 {
		return 0
	}
	var sum, sumSq float64
	for i := 0; i < n; i++ {
		sum += rb.data[i]
		sumSq += rb.data[i] * rb.data[i]
	}
	mean := sum / float64(n)
	variance := sumSq/float64(n) - mean*mean
	if variance < 0 {
		return 0
	}
	return math.Sqrt(variance)
}

// Mean returns the average of the buffered values.
func (rb *ringBuffer) Mean() float64 {
	n := rb.Len()
	if n == 0 {
		return 0
	}
	var sum float64
	for i := 0; i < n; i++ {
		sum += rb.data[i]
	}
	return sum / float64(n)
}

func NewStrategy(cfg config.MarketMakingConfig, client exchange.Client, executor execution.Executor, execEngine *execution.Engine, symbols []string) *Strategy {
	// Initialize ring buffers for volatility tracking
	returns := make(map[string]*ringBuffer)
	lookback := cfg.VolLookback
	if lookback <= 0 {
		lookback = 20
	}
	for _, sym := range symbols {
		returns[sym] = newRingBuffer(lookback)
	}

	return &Strategy{
		cfg:        cfg,
		client:     client,
		executor:   executor,
		execEngine: execEngine,
		symbols:    symbols,
		prices:     make(map[string]float64),
		orders:     make(map[string][]*execution.Order),
		pending:    make(map[string]*pendingRoundTrip),
		inventory:  make(map[string]float64),
		returns:    returns,
	}
}

func (s *Strategy) Start(ctx context.Context) error {
	log.Info().
		Float64("gamma", s.cfg.Gamma).
		Float64("max_inventory", s.cfg.MaxInventory).
		Float64("min_spread", s.cfg.MinSpreadPct).
		Float64("max_spread", s.cfg.MaxSpreadPct).
		Msg("starting market making strategy with inventory skew")

	// Subscribe to OrderBooks for price updates
	for _, sym := range s.symbols {
		if err := s.client.SubscribeOrderBook(sym, func(ob exchange.OrderBook) {
			s.updatePriceFromOB(ob)
		}); err != nil {
			return err
		}
	}

	// Start control loop
	go s.runLoop(ctx)
	return nil
}

func (s *Strategy) updatePriceFromOB(ob exchange.OrderBook) {
	if len(ob.Bids) == 0 || len(ob.Asks) == 0 {
		return
	}
	bestBid := ob.Bids[0].Price
	bestAsk := ob.Asks[0].Price
	midPrice := (bestBid + bestAsk) / 2

	s.mu.Lock()
	defer s.mu.Unlock()

	// Track returns for volatility estimation
	if prevPrice, ok := s.prices[ob.Symbol]; ok && prevPrice > 0 {
		ret := (midPrice - prevPrice) / prevPrice
		if rb, ok := s.returns[ob.Symbol]; ok {
			rb.Add(ret)
		}
	}

	s.prices[ob.Symbol] = midPrice
}

func (s *Strategy) runLoop(ctx context.Context) {
	ticker := time.NewTicker(time.Duration(s.cfg.RefreshTimeMs) * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			s.cancelAllOrders()
			return
		case <-ticker.C:
			s.refreshOrders(ctx)
		}
	}
}

func (s *Strategy) refreshOrders(ctx context.Context) {
	s.mu.Lock()
	defer s.mu.Unlock()

	for _, sym := range s.symbols {
		price, ok := s.prices[sym]
		if !ok || price == 0 {
			continue
		}

		// 1. Check for filled orders and record round trips
		s.checkFills(sym)

		// 2. Cancel existing orders
		if existing, ok := s.orders[sym]; ok {
			for _, order := range existing {
				_ = s.executor.CancelOrder(sym, order.ID)
			}
		}

		// Clear tracked orders
		s.orders[sym] = make([]*execution.Order, 0)

		// 3. Compute reservation price (Avellaneda-Stoikov skew)
		inv := s.inventory[sym]
		vol := s.getVolatility(sym)
		reservationPrice := price - inv*s.cfg.Gamma*vol*vol*price

		// 4. Compute dynamic spread (volatility-adjusted)
		spread := s.computeDynamicSpread(sym, price, vol)

		// 5. Calculate skewed bid/ask
		bidPrice := reservationPrice - spread
		askPrice := reservationPrice + spread

		// 6. Inventory guard — halt quoting on one side if max inventory exceeded
		placeBuy := true
		placeSell := true
		if s.cfg.MaxInventory > 0 {
			if inv >= s.cfg.MaxInventory {
				placeBuy = false // already too long, don't buy more
			}
			if inv <= -s.cfg.MaxInventory {
				placeSell = false // already too short, don't sell more
			}
		}

		// 7. Place orders
		if placeBuy {
			buyOrder, err := s.executor.ExecuteLimitOrder(sym, execution.OrderSideBuy, bidPrice, s.cfg.OrderAmount)
			if err != nil {
				log.Error().Err(err).Str("symbol", sym).Msg("failed to place buy order")
			} else {
				s.orders[sym] = append(s.orders[sym], buyOrder)
			}
		}

		if placeSell {
			sellOrder, err := s.executor.ExecuteLimitOrder(sym, execution.OrderSideSell, askPrice, s.cfg.OrderAmount)
			if err != nil {
				log.Error().Err(err).Str("symbol", sym).Msg("failed to place sell order")
			} else {
				s.orders[sym] = append(s.orders[sym], sellOrder)
			}
		}

		log.Info().
			Str("symbol", sym).
			Float64("mid_price", price).
			Float64("reservation", reservationPrice).
			Float64("bid", bidPrice).
			Float64("ask", askPrice).
			Float64("spread_pct", spread/price*100).
			Float64("inventory", inv).
			Float64("volatility", vol).
			Bool("buy_active", placeBuy).
			Bool("sell_active", placeSell).
			Msg("refreshed market making orders")
	}
}

// getVolatility returns the rolling standard deviation of returns for a symbol.
// Returns 0 if insufficient data (fallback: use base spread).
func (s *Strategy) getVolatility(sym string) float64 {
	rb, ok := s.returns[sym]
	if !ok || rb.Len() < 5 {
		return 0
	}
	return rb.Stddev()
}

// computeDynamicSpread scales the base spread by relative volatility.
// In calm markets spread tightens (more fills); in volatile markets it widens (less adverse selection).
func (s *Strategy) computeDynamicSpread(sym string, price, vol float64) float64 {
	baseSpread := price * s.cfg.SpreadPct

	if vol <= 0 {
		// Not enough data yet — use base spread
		return baseSpread
	}

	// Average volatility as baseline
	rb, ok := s.returns[sym]
	if !ok {
		return baseSpread
	}
	avgVol := rb.Mean()
	if avgVol == 0 {
		// All returns are zero (e.g. stable price), use stddev directly
		return baseSpread
	}

	// Scale: currentVol / avgVol
	// When vol > avg → spread widens, when vol < avg → spread tightens
	ratio := math.Abs(vol / avgVol)
	if ratio < 0.1 {
		ratio = 0.1 // prevent spread from collapsing to near zero
	}
	if ratio > 10 {
		ratio = 10 // cap extreme widening
	}

	dynamicSpread := baseSpread * ratio

	// Clamp to [min, max]
	minSpread := price * s.cfg.MinSpreadPct
	maxSpread := price * s.cfg.MaxSpreadPct
	if minSpread > 0 && dynamicSpread < minSpread {
		dynamicSpread = minSpread
	}
	if maxSpread > 0 && dynamicSpread > maxSpread {
		dynamicSpread = maxSpread
	}

	return dynamicSpread
}

// checkFills detects filled orders and tracks round trips + inventory.
func (s *Strategy) checkFills(sym string) {
	orders, ok := s.orders[sym]
	if !ok {
		return
	}

	// Initialize pending round trip if not exists
	if s.pending[sym] == nil {
		s.pending[sym] = &pendingRoundTrip{}
	}
	pending := s.pending[sym]

	for _, order := range orders {
		latestOrder, err := s.executor.GetOrder(sym, order.ID)
		if err != nil {
			continue
		}

		if latestOrder.Status == execution.OrderStatusFilled {
			if latestOrder.Side == execution.OrderSideBuy && !pending.buyFilled {
				pending.buyFilled = true
				pending.buyPrice = latestOrder.FilledPrice
				pending.size = latestOrder.FilledSize
				pending.buyTime = latestOrder.UpdatedAt
				// Update inventory: bought → inventory increases
				s.inventory[sym] += latestOrder.FilledSize
			} else if latestOrder.Side == execution.OrderSideSell && !pending.sellFilled {
				pending.sellFilled = true
				pending.sellPrice = latestOrder.FilledPrice
				pending.sellTime = latestOrder.UpdatedAt
				// Update inventory: sold → inventory decreases
				s.inventory[sym] -= latestOrder.FilledSize
			}
		}
	}

	// If both buy and sell filled, record the round trip
	if pending.buyFilled && pending.sellFilled {
		s.recordRoundTrip(sym, pending)
		s.pending[sym] = &pendingRoundTrip{}
	}
}

// recordRoundTrip registers a completed round trip with the execution engine.
func (s *Strategy) recordRoundTrip(sym string, rt *pendingRoundTrip) {
	_, err := s.execEngine.ClosePosition(
		sym,
		"LONG",
		rt.sellPrice,
		rt.size,
		"mm_roundtrip",
		strategy.SignalNone,
		"market_making",
		rt.buyPrice,
		rt.buyTime,
	)

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to record MM round trip")
		return
	}

	pnl := (rt.sellPrice - rt.buyPrice) * rt.size
	log.Info().
		Str("symbol", sym).
		Float64("buy_price", rt.buyPrice).
		Float64("sell_price", rt.sellPrice).
		Float64("size", rt.size).
		Float64("pnl_gross", pnl).
		Float64("inventory", s.inventory[sym]).
		Msg("MM round trip completed")
}

func (s *Strategy) cancelAllOrders() {
	s.mu.Lock()
	defer s.mu.Unlock()

	for sym, orders := range s.orders {
		for _, order := range orders {
			s.executor.CancelOrder(sym, order.ID)
		}
	}
	s.orders = make(map[string][]*execution.Order)
}
