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
	"github.com/cgn175/quant-bot/internal/metrics"
	"github.com/cgn175/quant-bot/internal/strategy"
)

// VolatilityRegime represents the current market volatility state
type VolatilityRegime int

const (
	VolCalm VolatilityRegime = iota      // ATR% < 2%
	VolNormal                            // ATR% 2-5%
	VolElevated                          // ATR% 5-10%
	VolExtreme                           // ATR% > 10%
)

// String returns the string representation of the volatility regime
func (v VolatilityRegime) String() string {
	switch v {
	case VolCalm:
		return "calm"
	case VolNormal:
		return "normal"
	case VolElevated:
		return "elevated"
	case VolExtreme:
		return "extreme"
	default:
		return "unknown"
	}
}

type Strategy struct {
	cfg        config.MarketMakingConfig
	client     exchange.Client
	executor   execution.Executor
	execEngine *execution.Engine
	symbols    []string
	metrics    *metrics.Metrics

	// State
	mu        sync.RWMutex
	prices    map[string]float64
	orders    map[string][]*execution.Order // symbol -> active orders
	pending   map[string]*pendingRoundTrip  // symbol -> incomplete round trip
	inventory map[string]float64            // symbol -> net inventory (positive = long)
	returns   map[string]*ringBuffer        // symbol -> rolling returns for vol calc
	orderBooks map[string]exchange.OrderBook // symbol -> latest order book snapshot

	// Volatility regime tracking (BTC/ETH as market proxies)
	btcPrices     *ringBuffer      // rolling window for BTC prices (ATR calc)
	ethPrices     *ringBuffer      // rolling window for ETH prices (ATR calc)
	btcHighs      *ringBuffer      // rolling window for BTC highs
	btcLows       *ringBuffer      // rolling window for BTC lows
	ethHighs      *ringBuffer      // rolling window for ETH highs
	ethLows       *ringBuffer      // rolling window for ETH lows
	currentRegime VolatilityRegime // current market volatility regime
	lastRegime    VolatilityRegime // for detecting regime changes
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

// Get returns the value at the given index (0 = most recent)
func (rb *ringBuffer) Get(idx int) float64 {
	if idx < 0 || idx >= rb.Len() {
		return 0
	}
	// Calculate actual position
	pos := (rb.pos - 1 - idx + rb.size) % rb.size
	if rb.full {
		return rb.data[pos]
	}
	// Not full yet, adjust for partial buffer
	if pos >= rb.pos {
		return rb.data[pos-rb.size+rb.pos]
	}
	return rb.data[pos]
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

// TrueRange calculates the true range from high, low, close prices
func trueRange(high, low, closePrev float64) float64 {
	tr1 := high - low
	tr2 := math.Abs(high - closePrev)
	tr3 := math.Abs(low - closePrev)
	return math.Max(tr1, math.Max(tr2, tr3))
}

func NewStrategy(cfg config.MarketMakingConfig, client exchange.Client, executor execution.Executor, execEngine *execution.Engine, symbols []string, m *metrics.Metrics) *Strategy {
	// Initialize ring buffers for volatility tracking
	returns := make(map[string]*ringBuffer)
	lookback := cfg.VolLookback
	if lookback <= 0 {
		lookback = 20
	}
	for _, sym := range symbols {
		returns[sym] = newRingBuffer(lookback)
	}

	// Initialize ATR period for regime detection (default 14)
	atrPeriod := cfg.VolRegimeATRPeriod
	if atrPeriod <= 0 {
		atrPeriod = 14
	}

	return &Strategy{
		cfg:        cfg,
		client:     client,
		executor:   executor,
		execEngine: execEngine,
		symbols:    symbols,
		metrics:    m,
		prices:     make(map[string]float64),
		orders:     make(map[string][]*execution.Order),
		pending:    make(map[string]*pendingRoundTrip),
		inventory:  make(map[string]float64),
		returns:    returns,
		orderBooks: make(map[string]exchange.OrderBook),
		// Volatility regime buffers
		btcPrices: newRingBuffer(atrPeriod),
		ethPrices: newRingBuffer(atrPeriod),
		btcHighs:  newRingBuffer(atrPeriod),
		btcLows:   newRingBuffer(atrPeriod),
		ethHighs:  newRingBuffer(atrPeriod),
		ethLows:   newRingBuffer(atrPeriod),
		currentRegime: VolCalm,
		lastRegime:    VolCalm,
	}
}

func (s *Strategy) Start(ctx context.Context) error {
	log.Info().
		Float64("gamma", s.cfg.Gamma).
		Float64("max_inventory", s.cfg.MaxInventory).
		Float64("min_spread", s.cfg.MinSpreadPct).
		Float64("max_spread", s.cfg.MaxSpreadPct).
		Bool("vol_regime_enabled", s.cfg.VolRegimeEnabled).
		Msg("starting market making strategy with inventory skew")

	// Subscribe to OrderBooks for price updates
	for _, sym := range s.symbols {
		if err := s.client.SubscribeOrderBook(sym, func(ob exchange.OrderBook) {
			s.updatePriceFromOB(ob)
		}); err != nil {
			return err
		}
	}

	// Subscribe to BTC and ETH for volatility regime detection
	if s.cfg.VolRegimeEnabled {
		// Subscribe to BTC
		if err := s.client.SubscribeOrderBook("BTCUSDT", func(ob exchange.OrderBook) {
			s.updateProxyPriceFromOB("BTCUSDT", ob)
		}); err != nil {
			log.Warn().Err(err).Msg("failed to subscribe to BTCUSDT for volatility regime")
		}
		// Subscribe to ETH
		if err := s.client.SubscribeOrderBook("ETHUSDT", func(ob exchange.OrderBook) {
			s.updateProxyPriceFromOB("ETHUSDT", ob)
		}); err != nil {
			log.Warn().Err(err).Msg("failed to subscribe to ETHUSDT for volatility regime")
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

	// Store order book snapshot for imbalance calculation
	s.orderBooks[ob.Symbol] = ob

	// Track returns for volatility estimation
	if prevPrice, ok := s.prices[ob.Symbol]; ok && prevPrice > 0 {
		ret := (midPrice - prevPrice) / prevPrice
		if rb, ok := s.returns[ob.Symbol]; ok {
			rb.Add(ret)
		}
	}

	s.prices[ob.Symbol] = midPrice
}

// updateProxyPriceFromOB updates BTC/ETH price buffers for volatility regime detection
func (s *Strategy) updateProxyPriceFromOB(symbol string, ob exchange.OrderBook) {
	if len(ob.Bids) == 0 || len(ob.Asks) == 0 {
		return
	}
	bestBid := ob.Bids[0].Price
	bestAsk := ob.Asks[0].Price
	midPrice := (bestBid + bestAsk) / 2
	high := ob.Asks[0].Price // best ask as high proxy
	low := ob.Bids[0].Price  // best bid as low proxy

	s.mu.Lock()
	defer s.mu.Unlock()

	switch symbol {
	case "BTCUSDT":
		s.btcPrices.Add(midPrice)
		s.btcHighs.Add(high)
		s.btcLows.Add(low)
	case "ETHUSDT":
		s.ethPrices.Add(midPrice)
		s.ethHighs.Add(high)
		s.ethLows.Add(low)
	}
}

// calculateATRPercentage calculates ATR% for a symbol from the ring buffers
func (s *Strategy) calculateATRPercentage(prices, highs, lows *ringBuffer) float64 {
	n := prices.Len()
	if n < 2 {
		return 0
	}

	period := prices.Len()
	if period > prices.size {
		period = prices.size
	}

	var atrSum float64
	for i := 1; i < period; i++ {
		closePrice := prices.Get(i)
		high := highs.Get(i)
		low := lows.Get(i)
		prevClose := prices.Get(i - 1)
		_ = closePrice // not used directly, trueRange uses high/low/prevClose
		tr := trueRange(high, low, prevClose)
		atrSum += tr
	}

	atr := atrSum / float64(period-1)
	currentPrice := prices.Get(0)
	if currentPrice == 0 {
		return 0
	}

	return atr / currentPrice
}

// updateVolatilityRegime calculates market volatility regime based on BTC/ETH ATR%
func (s *Strategy) updateVolatilityRegime() VolatilityRegime {
	// Calculate ATR% for BTC and ETH
	btcATRPct := s.calculateATRPercentage(s.btcPrices, s.btcHighs, s.btcLows)
	ethATRPct := s.calculateATRPercentage(s.ethPrices, s.ethHighs, s.ethLows)

	// Use average of BTC and ETH as market regime proxy
	var avgATRPct float64
	if btcATRPct > 0 && ethATRPct > 0 {
		avgATRPct = (btcATRPct + ethATRPct) / 2
	} else if btcATRPct > 0 {
		avgATRPct = btcATRPct
	} else if ethATRPct > 0 {
		avgATRPct = ethATRPct
	} else {
		// Not enough data, assume calm
		return VolCalm
	}

	// Determine regime based on thresholds
	var regime VolatilityRegime
	switch {
	case avgATRPct < s.cfg.VolCalmThreshold:
		regime = VolCalm
	case avgATRPct < s.cfg.VolElevatedThreshold:
		regime = VolNormal
	case avgATRPct < s.cfg.VolExtremeThreshold:
		regime = VolElevated
	default:
		regime = VolExtreme
	}

	// Log regime changes
	if regime != s.lastRegime {
		log.Info().
			Str("old_regime", s.lastRegime.String()).
			Str("new_regime", regime.String()).
			Float64("btc_atr_pct", btcATRPct*100).
			Float64("eth_atr_pct", ethATRPct*100).
			Float64("avg_atr_pct", avgATRPct*100).
			Msg("volatility regime changed")
		s.lastRegime = regime
	}

	// Update metrics if available
	if s.metrics != nil && s.metrics.MMVolatilityRegime != nil {
		s.metrics.MMVolatilityRegime.WithLabelValues(regime.String()).Set(1)
		// Reset other regimes to 0
		for _, r := range []VolatilityRegime{VolCalm, VolNormal, VolElevated, VolExtreme} {
			if r != regime {
				s.metrics.MMVolatilityRegime.WithLabelValues(r.String()).Set(0)
			}
		}
	}

	s.currentRegime = regime
	return regime
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

	// Update volatility regime if enabled
	var regime VolatilityRegime
	var spreadMultiplier float64 = 1.0
	if s.cfg.VolRegimeEnabled {
		regime = s.updateVolatilityRegime()

		switch regime {
		case VolCalm:
			// Normal quoting
			spreadMultiplier = 1.0
		case VolNormal:
			// Slightly wider spreads (1.5x)
			spreadMultiplier = 1.5
		case VolElevated:
			// Wide spreads (configurable multiplier, default 3x)
			spreadMultiplier = s.cfg.VolSpreadMultiplier
			if spreadMultiplier < 1.0 {
				spreadMultiplier = 3.0
			}
		case VolExtreme:
			// HALT quoting entirely
			log.Warn().
				Str("regime", regime.String()).
				Msg("market making halted due to extreme volatility")
			if s.metrics != nil {
				s.metrics.MMQuotesHaltedTotal.Inc()
			}
			s.cancelAllOrders()
			return
		}
	}

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

		// 4. Compute dynamic spread (volatility-adjusted with regime multiplier)
		spread := s.computeDynamicSpread(sym, price, vol, spreadMultiplier)

		// 5. Apply order book imbalance skew (if enabled)
		bidSpread := spread
		askSpread := spread
		imbalance := 0.0

		if s.cfg.ImbalanceEnabled {
			if ob, ok := s.orderBooks[sym]; ok {
				depth := s.cfg.ImbalanceDepth
				if depth <= 0 {
					depth = 20
				}
				imbalance = CalculateOrderBookImbalance(ob, depth)
				
				// Emit metric
				if s.metrics != nil && s.metrics.MMOrderBookImbalance != nil {
					s.metrics.MMOrderBookImbalance.WithLabelValues(sym).Set(imbalance)
				}
				
				skewFactor := s.cfg.ImbalanceSkewFactor
				if skewFactor <= 0 {
					skewFactor = 0.5
				}
				
				bidSpread, askSpread = AdjustSpreadForImbalance(spread, imbalance, skewFactor)
			}
		}

		// 6. Calculate skewed bid/ask
		bidPrice := reservationPrice - bidSpread
		askPrice := reservationPrice + askSpread

		// 7. Inventory guard — halt quoting on one side if max inventory exceeded
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

		// 8. Place orders
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
			Float64("bid_spread_pct", bidSpread/price*100).
			Float64("ask_spread_pct", askSpread/price*100).
			Float64("imbalance", imbalance).
			Float64("inventory", inv).
			Float64("volatility", vol).
			Bool("buy_active", placeBuy).
			Bool("sell_active", placeSell).
			Str("vol_regime", regime.String()).
			Float64("spread_multiplier", spreadMultiplier).
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

// computeDynamicSpread scales the base spread by relative volatility and regime multiplier.
// In calm markets spread tightens (more fills); in volatile markets it widens (less adverse selection).
func (s *Strategy) computeDynamicSpread(sym string, price, vol, regimeMultiplier float64) float64 {
	baseSpread := price * s.cfg.SpreadPct

	if vol <= 0 {
		// Not enough data yet — use base spread with regime multiplier
		return baseSpread * regimeMultiplier
	}

	// Average volatility as baseline
	rb, ok := s.returns[sym]
	if !ok {
		return baseSpread * regimeMultiplier
	}
	avgVol := rb.Mean()
	if avgVol == 0 {
		// All returns are zero (e.g. stable price), use stddev directly
		return baseSpread * regimeMultiplier
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

	dynamicSpread := baseSpread * ratio * regimeMultiplier

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
// For paper trading, it also tries to fill limit orders based on current market price.
func (s *Strategy) checkFills(sym string) {
	orders, ok := s.orders[sym]
	if !ok {
		return
	}

	// Get current market price for paper trading fill simulation
	currentPrice := s.prices[sym]

	// Try to fill paper limit orders first
	if paperExec, ok := s.executor.(*execution.PaperExecutor); ok && currentPrice > 0 {
		for _, order := range orders {
			paperExec.TryFillLimitOrder(order.ID, currentPrice)
		}
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
	for sym, orders := range s.orders {
		for _, order := range orders {
			s.executor.CancelOrder(sym, order.ID)
		}
	}
	s.orders = make(map[string][]*execution.Order)
}
