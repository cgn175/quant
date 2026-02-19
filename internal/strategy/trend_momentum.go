package strategy

import (
	"math"
	"sort"

	"github.com/cgn175/quant-bot/internal/exchange"
)

// MomentumScore represents a symbol's momentum ranking
type MomentumScore struct {
	Symbol string
	Score  float64
	Rank   int
}

// CalculateMomentumScores calculates volatility-adjusted momentum using provided candles.
// decayFactor controls exponential decay weighting (0 < decay <= 1). When decay == 0 or 1,
// simple equal-weight returns are used. A value like 0.94 gives ~50% weight reduction at 10 days.
func CalculateMomentumScores(symbols []string, candlesMap map[string][]exchange.Candle, lookbackDays int, decayFactor float64) []MomentumScore {
	if lookbackDays == 0 {
		lookbackDays = 21 // default 3 weeks
	}

	scores := make([]MomentumScore, 0, len(symbols))

	for _, symbol := range symbols {
		candles, ok := candlesMap[symbol]
		if !ok || len(candles) < lookbackDays*6 {
			scores = append(scores, MomentumScore{Symbol: symbol, Score: 0.0})
			continue
		}

		// Use last N days of candles
		numCandles := lookbackDays * 6 // 4H candles, 6 per day
		recent := candles[len(candles)-numCandles:]

		// Calculate weighted returns
		returns := calcWeightedReturns(recent, decayFactor)

		// Calculate volatility
		volatility := calculateVolatility(recent)
		if volatility == 0 {
			scores = append(scores, MomentumScore{Symbol: symbol, Score: 0.0})
			continue
		}

		// Volatility-adjusted momentum
		score := returns / volatility
		scores = append(scores, MomentumScore{Symbol: symbol, Score: score})
	}

	// Sort by score descending
	sort.Slice(scores, func(i, j int) bool {
		return scores[i].Score > scores[j].Score
	})

	// Assign ranks
	for i := range scores {
		scores[i].Rank = i + 1
	}

	return scores
}

// calcWeightedReturns calculates the exponentially decay-weighted cumulative return.
// Each candle-to-candle return is weighted by decay^(n-1-i) where i=0 is the oldest
// return and i=n-1 is the newest. Weights are normalized to sum to 1.
// When decayFactor is 0 or 1, falls back to simple total return.
func calcWeightedReturns(candles []exchange.Candle, decayFactor float64) float64 {
	if len(candles) < 2 {
		return 0.0
	}

	// Fall back to simple return when decay is disabled
	if decayFactor <= 0 || decayFactor >= 1 {
		return (candles[len(candles)-1].Close / candles[0].Close) - 1.0
	}

	n := len(candles) - 1 // number of returns

	// Compute weights: newest return gets highest weight
	weights := make([]float64, n)
	sumW := 0.0
	for i := 0; i < n; i++ {
		w := math.Pow(decayFactor, float64(n-1-i))
		weights[i] = w
		sumW += w
	}

	// Weighted sum of per-candle returns
	weightedReturn := 0.0
	for i := 0; i < n; i++ {
		r := (candles[i+1].Close / candles[i].Close) - 1.0
		weightedReturn += (weights[i] / sumW) * r
	}

	// Scale by number of returns so the magnitude is comparable to total return
	return weightedReturn * float64(n)
}

// calculateVolatility calculates standard deviation of returns
func calculateVolatility(candles []exchange.Candle) float64 {
	if len(candles) < 2 {
		return 0.0
	}

	// Calculate returns
	returns := make([]float64, len(candles)-1)
	for i := 1; i < len(candles); i++ {
		returns[i-1] = (candles[i].Close / candles[i-1].Close) - 1.0
	}

	// Calculate mean
	sum := 0.0
	for _, r := range returns {
		sum += r
	}
	mean := sum / float64(len(returns))

	// Calculate variance
	variance := 0.0
	for _, r := range returns {
		diff := r - mean
		variance += diff * diff
	}
	variance /= float64(len(returns))

	// Return standard deviation
	return math.Sqrt(variance)
}

// IsTopMomentum checks if symbol is in top N% by momentum
func (ts *TrendStrategy) IsTopMomentum(symbol string, symbols []string, candlesMap map[string][]exchange.Candle) bool {
	if !ts.config.MomentumFilter.Enabled {
		return true // filter disabled, allow all
	}

	scores := CalculateMomentumScores(
		symbols,
		candlesMap,
		ts.config.MomentumFilter.LookbackDays,
		ts.config.MomentumFilter.DecayFactor,
	)

	topPct := ts.config.MomentumFilter.TopPct
	if topPct == 0 {
		topPct = 0.5 // default top 50%
	}

	topN := int(float64(len(scores)) * topPct)
	if topN < 1 {
		topN = 1 // always trade at least 1 symbol
	}

	// Check if symbol is in top N
	for i := 0; i < topN; i++ {
		if scores[i].Symbol == symbol {
			return true
		}
	}

	return false
}

// GetMomentumRank returns the momentum rank for a symbol (1 = highest)
func (ts *TrendStrategy) GetMomentumRank(symbol string, symbols []string, candlesMap map[string][]exchange.Candle) int {
	scores := CalculateMomentumScores(
		symbols,
		candlesMap,
		ts.config.MomentumFilter.LookbackDays,
		ts.config.MomentumFilter.DecayFactor,
	)

	for _, s := range scores {
		if s.Symbol == symbol {
			return s.Rank
		}
	}
	return len(scores) // worst rank if not found
}
