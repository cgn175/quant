package basistrade

import (
	"context"
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

// Strategy implements a perpetual basis (cash-and-carry) trade.
//
// When the annualized basis (perp premium over spot) exceeds a threshold,
// we enter delta-neutral: buy spot + short perp.
// When basis converges below exit threshold, we close both legs.
// Profit = basis captured + any funding collected.
type Strategy struct {
	cfg              config.BasisTradeConfig
	client           exchange.Client
	executor         execution.Executor
	execEngine       *execution.Engine
	store            *data.FundingStore
	symbols          []string
	portfolioMonitor *risk.PortfolioMonitor

	mu        sync.RWMutex
	positions map[string]*basisPosition
}

// basisPosition tracks an active basis trade.
type basisPosition struct {
	dbID           int64
	Symbol         string
	SpotEntryPrice float64
	SpotSize       float64
	PerpEntryPrice float64
	PerpSize       float64
	EntryBasis     float64 // annualized basis at entry
	EntryTime      time.Time
}

func NewStrategy(cfg config.BasisTradeConfig, client exchange.Client, executor execution.Executor, execEngine *execution.Engine, symbols []string, store *data.FundingStore, portfolioMonitor *risk.PortfolioMonitor) *Strategy {
	return &Strategy{
		cfg:              cfg,
		client:           client,
		executor:         executor,
		execEngine:       execEngine,
		store:            store,
		symbols:          symbols,
		portfolioMonitor: portfolioMonitor,
		positions:        make(map[string]*basisPosition),
	}
}

func (s *Strategy) Start(ctx context.Context) error {
	log.Info().
		Float64("min_basis_annualized", s.cfg.MinBasisAnnualized).
		Float64("exit_basis", s.cfg.ExitBasis).
		Int("max_positions", s.cfg.MaxPositions).
		Float64("position_size_usd", s.cfg.PositionSizeUSD).
		Msg("starting basis trade strategy")

	// Restore open positions from DB
	if s.store != nil {
		if err := s.restorePositions(); err != nil {
			log.Error().Err(err).Msg("failed to restore basis positions from DB")
		}
	}

	go s.runLoop(ctx)
	return nil
}

func (s *Strategy) restorePositions() error {
	positions, err := s.store.LoadOpenPositions()
	if err != nil {
		return err
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	for _, p := range positions {
		// Only restore positions that have both spot and perp (basis trade signature)
		if p.SpotSize > 0 && p.Size > 0 {
			s.positions[p.Symbol] = &basisPosition{
				dbID:           p.ID,
				Symbol:         p.Symbol,
				SpotEntryPrice: p.SpotEntryPrice,
				SpotSize:       p.SpotSize,
				PerpEntryPrice: p.EntryPrice,
				PerpSize:       p.Size,
				EntryBasis:     p.EntryFunding, // reusing EntryFunding to store basis
				EntryTime:      p.EntryTime,
			}
			log.Info().
				Str("symbol", p.Symbol).
				Float64("spot_price", p.SpotEntryPrice).
				Float64("perp_price", p.EntryPrice).
				Float64("size", p.Size).
				Msg("basis trade: restored position from DB")
		}
	}

	return nil
}

func (s *Strategy) runLoop(ctx context.Context) {
	scanInterval := time.Duration(s.cfg.ScanIntervalMs) * time.Millisecond
	if scanInterval <= 0 {
		scanInterval = 5 * time.Minute
	}

	ticker := time.NewTicker(scanInterval)
	defer ticker.Stop()

	// Initial scan
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

func (s *Strategy) scanAndManage() {
	s.mu.Lock()
	defer s.mu.Unlock()

	for _, sym := range s.symbols {
		// Fetch perp mark price (from funding rates endpoint)
		fundingInfo, err := s.client.FetchFundingRate(sym)
		if err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("basis trade: failed to fetch funding/mark price")
			continue
		}
		markPrice := fundingInfo.MarkPrice

		// Fetch spot price
		spotPrice, err := s.client.FetchSpotPrice(sym)
		if err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("basis trade: failed to fetch spot price")
			continue
		}

		// Calculate basis
		if spotPrice <= 0 {
			continue
		}
		basis := (markPrice - spotPrice) / spotPrice

		// Annualize: perpetuals have funding every 8h, basis compounds
		// Simplified: annualized = basis * (365 * 3) for 8h periods per year
		annualizedBasis := basis * 365 * 3

		pos, hasPos := s.positions[sym]

		if hasPos {
			s.managePosition(sym, pos, annualizedBasis, spotPrice, markPrice)
		} else {
			s.checkEntry(sym, annualizedBasis, spotPrice, markPrice)
		}
	}
}

func (s *Strategy) checkEntry(sym string, annualizedBasis, spotPrice, markPrice float64) {
	// Check max positions
	if s.cfg.MaxPositions > 0 && len(s.positions) >= s.cfg.MaxPositions {
		return
	}

	// Only enter on positive basis (contango): perp > spot
	if annualizedBasis < s.cfg.MinBasisAnnualized {
		return
	}

	// Position sizing
	size := s.cfg.PositionSizeUSD / spotPrice
	if size <= 0 {
		return
	}

	notional := size * spotPrice

	// Check portfolio monitor for cross-strategy limits
	if s.portfolioMonitor != nil {
		canEnter, reason := s.portfolioMonitor.CanEnter(sym, notional, "basis_trade")
		if !canEnter {
			log.Warn().
				Str("symbol", sym).
				Str("reason", reason).
				Float64("notional", notional).
				Msg("basis trade: entry blocked by portfolio monitor")
			return
		}
	}

	// Buy spot
	spotOrder, err := s.executor.ExecuteMarketOrder(sym, execution.OrderSideBuy, size)
	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("basis trade: spot buy failed")
		return
	}

	// Short perp
	perpOrder, err := s.executor.ExecuteMarketOrder(sym, execution.OrderSideSell, size)
	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("basis trade: perp short failed, rolling back spot")
		// Rollback: sell spot
		s.executor.ExecuteMarketOrder(sym, execution.OrderSideSell, spotOrder.FilledSize)
		return
	}

	pos := &basisPosition{
		Symbol:         sym,
		SpotEntryPrice: spotOrder.FilledPrice,
		SpotSize:       spotOrder.FilledSize,
		PerpEntryPrice: perpOrder.FilledPrice,
		PerpSize:       perpOrder.FilledSize,
		EntryBasis:     annualizedBasis,
		EntryTime:      time.Now(),
	}

	// Persist to DB
	if s.store != nil {
		dbPos := &data.ArbPosition{
			Symbol:         pos.Symbol,
			Side:           "SHORT", // perp side
			EntryPrice:     pos.PerpEntryPrice,
			Size:           pos.PerpSize,
			EntryTime:      pos.EntryTime,
			EntryFunding:   pos.EntryBasis, // reusing field for basis
			SpotEntryPrice: pos.SpotEntryPrice,
			SpotSize:       pos.SpotSize,
		}
		id, err := s.store.SavePosition(dbPos)
		if err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("failed to persist basis position")
		} else {
			pos.dbID = id
		}
	}

	s.positions[sym] = pos

	// Register with portfolio monitor (delta-neutral structure)
	if s.portfolioMonitor != nil {
		s.portfolioMonitor.RegisterEntry(sym, notional, "basis_trade", "NEUTRAL")
	}

	log.Info().
		Str("symbol", sym).
		Float64("spot_price", spotOrder.FilledPrice).
		Float64("perp_price", perpOrder.FilledPrice).
		Float64("size", spotOrder.FilledSize).
		Float64("annualized_basis_pct", annualizedBasis*100).
		Msg("basis trade: opened position")
}

func (s *Strategy) managePosition(sym string, pos *basisPosition, annualizedBasis, spotPrice, markPrice float64) {
	// Exit when basis has converged below threshold
	if annualizedBasis >= s.cfg.ExitBasis {
		return // basis still attractive, hold
	}

	// Close both legs
	// Sell spot
	_, err := s.executor.ExecuteMarketOrder(sym, execution.OrderSideSell, pos.SpotSize)
	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("basis trade: spot sell failed")
	}

	// Close short perp (buy to cover)
	_, err = s.execEngine.ClosePosition(
		sym,
		"SHORT",
		markPrice,
		pos.PerpSize,
		"basis_converged",
		strategy.SignalNone,
		"basis_trade",
		pos.PerpEntryPrice,
		pos.EntryTime,
	)
	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("basis trade: perp close failed")
	}

	// Persist close to DB
	if s.store != nil && pos.dbID > 0 {
		if err := s.store.ClosePosition(pos.dbID, "basis_converged", markPrice, time.Now()); err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("failed to close basis position in DB")
		}
	}

	// Calculate PnL
	spotPnL := (spotPrice - pos.SpotEntryPrice) * pos.SpotSize
	perpPnL := (pos.PerpEntryPrice - markPrice) * pos.PerpSize
	totalPnL := spotPnL + perpPnL

	log.Info().
		Str("symbol", sym).
		Float64("entry_basis_pct", pos.EntryBasis*100).
		Float64("exit_basis_pct", annualizedBasis*100).
		Float64("spot_pnl", spotPnL).
		Float64("perp_pnl", perpPnL).
		Float64("total_pnl", totalPnL).
		Msg("basis trade: closed position")

	// Register exit with portfolio monitor
	if s.portfolioMonitor != nil {
		notional := pos.SpotSize * spotPrice
		s.portfolioMonitor.RegisterExit(sym, notional, "basis_trade")
	}

	delete(s.positions, sym)
}

func (s *Strategy) closeAllPositions() {
	s.mu.Lock()
	defer s.mu.Unlock()

	for sym, pos := range s.positions {
		// Sell spot
		_, err := s.executor.ExecuteMarketOrder(sym, execution.OrderSideSell, pos.SpotSize)
		if err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("basis trade: shutdown spot close failed")
		}

		// Close short perp
		_, err = s.executor.ExecuteMarketOrder(sym, execution.OrderSideBuy, pos.PerpSize)
		if err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("basis trade: shutdown perp close failed")
		}

		log.Info().Str("symbol", sym).Msg("basis trade: closed position on shutdown")

		// Mark closed in DB
		if s.store != nil && pos.dbID > 0 {
			if err := s.store.ClosePosition(pos.dbID, "shutdown", 0, time.Now()); err != nil {
				log.Error().Err(err).Str("symbol", sym).Msg("failed to close basis position in DB on shutdown")
			}
		}
	}
	s.positions = make(map[string]*basisPosition)
}
