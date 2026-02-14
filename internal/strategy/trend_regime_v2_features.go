package strategy

import (
	"github.com/cgn175/quant-bot/internal/data"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/features"
	"github.com/cgn175/quant-bot/internal/sentiment"
)

// BuildRegimeV2Features computes the 8 features needed by the Regime Classifier v2
// (Traffic Light v2). Feature names must match ml/regime/features_regime_v2.py exactly.
//
// Features (8 total):
//   - v1 original (6): volatility_20, volume_ratio_20, rsi_14, hour_sin, hour_cos, funding_24h_avg
//   - v2 new (2):      atrp_14, range_sma_6
func BuildRegimeV2Features(
	candles []exchange.Candle,
	fundingCache *data.FundingCache,
	symbol string,
	idx int,
	sent *sentiment.SentimentData,
) map[string]float64 {
	// Start with the v1 features
	m := BuildRegimeFeatures(candles, fundingCache, symbol, idx, sent)

	close := candles[idx].Close
	if close <= 0 {
		return m
	}

	// --- atrp_14: ATR(14) / close ---
	atr14 := features.ATR(candles, 14)
	if atr14 != nil && idx < len(atr14) {
		m["atrp_14"] = atr14[idx] / close
	}

	// --- range_sma_6: SMA of (high - low) / close over 6 bars ---
	if idx >= 5 {
		var rangeSum float64
		count := 0
		for i := idx - 5; i <= idx; i++ {
			if candles[i].Close > 0 {
				r := (candles[i].High - candles[i].Low) / candles[i].Close
				rangeSum += r
				count++
			}
		}
		if count > 0 {
			m["range_sma_6"] = rangeSum / float64(count)
		}
	}

	return m
}
