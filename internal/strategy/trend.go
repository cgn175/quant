// Package strategy — Plan D: Pure Trend Following strategy.
//
// No ML. No prediction. Mechanical trend-following rules with three layers:
//
//	Layer 1: Entry signals (Donchian breakout + EMA crossover confirmation)
//	Layer 2: Regime filters (ADX, volatility, funding rate)
//	Layer 3: Risk management (ATR-based stops, trailing Chandelier exit, partial exits)
package strategy

import (
	"context"
	"math"
	"sync"
	"time"

	"github.com/cgn175/quant-bot/internal/data"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/features"
	"github.com/cgn175/quant-bot/internal/metrics"
	"github.com/cgn175/quant-bot/internal/mlfilter"
	"github.com/cgn175/quant-bot/internal/sentiment"
	"github.com/rs/zerolog/log"
)

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

// TrendConfig holds all parameters for the trend-following strategy.
type TrendConfig struct {
	// Layer 1: Entry signal parameters
	DonchianPeriod int // 20 — breakout lookback
	EMAFast        int // 9
	EMASlow        int // 21
	EMAConfirmBars int // 5 — crossover must have happened within N bars
	EMATrend       int // 50 — trend direction filter
	VolumePeriod   int // 20 — volume confirmation lookback

	// Layer 2: Regime filter parameters
	ATRPeriod       int     // 14
	ATRStopMult     float64 // 3.0
	ADXPeriod       int     // 14
	ADXThreshold    float64 // 20.0 — minimum ADX for trend
	VolatilityLow   float64 // 0.5 — min ATR ratio
	VolatilityHigh  float64 // 2.5 — max ATR ratio
	FundingExtreme  float64 // 0.0005 — block trades
	FundingElevated float64 // 0.0003 — reduce size

	// Layer 3: Risk management
	RiskPerTrade          float64 // 0.01 — 1% of equity per trade
	MaxLeverage           float64 // 2.0
	ChandelierLookback    int     // 10 — trailing stop lookback
	DailyLossCapPct       float64 // 0.03 — 3% of equity
	MaxOpenPositions      int     // 4
	MaxCorrelatedSame     int     // 2 — max same-direction on correlated pairs
	MaxPositionsPerSector int     // 1 — max positions in same sector (Patch 3)

	// Partial exit parameters
	PartialExitEnabled bool
	FirstTargetR       float64 // 3.0 — first partial at 3R
	FirstExitPct       float64 // 0.25 — close 25%
	SecondTargetR      float64 // 6.0 — second partial at 6R
	SecondExitPct      float64 // 0.25 — close 25%

	// ML filter parameters
	MLFilterEnabled bool
	MLThreshold     float64
	FallbackToADX   bool
	FailOpen        bool

	// Regime Classifier (Traffic Light) parameters
	RegimeFilterEnabled bool
	RegimeThreshold     float64
	RegimeFallbackToADX bool
	RegimeFailOpen      bool

	// Per-symbol regime model version ("v1" or "v2")
	RegimeSymbolVersions map[string]string

	// Ensemble (regime + vol) parameters
	EnsembleEnabled    bool
	EnsembleMaxStopPct float64
	EnsembleSymbols    map[string]bool // set of symbols to apply ensemble to

	// Directional regime models (LONG-only / SHORT-only)
	DirectionalRegimeEnabled bool
	DirectionalRegimeSymbols map[string]bool // symbols that use directional models

	// HMM regime detection (probabilistic states)
	UseHMM          bool    // Use HMM instead of RandomForest (default: false)
	HMMTrendingProb float64 // Min probability for "trending" state (default: 0.6)

	// Dynamic Stop-Loss (Volatility Reader) parameters
	DynamicStopEnabled bool
	DynamicStopK       float64 // multiplier for predicted range → stop %
	DynamicStopMinPct  float64 // floor (e.g., 0.01 = 1%)
	DynamicStopMaxPct  float64 // ceiling (e.g., 0.04 = 4%)

	// Portfolio circuit breaker
	MaxDrawdownPct     float64 // 0.15 — halt all if equity drops 15% from peak
	DrawdownHaltHours  int     // 48 — hours to halt after drawdown breach
	MaxLossPerPosition float64 // 0.05 — hard stop at 5% of equity per position
	ExtremeVolATRRatio float64 // 3.0 — halt entries when BTC ATR(14)/ATR(50) > this

	// Time-based exit for dead positions
	TimeStopBars int     // 10 — exit if position hasn't moved 0.5R after N bars
	TimeStopMinR float64 // 0.5 — minimum R required to avoid time stop

	// Open Interest regime filter
	OIFilterEnabled      bool
	OIFilterZScoreThresh float64 // z-score threshold for blocking entry (e.g., 2.0)
	OIFilterLookback     int     // number of OI samples for z-score calculation (e.g., 30)

	// Cross-sectional momentum filter
	MomentumFilter MomentumFilterConfig
}

// MomentumFilterConfig holds parameters for cross-sectional momentum filtering
type MomentumFilterConfig struct {
	Enabled      bool    // Enable momentum filter
	LookbackDays int     // Lookback period in days (default: 21 = 3 weeks)
	TopPct       float64 // Trade only top N% by momentum (default: 0.5 = 50%)
}


// SectorMap classifies trading symbols by sector for correlation management (Patch 3).
var SectorMap = map[string]string{
	"BTCUSDT":  "BTC",
	"ETHUSDT":  "L1",
	"SOLUSDT":  "L1",
	"AVAXUSDT": "L1",
	"ADAUSDT":  "L1",
	"FETUSDT":  "AI",
	"RNDRUSDT": "AI",
	"WLDUSDT":  "AI",
	"DOGEUSDT": "MEME",
	"SHIBUSDT": "MEME",
	"PEPEUSDT": "MEME",
	"BNBUSDT":  "EXCHANGE",
}

// getSector returns the sector for a symbol, defaulting to "OTHER".
func getSector(symbol string) string {
	if sector, ok := SectorMap[symbol]; ok {
		return sector
	}
	return "OTHER"
}

// DefaultTrendConfig returns the default trend-following configuration
// matching the Plan D specification.
func DefaultTrendConfig() TrendConfig {
	return TrendConfig{
		DonchianPeriod:        20,
		EMAFast:               9,
		EMASlow:               21,
		EMAConfirmBars:        5,
		EMATrend:              50,
		VolumePeriod:          20,
		ATRPeriod:             14,
		ATRStopMult:           2.5,
		ADXPeriod:             14,
		ADXThreshold:          20.0,
		VolatilityLow:         0.5,
		VolatilityHigh:        2.5,
		FundingExtreme:        0.0005,
		FundingElevated:       0.0003,
		RiskPerTrade:          0.01,
		MaxLeverage:           2.0,
		ChandelierLookback:    10,
		DailyLossCapPct:       0.03,
		MaxOpenPositions:      4,
		MaxCorrelatedSame:     2,
		MaxPositionsPerSector: 1,
		PartialExitEnabled:    true,
		FirstTargetR:          3.0,
		FirstExitPct:          0.10,
		SecondTargetR:         6.0,
		SecondExitPct:         0.10,
		MaxDrawdownPct:        0.15,
		DrawdownHaltHours:     48,
		MaxLossPerPosition:    0.05,
		ExtremeVolATRRatio:    3.0,
		TimeStopBars:          10,
		TimeStopMinR:          0.5,
	}
}

// MinCandles returns the minimum number of candles needed for all indicators
// to produce valid values.
func (c TrendConfig) MinCandles() int {
	// ADX needs 2*period+1, EMA trend needs EMATrend, Donchian needs period+1
	// ATR volatility filter uses ATR(50) for slow, so we need at least 51 candles
	min := 2*c.ADXPeriod + 1
	if c.EMATrend+1 > min {
		min = c.EMATrend + 1
	}
	if c.DonchianPeriod+1 > min {
		min = c.DonchianPeriod + 1
	}
	// Volatility filter uses ATR(50) for slow component
	if 51 > min {
		min = 51
	}
	return min + 5 // safety margin
}

// ---------------------------------------------------------------------------
// Position tracking (internal to TrendStrategy)
// ---------------------------------------------------------------------------

// TrendPosition tracks an open position with its trailing stop state.
type TrendPosition struct {
	Symbol         string
	Side           string // "LONG" or "SHORT"
	EntryPrice     float64
	EntryTime      time.Time
	Size           float64 // current remaining size
	OriginalSize   float64 // initial size (before partial exits)
	InitialStop    float64
	TrailingStop   float64 // current trailing stop (only tightens)
	InitialRisk    float64 // entry - initial_stop (absolute value, per unit)
	PartialStage   int     // 0=none, 1=first partial done, 2=second partial done
	SizeMultiplier float64 // 1.0 or 0.5 (from funding filter)
	Pending        bool    // true if this is a reservation (order not yet filled)
	BarsSinceEntry int     // counts closed bars since entry
}

// CurrentR returns the current profit in R-multiples.
func (p *TrendPosition) CurrentR(currentPrice float64) float64 {
	if p.InitialRisk <= 0 {
		return 0
	}
	var pnlPerUnit float64
	if p.Side == "LONG" {
		pnlPerUnit = currentPrice - p.EntryPrice
	} else {
		pnlPerUnit = p.EntryPrice - currentPrice
	}
	return pnlPerUnit / p.InitialRisk
}

// ---------------------------------------------------------------------------
// Signal types for trend strategy
// ---------------------------------------------------------------------------

// ExitSignal represents a trailing stop or full exit.
type ExitSignal struct {
	Symbol string
	Reason string  // "trailing_stop", "daily_loss_cap"
	Price  float64 // current price that triggered exit
}

// PartialExitSignal represents a partial position close at an R-target.
type PartialExitSignal struct {
	Symbol     string
	ExitPct    float64 // fraction of current size to close (0.25)
	ExitSize   float64 // absolute size to close
	Reason     string  // "partial_3r", "partial_6r"
	MoveStopBE bool    // move stop to breakeven after first partial
	NewStop    float64 // new stop level (if MoveStopBE)
}

// ---------------------------------------------------------------------------
// TrendStrategy
// ---------------------------------------------------------------------------

// TrendStrategy implements the Plan D pure trend-following system.
type TrendStrategy struct {
	config          TrendConfig
	mlClient        *mlfilter.Client
	sentimentClient *sentiment.Client
	prom            *metrics.Metrics

	mu        sync.Mutex
	positions map[string]*TrendPosition

	// Daily loss tracking
	dailyPnL       float64
	dailyResetDate time.Time
	dailyHalted    bool

	// Portfolio drawdown circuit breaker
	peakEquity        float64
	drawdownHaltUntil time.Time

	// OI filter history (per symbol)
	oiHistory map[string][]float64
}

// TrendStrategyOption configures optional dependencies for TrendStrategy.
type TrendStrategyOption func(*TrendStrategy)

// WithMLClient sets the ML filter client.
func WithMLClient(c *mlfilter.Client) TrendStrategyOption {
	return func(ts *TrendStrategy) { ts.mlClient = c }
}

// WithMetrics sets the Prometheus metrics collector.
func WithMetrics(m *metrics.Metrics) TrendStrategyOption {
	return func(ts *TrendStrategy) { ts.prom = m }
}

// WithSentimentClient sets the sentiment client.
func WithSentimentClient(s *sentiment.Client) TrendStrategyOption {
	return func(ts *TrendStrategy) { ts.sentimentClient = s }
}

// NewTrendStrategy creates a new trend-following strategy with the given config.
// An optional *mlfilter.Client can be passed to enable ML-based filtering;
// pass nil to use the legacy ADX filter.
func NewTrendStrategy(config TrendConfig, mlClient ...*mlfilter.Client) *TrendStrategy {
	ts := &TrendStrategy{
		config:         config,
		positions:      make(map[string]*TrendPosition),
		dailyResetDate: time.Now().UTC().Truncate(24 * time.Hour),
		oiHistory:      make(map[string][]float64),
	}
	if len(mlClient) > 0 {
		ts.mlClient = mlClient[0]
	}
	return ts
}

// NewTrendStrategyWithOpts creates a TrendStrategy with functional options.
func NewTrendStrategyWithOpts(config TrendConfig, opts ...TrendStrategyOption) *TrendStrategy {
	ts := &TrendStrategy{
		config:         config,
		positions:      make(map[string]*TrendPosition),
		dailyResetDate: time.Now().UTC().Truncate(24 * time.Hour),
		oiHistory:      make(map[string][]float64),
	}
	for _, opt := range opts {
		opt(ts)
	}
	return ts
}

// GetPosition returns a copy of the trend position for a symbol, or nil.
func (ts *TrendStrategy) GetPosition(symbol string) *TrendPosition {
	ts.mu.Lock()
	defer ts.mu.Unlock()
	pos, exists := ts.positions[symbol]
	if !exists {
		return nil
	}
	cp := *pos
	return &cp
}

// HasPosition returns true if a position exists for the symbol.
func (ts *TrendStrategy) HasPosition(symbol string) bool {
	ts.mu.Lock()
	defer ts.mu.Unlock()
	_, exists := ts.positions[symbol]
	return exists
}

// OpenPositionCount returns the number of open positions.
func (ts *TrendStrategy) OpenPositionCount() int {
	ts.mu.Lock()
	defer ts.mu.Unlock()
	return len(ts.positions)
}

// RegisterPosition records a new position after order execution succeeds.
func (ts *TrendStrategy) RegisterPosition(symbol, side string, entryPrice, size, initialStop, sizeMultiplier float64) {
	ts.mu.Lock()
	defer ts.mu.Unlock()

	var initialRisk float64
	if side == "LONG" {
		initialRisk = entryPrice - initialStop
	} else {
		initialRisk = initialStop - entryPrice
	}

	ts.positions[symbol] = &TrendPosition{
		Symbol:         symbol,
		Side:           side,
		EntryPrice:     entryPrice,
		EntryTime:      time.Now(),
		Size:           size,
		OriginalSize:   size,
		InitialStop:    initialStop,
		TrailingStop:   initialStop,
		InitialRisk:    initialRisk,
		PartialStage:   0,
		SizeMultiplier: sizeMultiplier,
	}
}

// RemovePosition removes a position after it's fully closed.
func (ts *TrendStrategy) RemovePosition(symbol string) {
	ts.mu.Lock()
	defer ts.mu.Unlock()
	delete(ts.positions, symbol)
}

// RecordPnL records realized PnL for daily loss tracking.
func (ts *TrendStrategy) RecordPnL(pnl float64) {
	ts.mu.Lock()
	defer ts.mu.Unlock()
	ts.checkDailyReset()
	ts.dailyPnL += pnl
}

// IsDailyHalted returns true if the daily loss cap has been hit.
func (ts *TrendStrategy) IsDailyHalted() bool {
	ts.mu.Lock()
	defer ts.mu.Unlock()
	ts.checkDailyReset()
	return ts.dailyHalted
}

func (ts *TrendStrategy) checkDailyReset() {
	today := time.Now().UTC().Truncate(24 * time.Hour)
	if today.After(ts.dailyResetDate) {
		ts.dailyPnL = 0
		ts.dailyHalted = false
		ts.dailyResetDate = today
	}
}

// CanEnter checks all TrendStrategy-level gating conditions under a single
// lock to avoid TOCTOU races between per-symbol goroutines. Returns (true, "")
// if entry is allowed, or (false, reason) if blocked.
//
// DEPRECATED: Use TryReserveEntry instead, which atomically checks and reserves.
func (ts *TrendStrategy) CanEnter(symbol string, direction string) (bool, string) {
	ts.mu.Lock()
	defer ts.mu.Unlock()

	return ts.canEnterLocked(symbol, direction)
}

// canEnterLocked is the internal implementation of CanEnter.
// Caller must hold ts.mu.
func (ts *TrendStrategy) canEnterLocked(symbol string, direction string) (bool, string) {
	// Already have a position (or reservation) for this symbol?
	if _, exists := ts.positions[symbol]; exists {
		return false, "position_exists"
	}

	// Max positions reached? (includes pending reservations)
	if len(ts.positions) >= ts.config.MaxOpenPositions {
		return false, "max_positions"
	}

	// Daily loss cap?
	ts.checkDailyReset()
	if ts.dailyHalted {
		return false, "daily_halted"
	}

	// Portfolio drawdown circuit breaker
	if time.Now().Before(ts.drawdownHaltUntil) {
		return false, "drawdown_halted"
	}

	// Sector limit check (Patch 3: Correlation Guard)
	if ts.config.MaxPositionsPerSector > 0 {
		newSector := getSector(symbol)
		sectorCount := 0
		for _, pos := range ts.positions {
			if getSector(pos.Symbol) == newSector {
				sectorCount++
			}
		}
		if sectorCount >= ts.config.MaxPositionsPerSector {
			return false, "sector_limit"
		}
	}

	// Correlation limit: max same-direction positions (includes pending)
	sameCount := 0
	for _, pos := range ts.positions {
		if pos.Side == direction {
			sameCount++
		}
	}
	if sameCount >= ts.config.MaxCorrelatedSame {
		return false, "correlated_limit"
	}

	return true, ""
}

// TryReserveEntry atomically checks if entry is allowed and creates a pending
// reservation. This prevents TOCTOU races between per-symbol goroutines.
// Returns (true, "") if reservation succeeded, or (false, reason) if blocked.
// On success, caller MUST call either ConfirmReservation (on order fill) or
// CancelReservation (on order failure/timeout).
func (ts *TrendStrategy) TryReserveEntry(symbol string, direction string) (bool, string) {
	ts.mu.Lock()
	defer ts.mu.Unlock()

	ok, reason := ts.canEnterLocked(symbol, direction)
	if !ok {
		return false, reason
	}

	// Create pending reservation
	ts.positions[symbol] = &TrendPosition{
		Symbol:    symbol,
		Side:      direction,
		EntryTime: time.Now(),
		Pending:   true,
	}

	log.Debug().Str("symbol", symbol).Str("side", direction).Msg("entry reservation created")
	return true, ""
}

// ConfirmReservation converts a pending reservation into a real position
// after the order is filled. Call this instead of RegisterPosition when
// using the reservation pattern.
func (ts *TrendStrategy) ConfirmReservation(symbol, side string, entryPrice, size, initialStop, sizeMultiplier float64) {
	ts.mu.Lock()
	defer ts.mu.Unlock()

	var initialRisk float64
	if side == "LONG" {
		initialRisk = entryPrice - initialStop
	} else {
		initialRisk = initialStop - entryPrice
	}

	ts.positions[symbol] = &TrendPosition{
		Symbol:         symbol,
		Side:           side,
		EntryPrice:     entryPrice,
		EntryTime:      time.Now(),
		Size:           size,
		OriginalSize:   size,
		InitialStop:    initialStop,
		TrailingStop:   initialStop,
		InitialRisk:    initialRisk,
		PartialStage:   0,
		SizeMultiplier: sizeMultiplier,
		Pending:        false,
	}

	log.Debug().Str("symbol", symbol).Str("side", side).Float64("price", entryPrice).Msg("reservation confirmed")
}

// CancelReservation removes a pending reservation (e.g., on order failure).
func (ts *TrendStrategy) CancelReservation(symbol string) {
	ts.mu.Lock()
	defer ts.mu.Unlock()

	pos, exists := ts.positions[symbol]
	if exists && pos.Pending {
		delete(ts.positions, symbol)
		log.Debug().Str("symbol", symbol).Msg("entry reservation cancelled")
	}
}

// ---------------------------------------------------------------------------
// OnBar — Main entry signal generation (Layer 1 + Layer 2)
// ---------------------------------------------------------------------------

// OnBar evaluates whether a new entry signal should be generated for the
// given symbol based on the latest candles. Returns nil if no signal.
//
// Parameters:
//   - symbol: trading pair (e.g., "BTCUSDT")
//   - candles: time-sorted candles (oldest first), must have at least MinCandles()
//   - fundingCache: funding rate cache (may be nil)
//   - equity: current account equity (for position sizing)
func (ts *TrendStrategy) OnBar(
	symbol string,
	candles []exchange.Candle,
	fundingCache *data.FundingCache,
	equity float64,
) *Signal {
	cfg := ts.config
	n := len(candles)

	if n < cfg.MinCandles() {
		return nil
	}

	last := candles[n-1]
	idx := n - 1 // index of the latest bar

	// ---------------------------------------------------------------
	// Layer 1: Entry signals
	// ---------------------------------------------------------------

	// 1a. Donchian breakout (shifted — excludes current bar)
	dcUpper := features.DonchianUpper(candles, cfg.DonchianPeriod)
	dcLower := features.DonchianLower(candles, cfg.DonchianPeriod)
	if dcUpper == nil || dcLower == nil {
		return nil
	}

	donchianLong := last.Close > dcUpper[idx] && dcUpper[idx] > 0
	donchianShort := last.Close < dcLower[idx] && dcLower[idx] > 0

	if !donchianLong && !donchianShort {
		return nil // no breakout
	}

	// 1b. EMA trend filter (close vs EMA(50))
	emaTrend := features.EMA(candles, cfg.EMATrend)
	if emaTrend == nil {
		return nil
	}
	trendLong := last.Close > emaTrend[idx]
	trendShort := last.Close < emaTrend[idx]

	// Combined Layer 1 signal
	longSignal := donchianLong && trendLong
	shortSignal := donchianShort && trendShort

	if !longSignal && !shortSignal {
		return nil
	}

	// Single atomic check for all strategy-level gating conditions
	// (position exists, max positions, daily halt, correlation limit).
	direction := "LONG"
	if shortSignal {
		direction = "SHORT"
	}
	if ok, reason := ts.CanEnter(symbol, direction); !ok {
		log.Debug().Str("symbol", symbol).Str("reason", reason).Msg("entry blocked")
		return nil
	}

	// ---------------------------------------------------------------
	// Cross-sectional momentum filter
	// ---------------------------------------------------------------
	// TODO: Implement momentum filter - requires multi-symbol candle access
	// For now, momentum filter is disabled in this integration
	// Will be enabled in next commit with proper data access

	// ---------------------------------------------------------------
	// Pre-compute indicators for Layer 2 (optimization: compute once, use many)
	// ---------------------------------------------------------------
	// Compute ADX once - used in multiple regime filter branches
	adxVals := features.ADX(candles, cfg.ADXPeriod)
	// Compute ATR once - used for volatility filter and stop calculation
	atrFast := features.ATR(candles, cfg.ATRPeriod)
	atrSlow := features.ATR(candles, 50)
	if adxVals == nil || atrFast == nil || atrSlow == nil {
		return nil
	}

	// Pre-compute volatility features ONCE if either ensemble or dynamic stop is enabled
	// (optimization: compute here so it can be reused by both regime filter ensemble check AND dynamic stop)
	var volFeatures map[string]float64
	if (cfg.EnsembleEnabled && cfg.EnsembleSymbols[symbol]) || (cfg.DynamicStopEnabled && ts.mlClient != nil && ts.mlClient.IsEnabled()) {
		volFeatures = BuildVolatilityFeatures(candles, idx)
	}

	// ---------------------------------------------------------------
	// Layer 2: Regime filters
	// ---------------------------------------------------------------

	// 2a. Regime filter — Regime Classifier OR legacy ML OR legacy ADX
	if cfg.RegimeFilterEnabled && ts.mlClient != nil && ts.mlClient.IsEnabled() {
		// --- Regime Classifier (Traffic Light) ---
		// Fetch sentiment if available
		var sent *sentiment.SentimentData
		if ts.sentimentClient != nil {
			sent = ts.sentimentClient.Get(symbol)
			// Update sentiment metrics
			if ts.prom != nil && sent != nil {
				ts.prom.SentimentScore.WithLabelValues(symbol).Set(sent.Score1h)
				ts.prom.Sentiment1h.WithLabelValues(symbol).Set(sent.Score1h)
				ts.prom.Sentiment24h.WithLabelValues(symbol).Set(sent.Score24h)
				ts.prom.SentimentVelocity.WithLabelValues(symbol).Set(sent.Velocity)
				ts.prom.MentionsZScore.WithLabelValues(symbol).Set(sent.MentionsZScore)
			}
		}

		// Pick v1 or v2 features based on per-symbol config
		var regimeFeatures map[string]float64
		if ver, ok := cfg.RegimeSymbolVersions[symbol]; ok && ver == "v2" {
			regimeFeatures = BuildRegimeV2Features(candles, fundingCache, symbol, idx, sent)
		} else {
			regimeFeatures = BuildRegimeFeatures(candles, fundingCache, symbol, idx, sent)
		}
		mlStart := time.Now()
		// Use HMM if enabled, otherwise use RandomForest
		var probSafe float64
		var err error
		
		if cfg.UseHMM {
			// HMM regime detection (probabilistic states)
			hmmFeatures := map[string]float64{
				"returns":      regimeFeatures["returns_20"],
				"volatility":   regimeFeatures["volatility_20"],
				"volume_ratio": regimeFeatures["volume_ratio_20"],
			}
			
			resp, hmmErr := ts.mlClient.PredictRegimeHMM(context.Background(), symbol, hmmFeatures)
			if hmmErr != nil {
				err = hmmErr
			} else {
				// Check if in "trending" state with sufficient probability
				trendingProb := cfg.HMMTrendingProb
				if trendingProb <= 0 {
					trendingProb = 0.6 // default
				}
				
				// Find trending state (label == "trending")
				isTrending := false
				if resp.Label == "trending" {
					// Get probability of current state
					if resp.State >= 0 && resp.State < len(resp.Probabilities) {
						stateProb := resp.Probabilities[resp.State]
						isTrending = stateProb >= trendingProb
					}
				}
				
				// Convert to probSafe (1.0 if trending, 0.0 otherwise)
				if isTrending {
					probSafe = 1.0
				} else {
					probSafe = 0.0
				}
				
				log.Debug().
					Str("symbol", symbol).
					Int("state", resp.State).
					Str("label", resp.Label).
					Interface("probs", resp.Probabilities).
					Bool("is_trending", isTrending).
					Msg("HMM regime detection")
			}
		} else if cfg.DirectionalRegimeEnabled && cfg.DirectionalRegimeSymbols[symbol] {
			probSafe, err = ts.mlClient.PredictRegimeDirectional(context.Background(), symbol, direction, regimeFeatures)
		} else {
			probSafe, err = ts.mlClient.PredictRegime(context.Background(), symbol, regimeFeatures)
		}
		
		if ts.prom != nil {
			ts.prom.MLFilterLatency.Observe(time.Since(mlStart).Seconds())
		}
		if err != nil {
			log.Warn().Err(err).Str("symbol", symbol).Msg("Regime filter error")
			if ts.prom != nil {
				ts.prom.MLFilterErrorsTotal.Inc()
			}
			if cfg.RegimeFallbackToADX {
				if ts.prom != nil {
					ts.prom.MLFilterFallbackTotal.Inc()
				}
				// Use cached ADX instead of recomputing
				if adxVals[idx] < cfg.ADXThreshold {
					if ts.prom != nil {
						ts.prom.ADXFilterBlockedTotal.WithLabelValues(symbol).Inc()
					}
					return nil
				}
			} else if !cfg.RegimeFailOpen {
				return nil
			}
		} else {
			if ts.prom != nil {
				ts.prom.MLFilterProb.WithLabelValues(symbol).Set(probSafe)
			}
			if probSafe < cfg.RegimeThreshold {
				log.Debug().Str("symbol", symbol).Float64("prob_safe", probSafe).Float64("threshold", cfg.RegimeThreshold).Msg("Regime filter blocked signal (DANGER_ZONE)")
				if ts.prom != nil {
					ts.prom.MLFilterBlockedTotal.WithLabelValues(symbol).Inc()
				}
				return nil
			}
			log.Debug().Str("symbol", symbol).Float64("prob_safe", probSafe).Msg("Regime filter passed (SAFE_TO_TRADE)")

			// Ensemble filter: require vol-predicted stop ≤ threshold
			// Use pre-computed volFeatures (optimization: computed once at top of function)
			if cfg.EnsembleEnabled && cfg.EnsembleSymbols[symbol] && ts.mlClient != nil && volFeatures != nil {
				predRangePct, err := ts.mlClient.PredictVolatility(context.Background(), symbol, volFeatures)
				if err != nil {
					log.Warn().Err(err).Str("symbol", symbol).Msg("Ensemble vol prediction error, skipping ensemble check")
				} else {
					stopPct := cfg.DynamicStopK * predRangePct
					if stopPct > cfg.EnsembleMaxStopPct {
						log.Debug().Str("symbol", symbol).Float64("stop_pct", stopPct).Float64("max", cfg.EnsembleMaxStopPct).Msg("Ensemble filter blocked signal (vol too high)")
						if ts.prom != nil {
							ts.prom.MLFilterBlockedTotal.WithLabelValues(symbol).Inc()
						}
						return nil
					}
					log.Debug().Str("symbol", symbol).Float64("stop_pct", stopPct).Msg("Ensemble filter passed")
				}
			}
		}
	} else if ts.mlClient != nil && ts.mlClient.IsEnabled() {
		// Fetch sentiment if available
		var sent *sentiment.SentimentData
		if ts.sentimentClient != nil {
			sent = ts.sentimentClient.Get(symbol)
			// Update sentiment metrics
			if ts.prom != nil && sent != nil {
				ts.prom.SentimentScore.WithLabelValues(symbol).Set(sent.Score1h)
				ts.prom.Sentiment1h.WithLabelValues(symbol).Set(sent.Score1h)
				ts.prom.Sentiment24h.WithLabelValues(symbol).Set(sent.Score24h)
				ts.prom.SentimentVelocity.WithLabelValues(symbol).Set(sent.Velocity)
				ts.prom.MentionsZScore.WithLabelValues(symbol).Set(sent.MentionsZScore)
			}
		}
		mlFeatures := BuildMLFeatures(candles, fundingCache, symbol, idx, cfg, sent)
		mlStart := time.Now()
		prob, err := ts.mlClient.Predict(context.Background(), symbol, mlFeatures)
		if ts.prom != nil {
			ts.prom.MLFilterLatency.Observe(time.Since(mlStart).Seconds())
		}
		if err != nil {
			log.Warn().Err(err).Str("symbol", symbol).Msg("ML filter error")
			if ts.prom != nil {
				ts.prom.MLFilterErrorsTotal.Inc()
			}
			if cfg.FallbackToADX {
				if ts.prom != nil {
					ts.prom.MLFilterFallbackTotal.Inc()
				}
				// Use cached ADX instead of recomputing
				if adxVals[idx] < cfg.ADXThreshold {
					if ts.prom != nil {
						ts.prom.ADXFilterBlockedTotal.WithLabelValues(symbol).Inc()
					}
					return nil
				}
			} else if !cfg.FailOpen {
				return nil
			}
		} else {
			if ts.prom != nil {
				ts.prom.MLFilterProb.WithLabelValues(symbol).Set(prob)
			}
			if prob < cfg.MLThreshold {
				log.Debug().Str("symbol", symbol).Float64("prob", prob).Float64("threshold", cfg.MLThreshold).Msg("ML filter blocked signal")
				if ts.prom != nil {
					ts.prom.MLFilterBlockedTotal.WithLabelValues(symbol).Inc()
				}
				return nil
			}
		}
	} else {
		// Use cached ADX instead of recomputing
		if adxVals[idx] < cfg.ADXThreshold {
			log.Debug().Str("symbol", symbol).Float64("adx", safeIdx(adxVals, idx)).Msg("ADX filter blocked signal")
			if ts.prom != nil {
				ts.prom.ADXFilterBlockedTotal.WithLabelValues(symbol).Inc()
			}
			return nil
		}
	}

	// 2b. Volatility filter — ATR(14) / ATR(50) in normal range (use cached values)
	if atrSlow[idx] > 0 {
		atrRatio := atrFast[idx] / atrSlow[idx]
		if atrRatio < cfg.VolatilityLow || atrRatio > cfg.VolatilityHigh {
			log.Debug().Str("symbol", symbol).Float64("atr_ratio", atrRatio).Msg("volatility filter blocked signal")
			return nil
		}
	}

	// 2c. Funding rate filter
	sizeMultiplier := 1.0
	isFundingElevated := false
	if fundingCache != nil {
		if longSignal && fundingCache.IsLongCrowded(symbol, cfg.FundingExtreme) {
			log.Debug().Str("symbol", symbol).Msg("funding filter blocked LONG (extreme)")
			return nil
		}
		if shortSignal && fundingCache.IsShortCrowded(symbol, cfg.FundingExtreme) {
			log.Debug().Str("symbol", symbol).Msg("funding filter blocked SHORT (extreme)")
			return nil
		}
		sizeMultiplier = fundingCache.SizeMultiplier(symbol, cfg.FundingElevated)
		isFundingElevated = sizeMultiplier < 1.0
	}

	// 2d. Open Interest regime filter
	// Skip entry when OI z-score is extreme AND funding is elevated
	if cfg.OIFilterEnabled && isFundingElevated {
		oiZScore := ts.getOIZScore(symbol)
		if oiZScore > cfg.OIFilterZScoreThresh {
			log.Debug().
				Str("symbol", symbol).
				Float64("oi_zscore", oiZScore).
				Float64("threshold", cfg.OIFilterZScoreThresh).
				Msg("OI filter blocked entry (extreme OI + elevated funding)")
			return nil
		}
	}

	// ---------------------------------------------------------------
	// Build signal
	// ---------------------------------------------------------------
	atrVal := atrFast[idx]
	stopDistance := cfg.ATRStopMult * atrVal

	// Use pre-computed volFeatures for dynamic stop (optimization: computed once at top of function)
	// Note: volFeatures already computed if DynamicStopEnabled (moved earlier in function)

	// 2d. Dynamic Stop-Loss — use ML volatility prediction if enabled
	if cfg.DynamicStopEnabled && ts.mlClient != nil && ts.mlClient.IsEnabled() {
		// Use cached volFeatures instead of building again
		predRangePct, err := ts.mlClient.PredictVolatility(context.Background(), symbol, volFeatures)
		if err != nil {
			log.Warn().Err(err).Str("symbol", symbol).Msg("Dynamic stop prediction error, falling back to ATR")
			// fallback: use ATR-based stop (already computed above)
		} else {
			// Compute dynamic stop: stop_pct = clamp(k * predicted_range, min, max)
			stopPct := cfg.DynamicStopK * predRangePct
			if stopPct < cfg.DynamicStopMinPct {
				stopPct = cfg.DynamicStopMinPct
			}
			if stopPct > cfg.DynamicStopMaxPct {
				stopPct = cfg.DynamicStopMaxPct
			}
			stopDistance = last.Close * stopPct
			log.Debug().
				Str("symbol", symbol).
				Float64("pred_range_pct", predRangePct).
				Float64("stop_pct", stopPct).
				Float64("stop_distance", stopDistance).
				Float64("atr_stop_distance", cfg.ATRStopMult*atrVal).
				Msg("Dynamic stop-loss applied")
		}
	}

	var sigType SignalType
	var stopLoss float64

	if longSignal {
		sigType = SignalLong
		stopLoss = last.Close - stopDistance
	} else {
		sigType = SignalShort
		stopLoss = last.Close + stopDistance
	}

	signal := &Signal{
		Symbol:     symbol,
		Type:       sigType,
		Timestamp:  last.CloseTime,
		Price:      last.Close,
		Prediction: nil, // no ML
		Features:   nil, // no ML features
		Confidence: 0,
		StopLoss:   stopLoss,
		TakeProfit: 0, // no fixed TP — trailing stop is the exit
	}

	log.Info().
		Str("symbol", symbol).
		Str("signal", sigType.String()).
		Float64("price", last.Close).
		Float64("stop_loss", stopLoss).
		Float64("atr", atrVal).
		Float64("adx", safeIdx(adxVals, idx)).
		Float64("size_mult", sizeMultiplier).
		Msg("trend entry signal generated")

	// Store size multiplier on the signal for downstream use
	signal.SizeMultiplier = sizeMultiplier

	return signal
}

// ---------------------------------------------------------------------------
// UpdateTrailingStop — Chandelier Exit (Layer 3)
// ---------------------------------------------------------------------------

// UpdateTrailingStop updates the trailing stop for an existing position.
// The trailing stop only tightens (never moves against the position).
//
// Stop level is only recomputed when the last candle is closed (IsClosed=true)
// to avoid intra-bar whipsaws from transient price extremes. The stop-hit
// check runs on every tick regardless.
//
// Returns an ExitSignal if the current bar's low/high has breached the stop.
func (ts *TrendStrategy) UpdateTrailingStop(
	symbol string,
	candles []exchange.Candle,
) *ExitSignal {
	ts.mu.Lock()
	defer ts.mu.Unlock()

	pos, exists := ts.positions[symbol]
	if !exists {
		return nil
	}

	cfg := ts.config
	n := len(candles)
	if n < cfg.ChandelierLookback+1 {
		return nil
	}

	last := candles[n-1]

	// Only tighten the trailing stop on closed bars to avoid
	// intra-bar whipsaws from transient price extremes.
	if last.IsClosed {
		atrVals := features.ATR(candles, cfg.ATRPeriod)
		if atrVals != nil {
			idx := n - 1
			atrVal := atrVals[idx]

			if pos.Side == "LONG" {
				hhVals := features.HighestHigh(candles, cfg.ChandelierLookback)
				if hhVals != nil {
					// Dynamic Chandelier Exit (Patch 2): tighten multiplier as profit increases
					atrMult := ts.getDynamicATRMultiplier(pos, hhVals[idx])
					newStop := hhVals[idx] - atrMult*atrVal
					if newStop > pos.TrailingStop {
						log.Debug().
							Str("symbol", symbol).
							Float64("r_multiple", pos.CurrentR(last.Close)).
							Float64("atr_mult", atrMult).
							Float64("old_stop", pos.TrailingStop).
							Float64("new_stop", newStop).
							Msg("dynamic chandelier exit updated")
						pos.TrailingStop = newStop
					}
				}
			} else {
				llVals := features.LowestLow(candles, cfg.ChandelierLookback)
				if llVals != nil {
					// Dynamic Chandelier Exit (Patch 2): tighten multiplier as profit increases
					atrMult := ts.getDynamicATRMultiplier(pos, llVals[idx])
					newStop := llVals[idx] + atrMult*atrVal
					if newStop < pos.TrailingStop {
						log.Debug().
							Str("symbol", symbol).
							Float64("r_multiple", pos.CurrentR(last.Close)).
							Float64("atr_mult", atrMult).
							Float64("old_stop", pos.TrailingStop).
							Float64("new_stop", newStop).
							Msg("dynamic chandelier exit updated")
						pos.TrailingStop = newStop
					}
				}
			}
		}
	}

	// Increment bar counter on closed bars
	if last.IsClosed {
		pos.BarsSinceEntry++
	}

	// Time-based exit: close dead positions after N bars with minimal profit
	// A position is "dead" if it hasn't reached at least TimeStopMinR after TimeStopBars bars
	if pos.BarsSinceEntry >= ts.config.TimeStopBars {
		currentR := pos.CurrentR(last.Close)
		if currentR < ts.config.TimeStopMinR {
			log.Debug().
				Str("symbol", symbol).
				Int("bars_since_entry", pos.BarsSinceEntry).
				Float64("current_r", currentR).
				Msg("time stop triggered - closing dead position")
			return &ExitSignal{
				Symbol: symbol,
				Reason: "time_stop",
				Price:  last.Close,
			}
		}
	}

	// Check if stop hit (always, even intrabar)
	if pos.Side == "LONG" {
		if last.Low <= pos.TrailingStop {
			return &ExitSignal{
				Symbol: symbol,
				Reason: "trailing_stop",
				Price:  pos.TrailingStop,
			}
		}
	} else {
		if last.High >= pos.TrailingStop {
			return &ExitSignal{
				Symbol: symbol,
				Reason: "trailing_stop",
				Price:  pos.TrailingStop,
			}
		}
	}

	return nil
}

// getDynamicATRMultiplier returns the ATR multiplier based on current R-multiple.
// As profit increases, the multiplier decreases to tighten the stop and lock in profits.
// Patch 2: Dynamic Chandelier Exit
func (ts *TrendStrategy) getDynamicATRMultiplier(pos *TrendPosition, currentExtreme float64) float64 {
	if pos.InitialRisk <= 0 {
		return ts.config.ATRStopMult
	}

	// Calculate current profit
	var currentProfit float64
	if pos.Side == "LONG" {
		currentProfit = currentExtreme - pos.EntryPrice
	} else {
		currentProfit = pos.EntryPrice - currentExtreme
	}

	rMultiple := currentProfit / pos.InitialRisk

	// Select multiplier based on profit level
	switch {
	case rMultiple > 6:
		return 2.0
	case rMultiple > 4:
		return 2.0
	case rMultiple > 2:
		return 2.5
	default:
		return ts.config.ATRStopMult
	}
}

// ---------------------------------------------------------------------------
// CheckPartialExit — R-Multiple Targets (Layer 3)
// ---------------------------------------------------------------------------

// CheckPartialExit checks if the current price has reached an R-multiple
// target for partial position exit. Returns nil if no partial exit needed.
func (ts *TrendStrategy) CheckPartialExit(
	symbol string,
	currentPrice float64,
) *PartialExitSignal {
	if !ts.config.PartialExitEnabled {
		return nil
	}

	ts.mu.Lock()
	defer ts.mu.Unlock()

	pos, exists := ts.positions[symbol]
	if !exists {
		return nil
	}

	currentR := pos.CurrentR(currentPrice)

	// Check 6R target first (stage 1 -> stage 2)
	// NOTE: PartialStage is NOT advanced here — it is advanced in
	// ApplyPartialExit after the order is confirmed filled. This prevents
	// state corruption if the order fails.
	if pos.PartialStage == 1 && currentR >= ts.config.SecondTargetR {
		exitSize := pos.Size * ts.config.SecondExitPct
		if exitSize > 0 {
			return &PartialExitSignal{
				Symbol:     symbol,
				ExitPct:    ts.config.SecondExitPct,
				ExitSize:   exitSize,
				Reason:     "partial_6r",
				MoveStopBE: false,
			}
		}
	}

	// Check 3R target (stage 0 -> stage 1)
	if pos.PartialStage == 0 && currentR >= ts.config.FirstTargetR {
		exitSize := pos.Size * ts.config.FirstExitPct
		if exitSize > 0 {
			return &PartialExitSignal{
				Symbol:     symbol,
				ExitPct:    ts.config.FirstExitPct,
				ExitSize:   exitSize,
				Reason:     "partial_3r",
				MoveStopBE: true,
				NewStop:    pos.EntryPrice, // breakeven
			}
		}
	}

	return nil
}

// ApplyPartialExit reduces position size, advances the partial exit stage,
// and optionally moves the stop to breakeven. Called after the partial exit
// order is successfully filled.
//
// The `reason` parameter ("partial_3r" or "partial_6r") determines which
// stage transition occurs. Stage advancement is deferred to this method
// (rather than CheckPartialExit) so that a failed order does not corrupt
// the state machine.
func (ts *TrendStrategy) ApplyPartialExit(symbol string, exitSize float64, moveStopBE bool, newStop float64, reason string) {
	ts.mu.Lock()
	defer ts.mu.Unlock()

	pos, exists := ts.positions[symbol]
	if !exists {
		return
	}

	pos.Size -= exitSize
	if pos.Size < 0 {
		pos.Size = 0
	}

	if moveStopBE && newStop > 0 {
		pos.TrailingStop = newStop
	}

	// Advance partial stage based on which exit was filled
	if reason == "partial_3r" {
		pos.PartialStage = 1
	} else if reason == "partial_6r" {
		pos.PartialStage = 2
	}
}

// ---------------------------------------------------------------------------
// CheckDailyLossCap
// ---------------------------------------------------------------------------

// CheckDailyLossCap checks if the daily loss cap has been reached and halts
// new entries if so. Does NOT close existing positions.
// An optional unrealizedPnL can be passed to include open-position PnL in the check.
func (ts *TrendStrategy) CheckDailyLossCap(equity float64, unrealizedPnL ...float64) {
	ts.mu.Lock()
	defer ts.mu.Unlock()

	ts.checkDailyReset()

	totalPnL := ts.dailyPnL
	if len(unrealizedPnL) > 0 {
		totalPnL += unrealizedPnL[0]
	}

	capAmount := equity * ts.config.DailyLossCapPct
	if totalPnL < -capAmount {
		if !ts.dailyHalted {
			log.Warn().
				Float64("daily_pnl", ts.dailyPnL).
				Float64("unrealized", totalPnL-ts.dailyPnL).
				Float64("total", totalPnL).
				Float64("cap", capAmount).
				Msg("daily loss cap reached — halting new entries")
			ts.dailyHalted = true
		}
	}
}

// GetDailyPnL returns the current daily PnL.
func (ts *TrendStrategy) GetDailyPnL() float64 {
	ts.mu.Lock()
	defer ts.mu.Unlock()
	ts.checkDailyReset()
	return ts.dailyPnL
}

// ---------------------------------------------------------------------------
// Portfolio Drawdown Circuit Breaker
// ---------------------------------------------------------------------------

// CheckPortfolioDrawdown checks if portfolio equity has breached the max drawdown threshold.
// If breached, halts all new entries for DrawdownHaltHours.
func (ts *TrendStrategy) CheckPortfolioDrawdown(currentEquity float64) {
	ts.mu.Lock()
	defer ts.mu.Unlock()

	if currentEquity > ts.peakEquity {
		ts.peakEquity = currentEquity
	}
	if ts.peakEquity <= 0 {
		return
	}

	drawdown := (ts.peakEquity - currentEquity) / ts.peakEquity
	if drawdown >= ts.config.MaxDrawdownPct {
		haltUntil := time.Now().Add(time.Duration(ts.config.DrawdownHaltHours) * time.Hour)
		if haltUntil.After(ts.drawdownHaltUntil) {
			ts.drawdownHaltUntil = haltUntil
			log.Warn().
				Float64("drawdown_pct", drawdown*100).
				Float64("peak", ts.peakEquity).
				Float64("current", currentEquity).
				Time("halt_until", haltUntil).
				Msg("portfolio drawdown circuit breaker triggered")
		}
	}
}

// IsDrawdownHalted returns true if the portfolio drawdown circuit breaker is active.
func (ts *TrendStrategy) IsDrawdownHalted() bool {
	ts.mu.Lock()
	defer ts.mu.Unlock()
	return time.Now().Before(ts.drawdownHaltUntil)
}

// ---------------------------------------------------------------------------
// CalculatePositionSize — ATR-based position sizing
// ---------------------------------------------------------------------------

// CalculatePositionSize computes the position size based on ATR risk.
//
//	size = (equity * riskPerTrade * sizeMultiplier * marketVolScalar) / (entryPrice * stopDistancePct)
//	capped by maxLeverage
//
// The marketVolScalar parameter (Patch 4: Volatility Scalar) adjusts size based on
// overall market regime: 1.2x in quiet markets, 0.5x in violent markets, 1.0x otherwise.
func (ts *TrendStrategy) CalculatePositionSize(
	equity, entryPrice, stopLoss, sizeMultiplier, marketVolScalar float64,
) float64 {
	cfg := ts.config

	stopDistancePct := math.Abs((entryPrice - stopLoss) / entryPrice)
	if stopDistancePct < 0.0001 {
		return 0
	}

	// Apply market volatility scalar (Patch 4)
	if marketVolScalar <= 0 {
		marketVolScalar = 1.0
	}

	riskAmount := equity * cfg.RiskPerTrade * sizeMultiplier * marketVolScalar
	size := riskAmount / (entryPrice * stopDistancePct)

	// Apply leverage constraint
	if cfg.MaxLeverage > 0 && equity > 0 {
		maxSize := (equity * cfg.MaxLeverage) / entryPrice
		if size > maxSize {
			size = maxSize
		}
	}

	return size
}

// ---------------------------------------------------------------------------
// Market Volatility Scalar (Patch 4: Volatility Scalar)
// ---------------------------------------------------------------------------

// MarketVolatilityScalar calculates a position size scalar based on market regime.
// Uses the average ATR% of BTC and ETH as a proxy for overall market volatility.
//
// Returns:
//   - 1.2 if market is quiet (ATR% < 2%) — safe to take bigger positions
//   - 0.5 if market is violent (ATR% > 5%) — preserve capital
//   - 1.0 otherwise (normal market)
func MarketVolatilityScalar(btcATRPct, ethATRPct float64) float64 {
	marketVol := (btcATRPct + ethATRPct) / 2.0

	switch {
	case marketVol > 0.05: // High vol (5%+)
		return 0.5
	case marketVol < 0.02: // Low vol (<2%)
		return 1.2
	default:
		return 1.0
	}
}

// CalculateATRPercent calculates the ATR as a percentage of price.
// Returns ATR[lastIndex] / Close[lastIndex].
func CalculateATRPercent(candles []exchange.Candle, period int) float64 {
	if len(candles) < period+1 {
		return 0
	}

	atr := features.ATR(candles, period)
	if atr == nil || len(atr) == 0 {
		return 0
	}

	lastIdx := len(candles) - 1
	lastClose := candles[lastIdx].Close
	if lastClose <= 0 {
		return 0
	}

	return atr[lastIdx] / lastClose
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func safeIdx(arr []float64, idx int) float64 {
	if arr == nil || idx < 0 || idx >= len(arr) {
		return 0
	}
	return arr[idx]
}

// countSameDirection returns how many open positions are in the given direction.
func (ts *TrendStrategy) countSameDirection(direction string) int {
	ts.mu.Lock()
	defer ts.mu.Unlock()
	count := 0
	for _, pos := range ts.positions {
		if pos.Side == direction {
			count++
		}
	}
	return count
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

// UpdateOIHistory adds an OI value to the history for a symbol.
// Call this periodically (e.g., each scan) to build up the z-score calculation.
func (ts *TrendStrategy) UpdateOIHistory(symbol string, oi float64) {
	ts.mu.Lock()
	defer ts.mu.Unlock()

	if ts.oiHistory == nil {
		ts.oiHistory = make(map[string][]float64)
	}

	history := ts.oiHistory[symbol]
	history = append(history, oi)

	// Keep only the last N samples
	lookback := ts.config.OIFilterLookback
	if lookback <= 0 {
		lookback = 30
	}
	if len(history) > lookback {
		history = history[len(history)-lookback:]
	}

	ts.oiHistory[symbol] = history
}

// getOIZScore calculates the z-score of the latest OI vs historical mean/stddev.
// Returns 0 if insufficient data.
func (ts *TrendStrategy) getOIZScore(symbol string) float64 {
	// Note: ts.mu should already be locked by caller, or we can lock here for safety
	history := ts.oiHistory[symbol]
	n := len(history)
	if n < 5 {
		return 0 // not enough data
	}

	// Mean
	var sum float64
	for _, v := range history {
		sum += v
	}
	mean := sum / float64(n)

	// Stddev
	var sumSq float64
	for _, v := range history {
		diff := v - mean
		sumSq += diff * diff
	}
	stddev := math.Sqrt(sumSq / float64(n))

	if stddev == 0 {
		return 0
	}

	latest := history[n-1]
	return (latest - mean) / stddev
}
