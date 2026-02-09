package strategy

import (
	"math"

	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/features"
)

// BuildVolatilityFeatures computes the 6 features needed by the Volatility
// Predictor (Dynamic Stop-Loss). Feature names must match
// ml/volatility/features_vol_v1.py exactly.
//
// Features: range_1, range_sma_6, atrp_14, volume_ratio_20, hour_sin, hour_cos
func BuildVolatilityFeatures(
	candles []exchange.Candle,
	idx int,
) map[string]float64 {
	m := make(map[string]float64, 6)

	close := candles[idx].Close
	if close <= 0 {
		return m
	}

	// --- range_1: (high - low) / close of current candle ---
	m["range_1"] = (candles[idx].High - candles[idx].Low) / close

	// --- range_sma_6: SMA of range_1 over 6 bars ---
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

	// --- atrp_14: ATR(14) / close ---
	atr14 := features.ATR(candles, 14)
	if atr14 != nil && idx < len(atr14) && close > 0 {
		m["atrp_14"] = atr14[idx] / close
	}

	// --- volume_ratio_20 ---
	vr := features.VolumeRatio(candles, 20)
	if vr != nil && idx < len(vr) {
		m["volume_ratio_20"] = vr[idx]
	}

	// --- hour_sin / hour_cos ---
	t := candles[idx].OpenTime
	hour := float64(t.Hour()) + float64(t.Minute())/60.0
	m["hour_sin"] = math.Sin(2 * math.Pi * hour / 24.0)
	m["hour_cos"] = math.Cos(2 * math.Pi * hour / 24.0)

	return m
}
