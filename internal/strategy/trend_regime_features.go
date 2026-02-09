package strategy

import (
	"math"

	"github.com/cgn175/quant-bot/internal/data"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/features"
)

// BuildRegimeFeatures computes the 6 features needed by the Regime Classifier
// (Traffic Light). Feature names must match ml/regime/features_regime_v1.py exactly.
//
// Features: volatility_20, volume_ratio_20, rsi_14, hour_sin, hour_cos, funding_24h_avg
func BuildRegimeFeatures(
	candles []exchange.Candle,
	fundingCache *data.FundingCache,
	symbol string,
	idx int,
) map[string]float64 {
	m := make(map[string]float64, 6)

	// --- volatility_20: rolling std of log returns over 20 bars ---
	if idx >= 20 {
		var sum, sumSq float64
		count := 0
		for i := idx - 19; i <= idx; i++ {
			if i >= 1 && candles[i-1].Close > 0 && candles[i].Close > 0 {
				lr := math.Log(candles[i].Close / candles[i-1].Close)
				sum += lr
				sumSq += lr * lr
				count++
			}
		}
		if count > 1 {
			mean := sum / float64(count)
			variance := sumSq/float64(count) - mean*mean
			if variance > 0 {
				m["volatility_20"] = math.Sqrt(variance)
			}
		}
	}

	// --- volume_ratio_20 ---
	vr := features.VolumeRatio(candles, 20)
	if vr != nil && idx < len(vr) {
		m["volume_ratio_20"] = vr[idx]
	}

	// --- rsi_14 ---
	rsiVals := features.RSI(candles, 14)
	if rsiVals != nil && idx < len(rsiVals) {
		m["rsi_14"] = rsiVals[idx]
	}

	// --- hour_sin / hour_cos ---
	t := candles[idx].OpenTime
	hour := float64(t.Hour()) + float64(t.Minute())/60.0
	m["hour_sin"] = math.Sin(2 * math.Pi * hour / 24.0)
	m["hour_cos"] = math.Cos(2 * math.Pi * hour / 24.0)

	// --- funding_24h_avg ---
	if fundingCache != nil {
		m["funding_24h_avg"] = fundingCache.MovingAverage(symbol, 6)
	} else {
		m["funding_24h_avg"] = 0.0
	}

	return m
}
