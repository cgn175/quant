package risk

import (
	"fmt"
	"sync"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/rs/zerolog/log"
)

// StrategyExposure tracks exposure for a specific strategy on a symbol
type StrategyExposure struct {
	StrategyType string
	Notional     float64
	Side         string // "LONG", "SHORT", or "NEUTRAL" (for delta-neutral)
}

// PortfolioMonitor tracks cross-strategy exposure to prevent double exposure
// when correlated strategies (funding arb, basis trade) fire on the same symbol.
type PortfolioMonitor struct {
	mu sync.RWMutex

	// Limits
	maxTotalPerpSpotExposure float64 // Max $ across all strategies
	maxPerSymbolExposure     float64 // Max $ per symbol
	enableCorrelatedCheck    bool    // Whether to block correlated strategies

	// Current state: symbol -> list of strategy exposures
	exposures map[string][]StrategyExposure

	// Prometheus metrics
	symbolExposureGauge  *prometheus.GaugeVec
	totalExposureGauge   prometheus.Gauge
	entriesBlockedTotal  *prometheus.CounterVec
}

// NewPortfolioMonitor creates a new portfolio monitor with the specified limits.
func NewPortfolioMonitor(maxTotal, maxPerSymbol float64, enableCorrelatedCheck bool) *PortfolioMonitor {
	return &PortfolioMonitor{
		maxTotalPerpSpotExposure: maxTotal,
		maxPerSymbolExposure:     maxPerSymbol,
		enableCorrelatedCheck:    enableCorrelatedCheck,
		exposures:                make(map[string][]StrategyExposure),
		symbolExposureGauge:      nil, // Set via SetMetrics
		totalExposureGauge:       nil,
		entriesBlockedTotal:      nil,
	}
}

// SetMetrics attaches Prometheus metrics to the monitor.
func (pm *PortfolioMonitor) SetMetrics(symbolExposureGauge *prometheus.GaugeVec, totalExposureGauge prometheus.Gauge, entriesBlockedTotal *prometheus.CounterVec) {
	pm.mu.Lock()
	defer pm.mu.Unlock()
	pm.symbolExposureGauge = symbolExposureGauge
	pm.totalExposureGauge = totalExposureGauge
	pm.entriesBlockedTotal = entriesBlockedTotal
}

// CanEnter checks if a new position can be entered for the given symbol and notional.
// Returns true if entry allowed, false with reason if blocked.
func (pm *PortfolioMonitor) CanEnter(symbol string, notional float64, strategyType string) (bool, string) {
	pm.mu.Lock()
	defer pm.mu.Unlock()

	// Calculate current total exposure
	currentTotal := pm.getTotalExposureLocked()

	// Check 1: Total exposure limit
	if currentTotal+notional > pm.maxTotalPerpSpotExposure {
		reason := "total_exposure_limit"
		if pm.entriesBlockedTotal != nil {
			pm.entriesBlockedTotal.WithLabelValues(symbol, reason).Inc()
		}
		log.Warn().
			Str("symbol", symbol).
			Str("strategy", strategyType).
			Float64("notional", notional).
			Float64("current_total", currentTotal).
			Float64("max_total", pm.maxTotalPerpSpotExposure).
			Msg("portfolio monitor: entry blocked - total exposure limit")
		return false, reason
	}

	// Check 2: Per-symbol exposure limit
	symbolExposure := pm.getSymbolExposureLocked(symbol)
	if symbolExposure+notional > pm.maxPerSymbolExposure {
		reason := "symbol_exposure_limit"
		if pm.entriesBlockedTotal != nil {
			pm.entriesBlockedTotal.WithLabelValues(symbol, reason).Inc()
		}
		log.Warn().
			Str("symbol", symbol).
			Str("strategy", strategyType).
			Float64("notional", notional).
			Float64("symbol_exposure", symbolExposure).
			Float64("max_symbol", pm.maxPerSymbolExposure).
			Msg("portfolio monitor: entry blocked - symbol exposure limit")
		return false, reason
	}

	// Check 3: Correlated strategy check
	if pm.enableCorrelatedCheck && pm.isCorrelatedStrategy(strategyType) {
		if pm.hasCorrelatedExposureLocked(symbol, strategyType) {
			reason := "correlated_strategy_active"
			if pm.entriesBlockedTotal != nil {
				pm.entriesBlockedTotal.WithLabelValues(symbol, reason).Inc()
			}
			log.Warn().
				Str("symbol", symbol).
				Str("strategy", strategyType).
				Float64("notional", notional).
				Msg("portfolio monitor: entry blocked - correlated strategy already active")
			return false, reason
		}
	}

	return true, ""
}

// RegisterEntry registers a new position entry with the portfolio monitor.
// Called when any strategy enters a position.
func (pm *PortfolioMonitor) RegisterEntry(symbol string, notional float64, strategyType string, side string) {
	pm.mu.Lock()
	defer pm.mu.Unlock()

	exp := StrategyExposure{
		StrategyType: strategyType,
		Notional:     notional,
		Side:         side,
	}

	pm.exposures[symbol] = append(pm.exposures[symbol], exp)

	// Update metrics
	if pm.symbolExposureGauge != nil {
		pm.symbolExposureGauge.WithLabelValues(symbol).Set(pm.getSymbolExposureLocked(symbol))
	}
	if pm.totalExposureGauge != nil {
		pm.totalExposureGauge.Set(pm.getTotalExposureLocked())
	}

	log.Info().
		Str("symbol", symbol).
		Str("strategy", strategyType).
		Str("side", side).
		Float64("notional", notional).
		Float64("symbol_exposure", pm.getSymbolExposureLocked(symbol)).
		Float64("total_exposure", pm.getTotalExposureLocked()).
		Msg("portfolio monitor: registered entry")
}

// RegisterExit removes a position from the portfolio monitor.
// Called when any strategy exits a position.
func (pm *PortfolioMonitor) RegisterExit(symbol string, notional float64, strategyType string) {
	pm.mu.Lock()
	defer pm.mu.Unlock()

	symbolExposures, exists := pm.exposures[symbol]
	if !exists {
		log.Warn().
			Str("symbol", symbol).
			Str("strategy", strategyType).
			Msg("portfolio monitor: exit called for non-existent position")
		return
	}

	// Find and remove the matching exposure
	found := false
	for i, exp := range symbolExposures {
		if exp.StrategyType == strategyType {
			// Remove this entry by swapping with last and truncating
			symbolExposures[i] = symbolExposures[len(symbolExposures)-1]
			pm.exposures[symbol] = symbolExposures[:len(symbolExposures)-1]
			found = true
			break
		}
	}

	if !found {
		log.Warn().
			Str("symbol", symbol).
			Str("strategy", strategyType).
			Msg("portfolio monitor: no matching exposure found for exit")
		return
	}

	// Clean up empty symbol entries
	if len(pm.exposures[symbol]) == 0 {
		delete(pm.exposures, symbol)
	}

	// Update metrics
	if pm.symbolExposureGauge != nil {
		symbolTotal := pm.getSymbolExposureLocked(symbol)
		if symbolTotal == 0 {
			pm.symbolExposureGauge.DeleteLabelValues(symbol)
		} else {
			pm.symbolExposureGauge.WithLabelValues(symbol).Set(symbolTotal)
		}
	}
	if pm.totalExposureGauge != nil {
		pm.totalExposureGauge.Set(pm.getTotalExposureLocked())
	}

	log.Info().
		Str("symbol", symbol).
		Str("strategy", strategyType).
		Float64("notional", notional).
		Float64("symbol_exposure", pm.getSymbolExposureLocked(symbol)).
		Float64("total_exposure", pm.getTotalExposureLocked()).
		Msg("portfolio monitor: registered exit")
}

// GetExposure returns the current total exposure for a symbol.
func (pm *PortfolioMonitor) GetExposure(symbol string) float64 {
	pm.mu.RLock()
	defer pm.mu.RUnlock()
	return pm.getSymbolExposureLocked(symbol)
}

// GetTotalExposure returns the current total exposure across all symbols.
func (pm *PortfolioMonitor) GetTotalExposure() float64 {
	pm.mu.RLock()
	defer pm.mu.RUnlock()
	return pm.getTotalExposureLocked()
}

// GetExposureByStrategy returns the exposure breakdown for a symbol by strategy.
func (pm *PortfolioMonitor) GetExposureByStrategy(symbol string) map[string]float64 {
	pm.mu.RLock()
	defer pm.mu.RUnlock()

	result := make(map[string]float64)
	for _, exp := range pm.exposures[symbol] {
		result[exp.StrategyType] += exp.Notional
	}
	return result
}

// GetAllExposures returns a copy of all exposures.
func (pm *PortfolioMonitor) GetAllExposures() map[string][]StrategyExposure {
	pm.mu.RLock()
	defer pm.mu.RUnlock()

	result := make(map[string][]StrategyExposure, len(pm.exposures))
	for symbol, exposures := range pm.exposures {
		result[symbol] = make([]StrategyExposure, len(exposures))
		copy(result[symbol], exposures)
	}
	return result
}

// getTotalExposureLocked returns total exposure across all symbols.
// Must be called with lock held.
func (pm *PortfolioMonitor) getTotalExposureLocked() float64 {
	total := 0.0
	for _, symbolExposures := range pm.exposures {
		for _, exp := range symbolExposures {
			total += exp.Notional
		}
	}
	return total
}

// getSymbolExposureLocked returns total exposure for a symbol.
// Must be called with lock held.
func (pm *PortfolioMonitor) getSymbolExposureLocked(symbol string) float64 {
	total := 0.0
	for _, exp := range pm.exposures[symbol] {
		total += exp.Notional
	}
	return total
}

// isCorrelatedStrategy returns true if the strategy type is correlated with others.
// Currently, funding_arb and basis_trade both enter LONG spot + SHORT perp structures.
func (pm *PortfolioMonitor) isCorrelatedStrategy(strategyType string) bool {
	switch strategyType {
	case "funding_arb", "basis_trade":
		return true
	default:
		return false
	}
}

// hasCorrelatedExposureLocked checks if a correlated strategy already has exposure on this symbol.
// Must be called with lock held.
func (pm *PortfolioMonitor) hasCorrelatedExposureLocked(symbol string, strategyType string) bool {
	for _, exp := range pm.exposures[symbol] {
		// Check if there's an exposure from a DIFFERENT but correlated strategy
		if exp.StrategyType != strategyType && pm.isCorrelatedStrategy(exp.StrategyType) {
			return true
		}
	}
	return false
}

// String returns a human-readable summary of current exposures.
func (pm *PortfolioMonitor) String() string {
	pm.mu.RLock()
	defer pm.mu.RUnlock()

	if len(pm.exposures) == 0 {
		return "PortfolioMonitor: no active exposures"
	}

	result := fmt.Sprintf("PortfolioMonitor: total=$%.2f/%v, symbols=%d [",
		pm.getTotalExposureLocked(),
		pm.maxTotalPerpSpotExposure,
		len(pm.exposures))

	first := true
	for symbol, exposures := range pm.exposures {
		if !first {
			result += ", "
		}
		first = false
		symbolTotal := 0.0
		for _, exp := range exposures {
			symbolTotal += exp.Notional
		}
		result += fmt.Sprintf("%s:$%.2f", symbol, symbolTotal)
	}
	result += "]"
	return result
}
