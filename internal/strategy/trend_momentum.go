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

// CalculateMomentumScores calculates volatility-adjusted momentum using provided candles
func CalculateMomentumScores(symbols []string, candlesMap map[string][]exchange.Candle, lookbackDays int) []MomentumScore {
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

		// Calculate returns
		priceStart := recent[0].Close
		priceEnd := recent[len(recent)-1].Close
		returns := (priceEnd / priceStart) - 1.0

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
	)

	for _, s := range scores {
		if s.Symbol == symbol {
			return s.Rank
		}
	}
	return len(scores) // worst rank if not found
}
