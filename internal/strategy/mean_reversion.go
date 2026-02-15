// Package strategy — Mean Reversion strategy.
//
// Mean reversion trading assumes prices tend to return to their historical
// average over time. This strategy identifies overbought/oversold conditions
// and enters trades when price deviates significantly from its mean.
//
// Architecture:
//
//	Layer 1: Entry signals (RSI extremes, Bollinger Band touches, price deviations)
//	Layer 2: Regime filters (trend strength, volatility regime, mean reversion suitability)
//	Layer 3: Risk management (fixed stops, time-based exits, profit targets)
package strategy

import (
	"math"
	"sync"
	"time"

	"github.com/cgn175/quant-bot/internal/data"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/features"
	"github.com/cgn175/quant-bot/internal/metrics"
	"github.com/cgn175/quant-bot/internal/mlfilter"
	"github.com/rs/zerolog/log"
)

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

// MeanReversionConfig holds all parameters for the mean reversion strategy.
type MeanReversionConfig struct {
	// Layer 1: Entry signal parameters
	RSIPeriod      int     // 14 — RSI lookback period
	RSIOverbought  float64 // 70 — RSI threshold for short entry
	RSIOversold    float64 // 30 — RSI threshold for long entry
	RSIExtremeHigh float64 // 80 — extreme overbought (stronger signal)
	RSIExtremeLow  float64 // 20 — extreme oversold (stronger signal)

	BBPeriod         int     // 20 — Bollinger Bands period
	BBStdDev         float64 // 2.0 — Bollinger Bands standard deviation multiplier
	BBEntryThreshold float64 // 0.5 — how far outside band to trigger (0=at band, 1=1 std dev beyond)

	PriceMAPeriod     int     // 50 — price mean reversion reference
	PriceDevThreshold float64 // 0.02 — 2% deviation from MA to trigger

	VolumePeriod   int     // 20 — volume confirmation lookback
	MinVolumeRatio float64 // 0.8 — volume must be at least 80% of average

	// Layer 2: Regime filter parameters
	ADXPeriod      int     // 14
	ADXMaxTrending float64 // 25 — max ADX for mean reversion (avoid trending markets)
	ADXMinRanging  float64 // 15 — min ADX to confirm ranging market

	ATRPeriod     int     // 14
	VolatilityMin float64 // 0.005 — min ATR% (avoid dead markets)
	VolatilityMax float64 // 0.03 — max ATR% (avoid explosive volatility)

	MeanRevLookback    int     // 20 — bars to check for mean reversion success
	MeanRevSuccessRate float64 // 0.6 — min 60% success rate in recent history

	FundingExtreme  float64 // 0.0005 — block trades
	FundingElevated float64 // 0.0003 — reduce size

	// Layer 3: Risk management
	RiskPerTrade float64 // 0.005 — 0.5% of equity per trade (smaller than trend)
	MaxLeverage  float64 // 1.0 — lower leverage for mean reversion

	StopLossATRMult   float64 // 2.0 — ATR multiplier for initial stop
	TakeProfitATRMult float64 // 1.5 — ATR multiplier for profit target (mean reversion target)

	TimeStopBars int // 8 — exit if mean reversion hasn't occurred

	DailyLossCapPct       float64 // 0.03 — 3% of equity
	MaxOpenPositions      int     // 6 — more positions allowed (shorter holds)
	MaxCorrelatedSame     int     // 3 — max same-direction on correlated pairs
	MaxPositionsPerSector int     // 2 — max positions in same sector

	// Portfolio circuit breaker
	MaxDrawdownPct    float64 // 0.15 — halt all if equity drops 15% from peak
	DrawdownHaltHours int     // 48 — hours to halt after drawdown breach

	// Trailing stop for mean reversion (tighter than trend)
	TrailingEnabled  bool    // true — use trailing stop once in profit
	TrailingATRMult  float64 // 1.5 — ATR multiplier for trailing stop
	TrailingTriggerR float64 // 0.5 — start trailing at 0.5R profit

	// ML filter parameters (optional)
	MLFilterEnabled bool
	MLThreshold     float64
	FallbackToADX   bool
	FailOpen        bool
}

// DefaultMeanReversionConfig returns the default mean reversion configuration.
func DefaultMeanReversionConfig() MeanReversionConfig {
	return MeanReversionConfig{
		RSIPeriod:             14,
		RSIOverbought:         70,
		RSIOversold:           30,
		RSIExtremeHigh:        80,
		RSIExtremeLow:         20,
		BBPeriod:              20,
		BBStdDev:              2.0,
		BBEntryThreshold:      0.5,
		PriceMAPeriod:         50,
		PriceDevThreshold:     0.02,
		VolumePeriod:          20,
		MinVolumeRatio:        0.8,
		ADXPeriod:             14,
		ADXMaxTrending:        25,
		ADXMinRanging:         15,
		ATRPeriod:             14,
		VolatilityMin:         0.005,
		VolatilityMax:         0.03,
		MeanRevLookback:       20,
		MeanRevSuccessRate:    0.6,
		FundingExtreme:        0.0005,
		FundingElevated:       0.0003,
		RiskPerTrade:          0.005,
		MaxLeverage:           1.0,
		StopLossATRMult:       2.0,
		TakeProfitATRMult:     1.5,
		TimeStopBars:          8,
		DailyLossCapPct:       0.03,
		MaxOpenPositions:      6,
		MaxCorrelatedSame:     3,
		MaxPositionsPerSector: 2,
		MaxDrawdownPct:        0.15,
		DrawdownHaltHours:     48,
		TrailingEnabled:       true,
		TrailingATRMult:       1.5,
		TrailingTriggerR:      0.5,
		MLFilterEnabled:       false,
		MLThreshold:           0.5,
		FallbackToADX:         true,
		FailOpen:              true,
	}
}

// MinCandles returns the minimum number of candles needed for all indicators.
func (c MeanReversionConfig) MinCandles() int {
	// Need max of: RSI(14), BB(20), MA(50), ATR(14), ADX(14), mean rev lookback
	min := c.PriceMAPeriod + 1
	if c.BBPeriod+1 > min {
		min = c.BBPeriod + 1
	}
	if 2*c.ADXPeriod+1 > min {
		min = 2*c.ADXPeriod + 1
	}
	if c.MeanRevLookback+c.PriceMAPeriod > min {
		min = c.MeanRevLookback + c.PriceMAPeriod
	}
	return min + 5 // safety margin
}

// ---------------------------------------------------------------------------
// Position tracking
// ---------------------------------------------------------------------------

// MeanRevPosition tracks an open position for mean reversion strategy.
type MeanRevPosition struct {
	Symbol         string
	Side           string // "LONG" or "SHORT"
	EntryPrice     float64
	EntryTime      time.Time
	Size           float64
	OriginalSize   float64
	InitialStop    float64
	TrailingStop   float64
	TakeProfit     float64
	InitialRisk    float64
	HighestR       float64 // highest R-multiple achieved
	TrailingActive bool    // trailing stop activated
	Pending        bool    // true if this is a reservation
	BarsSinceEntry int
}

// CurrentR returns the current profit in R-multiples.
func (p *MeanRevPosition) CurrentR(currentPrice float64) float64 {
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

// UpdateHighestR updates the highest R achieved (for trailing stop activation).
func (p *MeanRevPosition) UpdateHighestR(currentPrice float64) {
	r := p.CurrentR(currentPrice)
	if r > p.HighestR {
		p.HighestR = r
	}
}

// ---------------------------------------------------------------------------
// MeanReversionStrategy
// ---------------------------------------------------------------------------

// MeanReversionStrategy implements a mean reversion trading system.
type MeanReversionStrategy struct {
	config   MeanReversionConfig
	mlClient *mlfilter.Client
	prom     *metrics.Metrics

	mu        sync.Mutex
	positions map[string]*MeanRevPosition

	// Daily loss tracking
	dailyPnL       float64
	dailyResetDate time.Time
	dailyHalted    bool

	// Portfolio drawdown circuit breaker
	peakEquity        float64
	drawdownHaltUntil time.Time
}

// MeanReversionStrategyOption configures optional dependencies.
type MeanReversionStrategyOption func(*MeanReversionStrategy)

// WithMeanRevMLClient sets the ML filter client.
func WithMeanRevMLClient(c *mlfilter.Client) MeanReversionStrategyOption {
	return func(mrs *MeanReversionStrategy) { mrs.mlClient = c }
}

// WithMeanRevMetrics sets the Prometheus metrics collector.
func WithMeanRevMetrics(m *metrics.Metrics) MeanReversionStrategyOption {
	return func(mrs *MeanReversionStrategy) { mrs.prom = m }
}

// NewMeanReversionStrategy creates a new mean reversion strategy.
func NewMeanReversionStrategy(config MeanReversionConfig, opts ...MeanReversionStrategyOption) *MeanReversionStrategy {
	mrs := &MeanReversionStrategy{
		config:         config,
		positions:      make(map[string]*MeanRevPosition),
		dailyResetDate: time.Now().UTC().Truncate(24 * time.Hour),
	}
	for _, opt := range opts {
		opt(mrs)
	}
	return mrs
}

// GetPosition returns a copy of the position for a symbol, or nil.
func (mrs *MeanReversionStrategy) GetPosition(symbol string) *MeanRevPosition {
	mrs.mu.Lock()
	defer mrs.mu.Unlock()
	pos, exists := mrs.positions[symbol]
	if !exists {
		return nil
	}
	cp := *pos
	return &cp
}

// HasPosition returns true if a position exists for the symbol.
func (mrs *MeanReversionStrategy) HasPosition(symbol string) bool {
	mrs.mu.Lock()
	defer mrs.mu.Unlock()
	_, exists := mrs.positions[symbol]
	return exists
}

// OpenPositionCount returns the number of open positions.
func (mrs *MeanReversionStrategy) OpenPositionCount() int {
	mrs.mu.Lock()
	defer mrs.mu.Unlock()
	return len(mrs.positions)
}

// RegisterPosition records a new position after order execution succeeds.
func (mrs *MeanReversionStrategy) RegisterPosition(symbol, side string, entryPrice, size, initialStop, takeProfit float64) {
	mrs.mu.Lock()
	defer mrs.mu.Unlock()

	var initialRisk float64
	if side == "LONG" {
		initialRisk = entryPrice - initialStop
	} else {
		initialRisk = initialStop - entryPrice
	}

	mrs.positions[symbol] = &MeanRevPosition{
		Symbol:       symbol,
		Side:         side,
		EntryPrice:   entryPrice,
		EntryTime:    time.Now(),
		Size:         size,
		OriginalSize: size,
		InitialStop:  initialStop,
		TrailingStop: initialStop,
		TakeProfit:   takeProfit,
		InitialRisk:  initialRisk,
		HighestR:     0,
		Pending:      false,
	}
}

// RemovePosition removes a position after it's fully closed.
func (mrs *MeanReversionStrategy) RemovePosition(symbol string) {
	mrs.mu.Lock()
	defer mrs.mu.Unlock()
	delete(mrs.positions, symbol)
}

// RecordPnL records realized PnL for daily loss tracking.
func (mrs *MeanReversionStrategy) RecordPnL(pnl float64) {
	mrs.mu.Lock()
	defer mrs.mu.Unlock()
	mrs.checkDailyReset()
	mrs.dailyPnL += pnl
}

// IsDailyHalted returns true if the daily loss cap has been hit.
func (mrs *MeanReversionStrategy) IsDailyHalted() bool {
	mrs.mu.Lock()
	defer mrs.mu.Unlock()
	mrs.checkDailyReset()
	return mrs.dailyHalted
}

func (mrs *MeanReversionStrategy) checkDailyReset() {
	today := time.Now().UTC().Truncate(24 * time.Hour)
	if today.After(mrs.dailyResetDate) {
		mrs.dailyPnL = 0
		mrs.dailyHalted = false
		mrs.dailyResetDate = today
	}
}

// ---------------------------------------------------------------------------
// Entry gating and reservations
// ---------------------------------------------------------------------------

// CanEnter checks if entry is allowed for the given symbol and direction.
func (mrs *MeanReversionStrategy) CanEnter(symbol string, direction string) (bool, string) {
	mrs.mu.Lock()
	defer mrs.mu.Unlock()

	return mrs.canEnterLocked(symbol, direction)
}

func (mrs *MeanReversionStrategy) canEnterLocked(symbol string, direction string) (bool, string) {
	// Already have a position?
	if _, exists := mrs.positions[symbol]; exists {
		return false, "position_exists"
	}

	// Max positions reached?
	if len(mrs.positions) >= mrs.config.MaxOpenPositions {
		return false, "max_positions"
	}

	// Daily loss cap?
	mrs.checkDailyReset()
	if mrs.dailyHalted {
		return false, "daily_halted"
	}

	// Portfolio drawdown circuit breaker
	if time.Now().Before(mrs.drawdownHaltUntil) {
		return false, "drawdown_halted"
	}

	// Sector limit check
	if mrs.config.MaxPositionsPerSector > 0 {
		newSector := getSector(symbol)
		sectorCount := 0
		for _, pos := range mrs.positions {
			if getSector(pos.Symbol) == newSector {
				sectorCount++
			}
		}
		if sectorCount >= mrs.config.MaxPositionsPerSector {
			return false, "sector_limit"
		}
	}

	// Correlation limit
	sameCount := 0
	for _, pos := range mrs.positions {
		if pos.Side == direction {
			sameCount++
		}
	}
	if sameCount >= mrs.config.MaxCorrelatedSame {
		return false, "correlated_limit"
	}

	return true, ""
}

// TryReserveEntry atomically checks and reserves entry.
func (mrs *MeanReversionStrategy) TryReserveEntry(symbol string, direction string) (bool, string) {
	mrs.mu.Lock()
	defer mrs.mu.Unlock()

	ok, reason := mrs.canEnterLocked(symbol, direction)
	if !ok {
		return false, reason
	}

	mrs.positions[symbol] = &MeanRevPosition{
		Symbol:    symbol,
		Side:      direction,
		EntryTime: time.Now(),
		Pending:   true,
	}

	log.Debug().Str("symbol", symbol).Str("side", direction).Msg("mean reversion entry reservation created")
	return true, ""
}

// ConfirmReservation converts a pending reservation into a real position.
func (mrs *MeanReversionStrategy) ConfirmReservation(symbol, side string, entryPrice, size, initialStop, takeProfit float64) {
	mrs.mu.Lock()
	defer mrs.mu.Unlock()

	var initialRisk float64
	if side == "LONG" {
		initialRisk = entryPrice - initialStop
	} else {
		initialRisk = initialStop - entryPrice
	}

	mrs.positions[symbol] = &MeanRevPosition{
		Symbol:       symbol,
		Side:         side,
		EntryPrice:   entryPrice,
		EntryTime:    time.Now(),
		Size:         size,
		OriginalSize: size,
		InitialStop:  initialStop,
		TrailingStop: initialStop,
		TakeProfit:   takeProfit,
		InitialRisk:  initialRisk,
		HighestR:     0,
		Pending:      false,
	}

	log.Debug().Str("symbol", symbol).Str("side", side).Float64("price", entryPrice).Msg("mean reversion reservation confirmed")
}

// CancelReservation removes a pending reservation.
func (mrs *MeanReversionStrategy) CancelReservation(symbol string) {
	mrs.mu.Lock()
	defer mrs.mu.Unlock()

	pos, exists := mrs.positions[symbol]
	if exists && pos.Pending {
		delete(mrs.positions, symbol)
		log.Debug().Str("symbol", symbol).Msg("mean reversion reservation cancelled")
	}
}

// ---------------------------------------------------------------------------
// OnBar — Main entry signal generation
// ---------------------------------------------------------------------------

// OnBar evaluates whether a new mean reversion entry signal should be generated.
func (mrs *MeanReversionStrategy) OnBar(
	symbol string,
	candles []exchange.Candle,
	fundingCache *data.FundingCache,
	equity float64,
) *Signal {
	cfg := mrs.config
	n := len(candles)

	if n < cfg.MinCandles() {
		return nil
	}

	last := candles[n-1]
	idx := n - 1

	// -------------------------------------------------------------
	// Layer 1: Entry signals (mean reversion triggers)
	// -------------------------------------------------------------

	// 1a. RSI extremes
	rsiVals := features.RSI(candles, cfg.RSIPeriod)
	if rsiVals == nil {
		return nil
	}
	rsi := rsiVals[idx]

	// 1b. Bollinger Bands
	bb := features.Bollinger(candles, cfg.BBPeriod, cfg.BBStdDev)
	if bb == nil {
		return nil
	}

	// 1c. Price deviation from MA
	maVals := features.SMA(candles, cfg.PriceMAPeriod)
	if maVals == nil {
		return nil
	}
	ma := maVals[idx]
	priceDev := (last.Close - ma) / ma

	// Determine signal direction based on oversold/overbought conditions
	var longSignal, shortSignal bool
	var signalStrength float64 // 0-1, higher = stronger signal

	// Long entry: oversold conditions
	if rsi < cfg.RSIOversold || last.Close < bb.Lower[idx]*(1-cfg.BBEntryThreshold*0.1) || priceDev < -cfg.PriceDevThreshold {
		longSignal = true
		// Calculate signal strength (lower RSI = stronger)
		rsiStrength := (cfg.RSIOversold - rsi) / cfg.RSIOversold
		if rsiStrength < 0 {
			rsiStrength = 0
		}
		if rsiStrength > 1 {
			rsiStrength = 1
		}
		bbStrength := (bb.Lower[idx] - last.Close) / (bb.Lower[idx] * 0.02)
		if bbStrength < 0 {
			bbStrength = 0
		}
		if bbStrength > 1 {
			bbStrength = 1
		}
		devStrength := math.Abs(priceDev) / cfg.PriceDevThreshold
		if devStrength > 1 {
			devStrength = 1
		}
		// Combine strengths (take max)
		signalStrength = rsiStrength
		if bbStrength > signalStrength {
			signalStrength = bbStrength
		}
		if devStrength > signalStrength {
			signalStrength = devStrength
		}
	}

	// Short entry: overbought conditions
	if rsi > cfg.RSIOverbought || last.Close > bb.Upper[idx]*(1+cfg.BBEntryThreshold*0.1) || priceDev > cfg.PriceDevThreshold {
		shortSignal = true
		// Calculate signal strength (higher RSI = stronger)
		rsiStrength := (rsi - cfg.RSIOverbought) / (100 - cfg.RSIOverbought)
		if rsiStrength < 0 {
			rsiStrength = 0
		}
		if rsiStrength > 1 {
			rsiStrength = 1
		}
		bbStrength := (last.Close - bb.Upper[idx]) / (bb.Upper[idx] * 0.02)
		if bbStrength < 0 {
			bbStrength = 0
		}
		if bbStrength > 1 {
			bbStrength = 1
		}
		devStrength := priceDev / cfg.PriceDevThreshold
		if devStrength > 1 {
			devStrength = 1
		}
		// Combine strengths (take max)
		signalStrength = rsiStrength
		if bbStrength > signalStrength {
			signalStrength = bbStrength
		}
		if devStrength > signalStrength {
			signalStrength = devStrength
		}
	}

	if !longSignal && !shortSignal {
		return nil
	}

	// Volume confirmation
	volRatio := features.VolumeRatio(candles, cfg.VolumePeriod)
	if volRatio != nil && volRatio[idx] < cfg.MinVolumeRatio {
		log.Debug().Str("symbol", symbol).Float64("vol_ratio", volRatio[idx]).Msg("mean reversion: volume too low")
		return nil
	}

	// Check entry gating
	direction := "LONG"
	if shortSignal {
		direction = "SHORT"
	}
	if ok, reason := mrs.CanEnter(symbol, direction); !ok {
		log.Debug().Str("symbol", symbol).Str("reason", reason).Msg("mean reversion entry blocked")
		return nil
	}

	// -------------------------------------------------------------
	// Layer 2: Regime filters
	// -------------------------------------------------------------

	// 2a. ADX filter — mean reversion works best in ranging markets (ADX not too high)
	adxVals := features.ADX(candles, cfg.ADXPeriod)
	if adxVals != nil {
		adx := adxVals[idx]
		// Block if market is strongly trending
		if adx > cfg.ADXMaxTrending {
			log.Debug().Str("symbol", symbol).Float64("adx", adx).Msg("mean reversion: market too trending")
			if mrs.prom != nil {
				mrs.prom.ADXFilterBlockedTotal.WithLabelValues(symbol).Inc()
			}
			return nil
		}
	}

	// 2b. Volatility filter — need some volatility but not too much
	atrVals := features.ATR(candles, cfg.ATRPeriod)
	if atrVals != nil {
		atrPct := atrVals[idx] / last.Close
		if atrPct < cfg.VolatilityMin {
			log.Debug().Str("symbol", symbol).Float64("atr_pct", atrPct).Msg("mean reversion: volatility too low")
			return nil
		}
		if atrPct > cfg.VolatilityMax {
			log.Debug().Str("symbol", symbol).Float64("atr_pct", atrPct).Msg("mean reversion: volatility too high")
			return nil
		}
	}

	// 2c. Mean reversion suitability check — has price been reverting recently?
	if !mrs.checkMeanReversionHistory(candles, idx) {
		log.Debug().Str("symbol", symbol).Msg("mean reversion: historical success rate too low")
		return nil
	}

	// 2d. Funding rate filter
	sizeMultiplier := 1.0
	if fundingCache != nil {
		if longSignal && fundingCache.IsLongCrowded(symbol, cfg.FundingExtreme) {
			log.Debug().Str("symbol", symbol).Msg("mean reversion: funding blocks LONG")
			return nil
		}
		if shortSignal && fundingCache.IsShortCrowded(symbol, cfg.FundingExtreme) {
			log.Debug().Str("symbol", symbol).Msg("mean reversion: funding blocks SHORT")
			return nil
		}
		sizeMultiplier = fundingCache.SizeMultiplier(symbol, cfg.FundingElevated)
	}

	// -------------------------------------------------------------
	// Build signal
	// -------------------------------------------------------------
	atrVal := atrVals[idx]
	stopDistance := cfg.StopLossATRMult * atrVal

	var sigType SignalType
	var stopLoss, takeProfit float64

	if longSignal {
		sigType = SignalLong
		stopLoss = last.Close - stopDistance
		takeProfit = last.Close + cfg.TakeProfitATRMult*atrVal // target mean reversion
	} else {
		sigType = SignalShort
		stopLoss = last.Close + stopDistance
		takeProfit = last.Close - cfg.TakeProfitATRMult*atrVal
	}

	signal := &Signal{
		Symbol:         symbol,
		Type:           sigType,
		Timestamp:      last.CloseTime,
		Price:          last.Close,
		Prediction:     nil,
		Features:       nil,
		Confidence:     signalStrength,
		StopLoss:       stopLoss,
		TakeProfit:     takeProfit,
		SizeMultiplier: sizeMultiplier,
	}

	log.Info().
		Str("symbol", symbol).
		Str("signal", sigType.String()).
		Float64("price", last.Close).
		Float64("rsi", rsi).
		Float64("bb_upper", bb.Upper[idx]).
		Float64("bb_lower", bb.Lower[idx]).
		Float64("ma", ma).
		Float64("price_dev", priceDev).
		Float64("stop_loss", stopLoss).
		Float64("take_profit", takeProfit).
		Float64("atr", atrVal).
		Float64("confidence", signalStrength).
		Msg("mean reversion entry signal generated")

	return signal
}

// checkMeanReversionHistory checks if price has been reverting to mean recently.
func (mrs *MeanReversionStrategy) checkMeanReversionHistory(candles []exchange.Candle, idx int) bool {
	cfg := mrs.config
	if idx < cfg.MeanRevLookback+cfg.PriceMAPeriod {
		return false
	}

	maVals := features.SMA(candles, cfg.PriceMAPeriod)
	if maVals == nil {
		return false
	}

	successCount := 0
	checkCount := 0

	// Look back at recent deviations and check if they reverted
	for i := idx - cfg.MeanRevLookback; i < idx; i++ {
		if i < cfg.PriceMAPeriod {
			continue
		}

		price := candles[i].Close
		ma := maVals[i]
		deviation := (price - ma) / ma

		// Only check significant deviations
		if math.Abs(deviation) < cfg.PriceDevThreshold*0.5 {
			continue
		}

		checkCount++

		// Check if price moved back toward MA in next few bars
		lookAhead := 5
		if i+lookAhead >= idx {
			continue
		}

		futurePrice := candles[i+lookAhead].Close
		futureMA := maVals[i+lookAhead]

		// Success if price moved closer to MA
		initialDist := math.Abs(price - ma)
		futureDist := math.Abs(futurePrice - futureMA)

		if futureDist < initialDist {
			successCount++
		}
	}

	if checkCount < 5 {
		// Not enough data points, allow it
		return true
	}

	successRate := float64(successCount) / float64(checkCount)
	return successRate >= cfg.MeanRevSuccessRate
}

// ---------------------------------------------------------------------------
// Exit management
// ---------------------------------------------------------------------------

// ExitSignal represents an exit trigger.
type MeanRevExitSignal struct {
	Symbol string
	Reason string
	Price  float64
}

// CheckExit checks for exit conditions (stop loss, take profit, time stop, trailing stop).
func (mrs *MeanReversionStrategy) CheckExit(
	symbol string,
	candles []exchange.Candle,
) *MeanRevExitSignal {
	mrs.mu.Lock()
	defer mrs.mu.Unlock()

	pos, exists := mrs.positions[symbol]
	if !exists || pos.Pending {
		return nil
	}

	cfg := mrs.config
	n := len(candles)
	if n < 2 {
		return nil
	}

	last := candles[n-1]
	currentPrice := last.Close

	// Update tracking
	pos.BarsSinceEntry++
	pos.UpdateHighestR(currentPrice)

	// 1. Check initial stop loss
	if pos.Side == "LONG" {
		if last.Low <= pos.InitialStop {
			return &MeanRevExitSignal{Symbol: symbol, Reason: "stop_loss", Price: pos.InitialStop}
		}
	} else {
		if last.High >= pos.InitialStop {
			return &MeanRevExitSignal{Symbol: symbol, Reason: "stop_loss", Price: pos.InitialStop}
		}
	}

	// 2. Check take profit (mean reversion target)
	if pos.Side == "LONG" {
		if last.High >= pos.TakeProfit {
			return &MeanRevExitSignal{Symbol: symbol, Reason: "take_profit", Price: pos.TakeProfit}
		}
	} else {
		if last.Low <= pos.TakeProfit {
			return &MeanRevExitSignal{Symbol: symbol, Reason: "take_profit", Price: pos.TakeProfit}
		}
	}

	// 3. Time-based exit (mean reversion hasn't happened)
	if pos.BarsSinceEntry >= cfg.TimeStopBars {
		return &MeanRevExitSignal{Symbol: symbol, Reason: "time_stop", Price: currentPrice}
	}

	// 4. Trailing stop (once in profit)
	if cfg.TrailingEnabled && pos.HighestR >= cfg.TrailingTriggerR {
		if !pos.TrailingActive {
			pos.TrailingActive = true
			// Set initial trailing stop at breakeven or better
			if pos.Side == "LONG" {
				pos.TrailingStop = pos.EntryPrice
			} else {
				pos.TrailingStop = pos.EntryPrice
			}
		}

		// Update trailing stop on closed bars
		if last.IsClosed && n >= cfg.ATRPeriod+1 {
			atrVals := features.ATR(candles, cfg.ATRPeriod)
			if atrVals != nil {
				atrVal := atrVals[n-1]
				if pos.Side == "LONG" {
					// For mean reversion, trail below recent lows
					llVals := features.LowestLow(candles, 3)
					if llVals != nil {
						newStop := llVals[n-1] - cfg.TrailingATRMult*atrVal
						if newStop > pos.TrailingStop {
							pos.TrailingStop = newStop
						}
					}
					if last.Low <= pos.TrailingStop {
						return &MeanRevExitSignal{Symbol: symbol, Reason: "trailing_stop", Price: pos.TrailingStop}
					}
				} else {
					// For shorts, trail above recent highs
					hhVals := features.HighestHigh(candles, 3)
					if hhVals != nil {
						newStop := hhVals[n-1] + cfg.TrailingATRMult*atrVal
						if newStop < pos.TrailingStop {
							pos.TrailingStop = newStop
						}
					}
					if last.High >= pos.TrailingStop {
						return &MeanRevExitSignal{Symbol: symbol, Reason: "trailing_stop", Price: pos.TrailingStop}
					}
				}
			}
		}
	}

	return nil
}

// ---------------------------------------------------------------------------
// Risk management
// ---------------------------------------------------------------------------

// CalculatePositionSize computes position size based on ATR risk.
func (mrs *MeanReversionStrategy) CalculatePositionSize(
	equity, entryPrice, stopLoss, sizeMultiplier float64,
) float64 {
	cfg := mrs.config

	stopDistancePct := math.Abs((entryPrice - stopLoss) / entryPrice)
	if stopDistancePct < 0.0001 {
		return 0
	}

	riskAmount := equity * cfg.RiskPerTrade * sizeMultiplier
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

// CheckDailyLossCap checks if daily loss cap has been reached.
func (mrs *MeanReversionStrategy) CheckDailyLossCap(equity float64, unrealizedPnL ...float64) {
	mrs.mu.Lock()
	defer mrs.mu.Unlock()

	mrs.checkDailyReset()

	totalPnL := mrs.dailyPnL
	if len(unrealizedPnL) > 0 {
		totalPnL += unrealizedPnL[0]
	}

	capAmount := equity * mrs.config.DailyLossCapPct
	if totalPnL < -capAmount {
		if !mrs.dailyHalted {
			log.Warn().
				Float64("daily_pnl", mrs.dailyPnL).
				Float64("unrealized", totalPnL-mrs.dailyPnL).
				Float64("total", totalPnL).
				Float64("cap", capAmount).
				Msg("mean reversion: daily loss cap reached — halting new entries")
			mrs.dailyHalted = true
		}
	}
}

// GetDailyPnL returns the current daily PnL.
func (mrs *MeanReversionStrategy) GetDailyPnL() float64 {
	mrs.mu.Lock()
	defer mrs.mu.Unlock()
	mrs.checkDailyReset()
	return mrs.dailyPnL
}

// CheckPortfolioDrawdown checks portfolio drawdown circuit breaker.
func (mrs *MeanReversionStrategy) CheckPortfolioDrawdown(currentEquity float64) {
	mrs.mu.Lock()
	defer mrs.mu.Unlock()

	if currentEquity > mrs.peakEquity {
		mrs.peakEquity = currentEquity
	}
	if mrs.peakEquity <= 0 {
		return
	}

	drawdown := (mrs.peakEquity - currentEquity) / mrs.peakEquity
	if drawdown >= mrs.config.MaxDrawdownPct {
		haltUntil := time.Now().Add(time.Duration(mrs.config.DrawdownHaltHours) * time.Hour)
		if haltUntil.After(mrs.drawdownHaltUntil) {
			mrs.drawdownHaltUntil = haltUntil
			log.Warn().
				Float64("drawdown_pct", drawdown*100).
				Float64("peak", mrs.peakEquity).
				Float64("current", currentEquity).
				Time("halt_until", haltUntil).
				Msg("mean reversion: portfolio drawdown circuit breaker triggered")
		}
	}
}

// IsDrawdownHalted returns true if drawdown circuit breaker is active.
func (mrs *MeanReversionStrategy) IsDrawdownHalted() bool {
	mrs.mu.Lock()
	defer mrs.mu.Unlock()
	return time.Now().Before(mrs.drawdownHaltUntil)
}

// GetPositionHighestR returns the highest R achieved for a position.
func (mrs *MeanReversionStrategy) GetPositionHighestR(symbol string) float64 {
	mrs.mu.Lock()
	defer mrs.mu.Unlock()
	pos, exists := mrs.positions[symbol]
	if !exists {
		return 0
	}
	return pos.HighestR
}
