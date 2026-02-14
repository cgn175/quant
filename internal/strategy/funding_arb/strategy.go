package fundingarb

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

// Strategy implements a funding rate carry trade.
//
// When funding rate is extremely positive (longs pay shorts), we go SHORT
// on the perpetual futures contract to collect funding payments.
// When funding normalizes, we close the position.
//
// This is a simplified "carry only" strategy — not fully delta-neutral
// (no spot leg). Use with isolated margin and tight position sizing.
type Strategy struct {
	cfg        config.FundingArbConfig
	client     exchange.Client
	executor   execution.Executor
	execEngine *execution.Engine
	symbols    []string

	mu        sync.RWMutex
	positions map[string]*arbPosition // symbol -> active position
}

// arbPosition tracks an active funding arb position.
type arbPosition struct {
	Symbol           string
	Side             string // "SHORT" (collecting positive funding) or "LONG" (collecting negative funding)
	EntryPrice       float64
	Size             float64
	EntryTime        time.Time
	EntryFunding     float64 // funding rate at entry
	FundingCollected float64 // estimated total funding collected
	FundingPayments  int     // number of funding payments received
}

func NewStrategy(cfg config.FundingArbConfig, client exchange.Client, executor execution.Executor, execEngine *execution.Engine, symbols []string) *Strategy {
	return &Strategy{
		cfg:        cfg,
		client:     client,
		executor:   executor,
		execEngine: execEngine,
		symbols:    symbols,
		positions:  make(map[string]*arbPosition),
	}
}

func (s *Strategy) Start(ctx context.Context) error {
	log.Info().
		Float64("min_funding", s.cfg.MinFundingRate).
		Float64("exit_threshold", s.cfg.ExitThreshold).
		Int("max_positions", s.cfg.MaxPositions).
		Float64("position_size_usd", s.cfg.PositionSizeUSD).
		Msg("starting funding rate arbitrage strategy")

	// Run the main scan loop
	go s.runLoop(ctx)
	return nil
}

func (s *Strategy) runLoop(ctx context.Context) {
	// Check funding rates on a regular interval (default: every 8 hours to match funding period)
	scanInterval := time.Duration(s.cfg.ScanIntervalMs) * time.Millisecond
	if scanInterval <= 0 {
		scanInterval = 8 * time.Hour
	}

	ticker := time.NewTicker(scanInterval)
	defer ticker.Stop()

	// Do an initial scan immediately
	s.scanAndManage()

	for {
		select {
		case <-ctx.Done():
			s.closeAllPositions()
			return
		case <-ticker.C:
			s.scanAndManage()
		}
	}
}

// scanAndManage checks funding rates and opens/closes positions accordingly.
func (s *Strategy) scanAndManage() {
	// Fetch all funding rates
	rates, err := s.client.FetchFundingRates(s.symbols)
	if err != nil {
		log.Error().Err(err).Msg("failed to fetch funding rates")
		return
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	for _, sym := range s.symbols {
		info, ok := rates[sym]
		if !ok {
			continue
		}

		fundingRate := info.FundingRate
		pos, hasPos := s.positions[sym]

		if hasPos {
			// --- Manage existing position ---
			s.managePosition(sym, pos, fundingRate, info.MarkPrice)
		} else {
			// --- Look for new entry ---
			s.checkEntry(sym, fundingRate, info.MarkPrice)
		}
	}
}

// checkEntry opens a position if funding rate exceeds threshold.
func (s *Strategy) checkEntry(sym string, fundingRate, markPrice float64) {
	// Check max positions
	if s.cfg.MaxPositions > 0 && len(s.positions) >= s.cfg.MaxPositions {
		return
	}

	absFunding := math.Abs(fundingRate)
	if absFunding < s.cfg.MinFundingRate {
		return // funding not attractive enough
	}

	// Determine direction: counter-trade the crowd
	var side string
	var orderSide execution.OrderSide
	if fundingRate > 0 {
		// Positive funding: longs pay shorts → go SHORT to collect
		side = "SHORT"
		orderSide = execution.OrderSideSell
	} else {
		// Negative funding: shorts pay longs → go LONG to collect
		side = "LONG"
		orderSide = execution.OrderSideBuy
	}

	// Position sizing
	size := s.cfg.PositionSizeUSD / markPrice
	if size <= 0 {
		return
	}

	// Execute entry
	order, err := s.executor.ExecuteMarketOrder(sym, orderSide, size)
	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Str("side", side).Msg("funding arb: entry failed")
		return
	}

	s.positions[sym] = &arbPosition{
		Symbol:       sym,
		Side:         side,
		EntryPrice:   order.FilledPrice,
		Size:         order.FilledSize,
		EntryTime:    time.Now(),
		EntryFunding: fundingRate,
	}

	// Annualized yield: funding * 3 payments/day * 365 days
	annualizedYield := math.Abs(fundingRate) * 3 * 365 * 100

	log.Info().
		Str("symbol", sym).
		Str("side", side).
		Float64("entry_price", order.FilledPrice).
		Float64("size", order.FilledSize).
		Float64("funding_rate", fundingRate).
		Float64("annualized_yield_pct", annualizedYield).
		Msg("funding arb: opened position")
}

// managePosition checks if we should close an existing arb position.
func (s *Strategy) managePosition(sym string, pos *arbPosition, currentFunding, markPrice float64) {
	// Track estimated funding collection
	// (simplified: assumes we've been in since last check and received funding)
	if pos.Side == "SHORT" && currentFunding > 0 {
		payment := currentFunding * pos.Size * markPrice
		pos.FundingCollected += payment
		pos.FundingPayments++
	} else if pos.Side == "LONG" && currentFunding < 0 {
		payment := math.Abs(currentFunding) * pos.Size * markPrice
		pos.FundingCollected += payment
		pos.FundingPayments++
	}

	// Exit conditions:
	// 1. Funding has normalized (below exit threshold)
	// 2. Funding has flipped (we'd be paying instead of collecting)
	shouldClose := false
	reason := ""

	// Check max loss per position (directional risk protection)
	if s.cfg.MaxLossPct > 0 {
		var pricePnLPct float64
		if pos.Side == "SHORT" {
			pricePnLPct = (pos.EntryPrice - markPrice) / pos.EntryPrice
		} else {
			pricePnLPct = (markPrice - pos.EntryPrice) / pos.EntryPrice
		}
		if pricePnLPct < -s.cfg.MaxLossPct {
			shouldClose = true
			reason = "max_loss"
		}
	}

	absFunding := math.Abs(currentFunding)
	if absFunding < s.cfg.ExitThreshold {
		shouldClose = true
		reason = "funding_normalized"
	}

	// Check if funding flipped against us
	if pos.Side == "SHORT" && currentFunding < 0 {
		shouldClose = true
		reason = "funding_flipped"
	}
	if pos.Side == "LONG" && currentFunding > 0 {
		shouldClose = true
		reason = "funding_flipped"
	}

	if !shouldClose {
		return
	}

	// Close position
	_, err := s.execEngine.ClosePosition(
		sym,
		pos.Side,
		markPrice,
		pos.Size,
		reason,
		strategy.SignalNone,
		"funding_arb",
		pos.EntryPrice,
		pos.EntryTime,
	)

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("funding arb: close failed")
		return
	}

	// Calculate price PnL
	var pricePnL float64
	if pos.Side == "SHORT" {
		pricePnL = (pos.EntryPrice - markPrice) * pos.Size
	} else {
		pricePnL = (markPrice - pos.EntryPrice) * pos.Size
	}

	totalPnL := pricePnL + pos.FundingCollected

	log.Info().
		Str("symbol", sym).
		Str("side", pos.Side).
		Str("reason", reason).
		Float64("entry_price", pos.EntryPrice).
		Float64("exit_price", markPrice).
		Float64("price_pnl", pricePnL).
		Float64("funding_collected", pos.FundingCollected).
		Float64("total_pnl", totalPnL).
		Int("funding_payments", pos.FundingPayments).
		Msg("funding arb: closed position")

	delete(s.positions, sym)
}

func (s *Strategy) closeAllPositions() {
	s.mu.Lock()
	defer s.mu.Unlock()

	for sym, pos := range s.positions {
		var orderSide execution.OrderSide
		if pos.Side == "SHORT" {
			orderSide = execution.OrderSideBuy // close short by buying
		} else {
			orderSide = execution.OrderSideSell // close long by selling
		}

		_, err := s.executor.ExecuteMarketOrder(sym, orderSide, pos.Size)
		if err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("funding arb: shutdown close failed")
		} else {
			log.Info().Str("symbol", sym).Msg("funding arb: closed position on shutdown")
		}
	}
	s.positions = make(map[string]*arbPosition)
}
