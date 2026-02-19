package fundingarb

import (
	"context"
	"math"
	"sync"
	"time"

	"github.com/rs/zerolog/log"

	"github.com/cgn175/quant-bot/internal/config"
	"github.com/cgn175/quant-bot/internal/data"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/execution"
	"github.com/cgn175/quant-bot/internal/risk"
	"github.com/cgn175/quant-bot/internal/strategy"
)

// Strategy implements a funding rate carry trade with cross-exchange support.
//
// Single exchange mode: When funding rate is extremely positive (longs pay shorts), 
// we go SHORT on the perpetual futures contract to collect funding payments.
//
// Cross-exchange mode: Short high-funding exchange and long low-funding exchange
// to capture the funding rate differential while maintaining market neutrality.
type Strategy struct {
	cfg              config.FundingArbConfig
	client           exchange.Client
	executor         execution.Executor
	execEngine       *execution.Engine
	store            *data.FundingStore
	symbols          []string
	portfolioMonitor *risk.PortfolioMonitor

	// Cross-exchange support
	crossExchangeManager *CrossExchangeManager
	crossExchangeEnabled bool

	mu        sync.RWMutex
	positions map[string]*arbPosition // symbol -> active position
}

// arbPosition tracks an active funding arb position.
type arbPosition struct {
	dbID             int64 // row ID in arb_positions table
	Symbol           string
	Side             string // "SHORT" (collecting positive funding) or "LONG" (collecting negative funding)
	EntryPrice       float64
	Size             float64
	EntryTime        time.Time
	EntryFunding     float64 // funding rate at entry
	FundingCollected float64 // estimated total funding collected
	FundingPayments  int     // number of funding payments received
	SpotEntryPrice   float64 // spot hedge entry price (0 if no hedge)
	SpotSize         float64 // spot hedge size (0 if no hedge)
	
	// Cross-exchange fields
	IsCrossExchange  bool   // true if this is a cross-exchange position
	HighExchange     string // exchange with higher funding rate (short leg)
	LowExchange      string // exchange with lower funding rate (long leg)
	HighFundingRate  float64 // funding rate on high exchange
	LowFundingRate   float64 // funding rate on low exchange
}

func NewStrategy(cfg config.FundingArbConfig, exchangeCfg config.ExchangeConfig, client exchange.Client, executor execution.Executor, execEngine *execution.Engine, symbols []string, store *data.FundingStore, portfolioMonitor *risk.PortfolioMonitor) *Strategy {
	s := &Strategy{
		cfg:              cfg,
		client:           client,
		executor:         executor,
		execEngine:       execEngine,
		store:            store,
		symbols:          symbols,
		portfolioMonitor: portfolioMonitor,
		positions:        make(map[string]*arbPosition),
		crossExchangeEnabled: cfg.CrossExchange,
	}
	
	// Initialize cross-exchange manager if enabled
	if cfg.CrossExchange {
		s.crossExchangeManager = NewCrossExchangeManager(store)
		
		// Add configured exchanges
		for _, exchangeName := range cfg.Exchanges {
			switch exchangeName {
			case "binance":
				log.Info().Str("exchange", "binance").Msg("binance client already available")
			case "bybit":
				var bybitClient exchange.CrossExchangeClient
				if exchangeCfg.BybitAPIKey != "" && exchangeCfg.BybitAPISecret != "" {
					bybitClient = exchange.NewBybitAuthClient(exchangeCfg.BybitTestnet, exchangeCfg.BybitAPIKey, exchangeCfg.BybitAPISecret)
					log.Info().Str("exchange", "bybit").Bool("authenticated", true).Msg("added authenticated bybit client")
				} else {
					bybitClient = exchange.NewBybitClient(exchangeCfg.BybitTestnet)
					log.Info().Str("exchange", "bybit").Bool("authenticated", false).Msg("added read-only bybit client")
				}
				s.crossExchangeManager.AddExchange("bybit", bybitClient)
			case "okx":
				var okxClient exchange.CrossExchangeClient
				if exchangeCfg.OKXAPIKey != "" && exchangeCfg.OKXAPISecret != "" {
					okxClient = exchange.NewOKXAuthClient(exchangeCfg.OKXAPIKey, exchangeCfg.OKXAPISecret, exchangeCfg.OKXPassphrase)
					log.Info().Str("exchange", "okx").Bool("authenticated", true).Msg("added authenticated okx client")
				} else {
					okxClient = exchange.NewOKXClient()
					log.Info().Str("exchange", "okx").Bool("authenticated", false).Msg("added read-only okx client")
				}
				s.crossExchangeManager.AddExchange("okx", okxClient)
			}
		}
	}
	
	return s
}

func (s *Strategy) Start(ctx context.Context) error {
	log.Info().
		Float64("min_funding", s.cfg.MinFundingRate).
		Float64("exit_threshold", s.cfg.ExitThreshold).
		Int("max_positions", s.cfg.MaxPositions).
		Float64("position_size_usd", s.cfg.PositionSizeUSD).
		Msg("starting funding rate arbitrage strategy")

	// Restore open positions from DB
	if s.store != nil {
		if err := s.restorePositions(); err != nil {
			log.Error().Err(err).Msg("failed to restore arb positions from DB")
		}
	}

	// Run the main scan loop
	go s.runLoop(ctx)
	return nil
}

// restorePositions loads open positions from the database into the in-memory map.
func (s *Strategy) restorePositions() error {
	positions, err := s.store.LoadOpenPositions()
	if err != nil {
		return err
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	for _, p := range positions {
		s.positions[p.Symbol] = &arbPosition{
			dbID:             p.ID,
			Symbol:           p.Symbol,
			Side:             p.Side,
			EntryPrice:       p.EntryPrice,
			Size:             p.Size,
			EntryTime:        p.EntryTime,
			EntryFunding:     p.EntryFunding,
			FundingCollected: p.FundingCollected,
			FundingPayments:  p.FundingPayments,
			SpotEntryPrice:   p.SpotEntryPrice,
			SpotSize:         p.SpotSize,
		}
		log.Info().
			Str("symbol", p.Symbol).
			Str("side", p.Side).
			Float64("entry_price", p.EntryPrice).
			Float64("size", p.Size).
			Msg("funding arb: restored position from DB")
	}

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
	s.mu.Lock()
	defer s.mu.Unlock()

	now := time.Now()

	// Cross-exchange mode
	if s.crossExchangeEnabled && s.crossExchangeManager != nil {
		opportunities, err := s.crossExchangeManager.ScanCrossExchangeOpportunities(s.symbols, s.cfg.MinSpreadBps)
		if err != nil {
			log.Error().Err(err).Msg("failed to scan cross-exchange opportunities")
			return
		}

		for _, opp := range opportunities {
			pos, hasPos := s.positions[opp.Symbol]
			if hasPos {
				s.manageCrossExchangePosition(opp.Symbol, pos, opp)
			} else {
				s.checkCrossExchangeEntry(opp)
			}
		}
		return
	}

	// Single exchange mode (original logic)
	rates, err := s.client.FetchFundingRates(s.symbols)
	if err != nil {
		log.Error().Err(err).Msg("failed to fetch funding rates")
		return
	}

	for _, sym := range s.symbols {
		info, ok := rates[sym]
		if !ok {
			continue
		}

		fundingRate := info.FundingRate

		// Persist every funding rate snapshot
		if s.store != nil {
			if err := s.store.InsertFundingRate(sym, fundingRate, info.MarkPrice, now); err != nil {
				log.Error().Err(err).Str("symbol", sym).Msg("failed to persist funding rate")
			}
		}

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
	
	// Momentum strategy: check if funding is high AND accelerating
	if s.cfg.UseMomentum {
		avg24h := CalculateFundingAverage(s.store, sym, 24)
		multiplier := s.cfg.MomentumMultiplier
		if multiplier <= 0 {
			multiplier = 1.2 // default
		}
		
		if !CheckFundingMomentum(fundingRate, s.cfg.MinFundingRate, avg24h, multiplier) {
			return // momentum conditions not met
		}
		
		log.Debug().
			Str("symbol", sym).
			Float64("current_funding", fundingRate).
			Float64("avg_24h", avg24h).
			Float64("multiplier", multiplier).
			Msg("funding arb: momentum entry conditions met")
	} else {
		// Static threshold strategy (legacy)
		if absFunding < s.cfg.MinFundingRate {
			return // funding not attractive enough
		}
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

	notional := size * markPrice

	// Check portfolio monitor for cross-strategy limits
	if s.portfolioMonitor != nil {
		canEnter, reason := s.portfolioMonitor.CanEnter(sym, notional, "funding_arb")
		if !canEnter {
			log.Warn().
				Str("symbol", sym).
				Str("reason", reason).
				Float64("notional", notional).
				Msg("funding arb: entry blocked by portfolio monitor")
			return
		}
	}

	// Execute perp entry
	order, err := s.executor.ExecuteMarketOrder(sym, orderSide, size)
	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Str("side", side).Msg("funding arb: perp entry failed")
		return
	}

	pos := &arbPosition{
		Symbol:       sym,
		Side:         side,
		EntryPrice:   order.FilledPrice,
		Size:         order.FilledSize,
		EntryTime:    time.Now(),
		EntryFunding: fundingRate,
	}

	// Delta-neutral: place spot hedge (opposite direction)
	if s.cfg.DeltaNeutral {
		var spotSide execution.OrderSide
		if side == "SHORT" {
			spotSide = execution.OrderSideBuy // short perp → buy spot
		} else {
			spotSide = execution.OrderSideSell // long perp → sell spot
		}
		spotOrder, err := s.executor.ExecuteMarketOrder(sym, spotSide, order.FilledSize)
		if err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("funding arb: spot hedge failed, closing perp")
			// Rollback: close the perp leg
			var rollbackSide execution.OrderSide
			if side == "SHORT" {
				rollbackSide = execution.OrderSideBuy
			} else {
				rollbackSide = execution.OrderSideSell
			}
			s.executor.ExecuteMarketOrder(sym, rollbackSide, order.FilledSize)
			return
		}
		pos.SpotEntryPrice = spotOrder.FilledPrice
		pos.SpotSize = spotOrder.FilledSize
	}

	// Persist to DB
	if s.store != nil {
		dbPos := &data.ArbPosition{
			Symbol:         pos.Symbol,
			Side:           pos.Side,
			EntryPrice:     pos.EntryPrice,
			Size:           pos.Size,
			EntryTime:      pos.EntryTime,
			EntryFunding:   pos.EntryFunding,
			SpotEntryPrice: pos.SpotEntryPrice,
			SpotSize:       pos.SpotSize,
		}
		id, err := s.store.SavePosition(dbPos)
		if err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("failed to persist arb position")
		} else {
			pos.dbID = id
		}
	}

	s.positions[sym] = pos

	// Register with portfolio monitor
	if s.portfolioMonitor != nil {
		exposureSide := "NEUTRAL"
		if !s.cfg.DeltaNeutral {
			exposureSide = side
		}
		s.portfolioMonitor.RegisterEntry(sym, notional, "funding_arb", exposureSide)
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
		Bool("delta_neutral", s.cfg.DeltaNeutral).
		Float64("spot_price", pos.SpotEntryPrice).
		Msg("funding arb: opened position")
}

// managePosition checks if we should close an existing arb position.
func (s *Strategy) managePosition(sym string, pos *arbPosition, currentFunding, markPrice float64) {
	// Track estimated funding collection
	// (simplified: assumes we've been in since last check and received funding)
	fundingUpdated := false
	if pos.Side == "SHORT" && currentFunding > 0 {
		payment := currentFunding * pos.Size * markPrice
		pos.FundingCollected += payment
		pos.FundingPayments++
		fundingUpdated = true
	} else if pos.Side == "LONG" && currentFunding < 0 {
		payment := math.Abs(currentFunding) * pos.Size * markPrice
		pos.FundingCollected += payment
		pos.FundingPayments++
		fundingUpdated = true
	}

	// Persist funding collection update
	if fundingUpdated && s.store != nil && pos.dbID > 0 {
		if err := s.store.UpdatePosition(pos.dbID, pos.FundingCollected, pos.FundingPayments); err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("failed to update arb position in DB")
		}
	}

	// Exit conditions:
	// 1. Funding has normalized (below exit threshold)
	// 2. Funding has flipped (we'd be paying instead of collecting)
	// 3. Momentum reversal (if enabled)
	shouldClose := false
	reason := ""

	// Check max loss per position (directional risk protection)
	// Skip when delta-neutral — position is hedged, no directional exposure
	if s.cfg.MaxLossPct > 0 && pos.SpotSize == 0 {
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

	// Only check other exit conditions if not already closing due to max loss
	if !shouldClose {
		// Momentum exit: check if funding momentum has reversed
		if s.cfg.UseMomentum && s.cfg.MomentumExitEnable {
			avg24h := CalculateFundingAverage(s.store, sym, 24)
			if CheckMomentumExit(currentFunding, avg24h) {
				shouldClose = true
				reason = "momentum_reversal"
				log.Debug().
					Str("symbol", sym).
					Float64("current_funding", currentFunding).
					Float64("avg_24h", avg24h).
					Msg("funding arb: momentum reversal detected")
			}
		}
		
		// Static exit: funding normalized
		if !shouldClose {
			absFunding := math.Abs(currentFunding)
			if absFunding < s.cfg.ExitThreshold {
				shouldClose = true
				reason = "funding_normalized"
			}
		}
	}

	// Check if funding flipped against us (only if not already closing)
	if !shouldClose {
		if pos.Side == "SHORT" && currentFunding < 0 {
			shouldClose = true
			reason = "funding_flipped"
		}
		if pos.Side == "LONG" && currentFunding > 0 {
			shouldClose = true
			reason = "funding_flipped"
		}
	}

	if !shouldClose {
		return
	}

	// Close perp position
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
		log.Error().Err(err).Str("symbol", sym).Msg("funding arb: perp close failed")
		return
	}

	// Close spot hedge if delta-neutral
	if pos.SpotSize > 0 {
		var spotCloseSide execution.OrderSide
		if pos.Side == "SHORT" {
			spotCloseSide = execution.OrderSideSell // had bought spot → sell
		} else {
			spotCloseSide = execution.OrderSideBuy // had sold spot → buy back
		}
		_, err := s.executor.ExecuteMarketOrder(sym, spotCloseSide, pos.SpotSize)
		if err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("funding arb: spot hedge close failed")
		}
	}

	// Persist close to DB
	if s.store != nil && pos.dbID > 0 {
		if err := s.store.ClosePosition(pos.dbID, reason, markPrice, time.Now()); err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("failed to close arb position in DB")
		}
	}

	// Calculate PnL
	var perpPnL float64
	if pos.Side == "SHORT" {
		perpPnL = (pos.EntryPrice - markPrice) * pos.Size
	} else {
		perpPnL = (markPrice - pos.EntryPrice) * pos.Size
	}

	var spotPnL float64
	if pos.SpotSize > 0 {
		if pos.Side == "SHORT" {
			spotPnL = (markPrice - pos.SpotEntryPrice) * pos.SpotSize // bought spot, now selling
		} else {
			spotPnL = (pos.SpotEntryPrice - markPrice) * pos.SpotSize // sold spot, now buying back
		}
	}

	totalPnL := perpPnL + spotPnL + pos.FundingCollected

	log.Info().
		Str("symbol", sym).
		Str("side", pos.Side).
		Str("reason", reason).
		Float64("entry_price", pos.EntryPrice).
		Float64("exit_price", markPrice).
		Float64("perp_pnl", perpPnL).
		Float64("spot_pnl", spotPnL).
		Float64("funding_collected", pos.FundingCollected).
		Float64("total_pnl", totalPnL).
		Int("funding_payments", pos.FundingPayments).
		Bool("delta_neutral", pos.SpotSize > 0).
		Msg("funding arb: closed position")

	// Register exit with portfolio monitor
	if s.portfolioMonitor != nil {
		notional := pos.Size * markPrice
		s.portfolioMonitor.RegisterExit(sym, notional, "funding_arb")
	}

	delete(s.positions, sym)
}

// checkCrossExchangeEntry evaluates cross-exchange arbitrage opportunities
func (s *Strategy) checkCrossExchangeEntry(opp *exchange.CrossExchangeOpportunity) {
	// Check max positions
	if s.cfg.MaxPositions > 0 && len(s.positions) >= s.cfg.MaxPositions {
		return
	}

	// Check minimum spread
	if opp.SpreadBps < s.cfg.MinSpreadBps {
		return
	}

	// Position sizing based on lower funding rate exchange (more conservative)
	markPrice := (opp.HighFundingRate + opp.LowFundingRate) / 2 // Use average as proxy
	size := s.cfg.PositionSizeUSD / markPrice
	if size <= 0 {
		return
	}

	notional := size * markPrice

	// Check portfolio monitor
	if s.portfolioMonitor != nil {
		canEnter, reason := s.portfolioMonitor.CanEnter(opp.Symbol, notional, "funding_arb")
		if !canEnter {
			log.Warn().
				Str("symbol", opp.Symbol).
				Str("reason", reason).
				Float64("notional", notional).
				Msg("cross-exchange funding arb: entry blocked by portfolio monitor")
			return
		}
	}

	// Create cross-exchange position
	pos := &arbPosition{
		Symbol:          opp.Symbol,
		Side:            "CROSS_EXCHANGE",
		Size:            size,
		EntryTime:       time.Now(),
		IsCrossExchange: true,
		HighExchange:    opp.HighExchange,
		LowExchange:     opp.LowExchange,
		HighFundingRate: opp.HighFundingRate,
		LowFundingRate:  opp.LowFundingRate,
	}

	// TODO: Execute orders on both exchanges
	// This would require implementing order execution for Bybit/OKX clients
	log.Info().
		Str("symbol", opp.Symbol).
		Str("high_exchange", opp.HighExchange).
		Str("low_exchange", opp.LowExchange).
		Float64("spread_bps", opp.SpreadBps).
		Float64("annualized_return", opp.AnnualizedReturn).
		Msg("cross-exchange funding arb: opportunity identified (execution not implemented)")

	// For now, just log the opportunity without executing
	// In production, this would place SHORT order on high exchange and LONG order on low exchange

	s.positions[opp.Symbol] = pos

	// Register with portfolio monitor
	if s.portfolioMonitor != nil {
		s.portfolioMonitor.RegisterEntry(opp.Symbol, notional, "funding_arb", "NEUTRAL")
	}
}

// manageCrossExchangePosition manages an existing cross-exchange position
func (s *Strategy) manageCrossExchangePosition(symbol string, pos *arbPosition, opp *exchange.CrossExchangeOpportunity) {
	// Check if spread has narrowed below exit threshold
	if opp.SpreadBps < s.cfg.MinSpreadBps * 0.5 { // Exit at 50% of entry spread
		s.closeCrossExchangePosition(symbol, pos, "spread_narrowed")
		return
	}

	// Check if funding rates have flipped
	if opp.HighExchange != pos.HighExchange || opp.LowExchange != pos.LowExchange {
		s.closeCrossExchangePosition(symbol, pos, "funding_flipped")
		return
	}

	// Update funding collection estimate
	spreadDiff := opp.SpreadBps / 10000 // Convert bps to decimal
	estimatedPayment := spreadDiff * pos.Size * (opp.HighFundingRate + opp.LowFundingRate) / 2
	pos.FundingCollected += estimatedPayment
	pos.FundingPayments++

	log.Debug().
		Str("symbol", symbol).
		Float64("spread_bps", opp.SpreadBps).
		Float64("estimated_payment", estimatedPayment).
		Float64("total_collected", pos.FundingCollected).
		Msg("cross-exchange funding arb: position update")
}

// closeCrossExchangePosition closes a cross-exchange arbitrage position
func (s *Strategy) closeCrossExchangePosition(symbol string, pos *arbPosition, reason string) {
	// TODO: Execute closing orders on both exchanges
	log.Info().
		Str("symbol", symbol).
		Str("reason", reason).
		Str("high_exchange", pos.HighExchange).
		Str("low_exchange", pos.LowExchange).
		Float64("funding_collected", pos.FundingCollected).
		Int("funding_payments", pos.FundingPayments).
		Msg("cross-exchange funding arb: closing position (execution not implemented)")

	// Register exit with portfolio monitor
	if s.portfolioMonitor != nil {
		notional := pos.Size * (pos.HighFundingRate + pos.LowFundingRate) / 2 // Estimate
		s.portfolioMonitor.RegisterExit(symbol, notional, "funding_arb")
	}

	delete(s.positions, symbol)
}

func (s *Strategy) closeAllPositions() {
	s.mu.Lock()
	defer s.mu.Unlock()

	for sym, pos := range s.positions {
		// Close perp leg
		var orderSide execution.OrderSide
		if pos.Side == "SHORT" {
			orderSide = execution.OrderSideBuy
		} else {
			orderSide = execution.OrderSideSell
		}

		_, err := s.executor.ExecuteMarketOrder(sym, orderSide, pos.Size)
		if err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("funding arb: shutdown perp close failed")
		}

		// Close spot hedge
		if pos.SpotSize > 0 {
			var spotSide execution.OrderSide
			if pos.Side == "SHORT" {
				spotSide = execution.OrderSideSell
			} else {
				spotSide = execution.OrderSideBuy
			}
			_, err := s.executor.ExecuteMarketOrder(sym, spotSide, pos.SpotSize)
			if err != nil {
				log.Error().Err(err).Str("symbol", sym).Msg("funding arb: shutdown spot close failed")
			}
		}

		log.Info().Str("symbol", sym).Bool("had_spot_hedge", pos.SpotSize > 0).Msg("funding arb: closed position on shutdown")

		// Mark closed in DB
		if s.store != nil && pos.dbID > 0 {
			if err := s.store.ClosePosition(pos.dbID, "shutdown", 0, time.Now()); err != nil {
				log.Error().Err(err).Str("symbol", sym).Msg("failed to close arb position in DB on shutdown")
			}
		}
	}
	s.positions = make(map[string]*arbPosition)
}
