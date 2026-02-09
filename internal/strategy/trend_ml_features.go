package strategy

import (
	"math"

	"github.com/cgn175/quant-bot/internal/data"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/features"
)

func BuildMLFeatures(
	candles []exchange.Candle,
	fundingCache *data.FundingCache,
	symbol string,
	idx int,
	cfg TrendConfig,
) map[string]float64 {
	m := make(map[string]float64, 19)
	close := candles[idx].Close

	// returns_1bar
	if idx >= 1 && candles[idx-1].Close > 0 {
		m["returns_1bar"] = math.Log(close / candles[idx-1].Close)
	}

	// returns_4bar
	if idx >= 4 && candles[idx-4].Close > 0 {
		m["returns_4bar"] = math.Log(close / candles[idx-4].Close)
	}

	// returns_20bar
	if idx >= 20 && candles[idx-20].Close > 0 {
		m["returns_20bar"] = math.Log(close / candles[idx-20].Close)
	}

	// volatility_20: rolling std of log returns over 20 bars
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

	// rsi_14
	rsiVals := features.RSI(candles, 14)
	if rsiVals != nil && idx < len(rsiVals) {
		m["rsi_14"] = rsiVals[idx]
	}

	// bb_width_20
	bbw := features.BollingerBandwidth(candles, 20, 2.0)
	if bbw != nil && idx < len(bbw) {
		m["bb_width_20"] = bbw[idx]
	}

	// adx_14
	adxVals := features.ADX(candles, 14)
	if adxVals != nil && idx < len(adxVals) {
		m["adx_14"] = adxVals[idx]
	}

	// ema_9_distance
	ema9 := features.EMA(candles, 9)
	if ema9 != nil && idx < len(ema9) && ema9[idx] > 0 {
		m["ema_9_distance"] = close/ema9[idx] - 1
	}

	// ema_50_distance
	ema50 := features.EMA(candles, 50)
	if ema50 != nil && idx < len(ema50) && ema50[idx] > 0 {
		m["ema_50_distance"] = close/ema50[idx] - 1
	}

	// volume_ratio_20
	vr := features.VolumeRatio(candles, 20)
	if vr != nil && idx < len(vr) {
		m["volume_ratio_20"] = vr[idx]
	}

	// funding rates
	if fundingCache != nil {
		m["funding_8h_avg"] = fundingCache.MovingAverage(symbol, 2)
		m["funding_24h_avg"] = fundingCache.MovingAverage(symbol, 6)
	}

	// hour_sin / hour_cos
	t := candles[idx].OpenTime
	hour := float64(t.Hour()) + float64(t.Minute())/60.0
	m["hour_sin"] = math.Sin(2 * math.Pi * hour / 24.0)
	m["hour_cos"] = math.Cos(2 * math.Pi * hour / 24.0)

	// dow_sin / dow_cos
	dow := float64(t.Weekday())
	m["dow_sin"] = math.Sin(2 * math.Pi * dow / 7.0)
	m["dow_cos"] = math.Cos(2 * math.Pi * dow / 7.0)

	// atr_14
	atr14 := features.ATR(candles, 14)
	if atr14 != nil && idx < len(atr14) {
		m["atr_14"] = atr14[idx]
	}

	// atr_ratio: ATR(14) / ATR(50)
	atr50 := features.ATR(candles, 50)
	if atr14 != nil && atr50 != nil && idx < len(atr14) && idx < len(atr50) && atr50[idx] > 0 {
		m["atr_ratio"] = atr14[idx] / atr50[idx]
	}

	// donchian_breakout: 1 if close > DonchianUpper, -1 if close < DonchianLower, else 0
	dcUpper := features.DonchianUpper(candles, cfg.DonchianPeriod)
	dcLower := features.DonchianLower(candles, cfg.DonchianPeriod)
	if dcUpper != nil && dcLower != nil && idx < len(dcUpper) && idx < len(dcLower) {
		if close > dcUpper[idx] {
			m["donchian_breakout"] = 1
		} else if close < dcLower[idx] {
			m["donchian_breakout"] = -1
		} else {
			m["donchian_breakout"] = 0
		}
	}

	return m
}
