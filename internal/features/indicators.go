package features

import (
	"math"

	"github.com/cgn175/quant-bot/internal/exchange"
)

func EMA(candles []exchange.Candle, period int) []float64 {
	if len(candles) < period {
		return nil
	}

	ema := make([]float64, len(candles))
	multiplier := 2.0 / float64(period+1)

	sum := 0.0
	for i := 0; i < period; i++ {
		sum += candles[i].Close
	}
	ema[period-1] = sum / float64(period)

	for i := period; i < len(candles); i++ {
		ema[i] = (candles[i].Close-ema[i-1])*multiplier + ema[i-1]
	}

	return ema
}

func RSI(candles []exchange.Candle, period int) []float64 {
	if len(candles) < period+1 {
		return nil
	}

	rsi := make([]float64, len(candles))

	gains := make([]float64, len(candles))
	losses := make([]float64, len(candles))

	for i := 1; i < len(candles); i++ {
		change := candles[i].Close - candles[i-1].Close
		if change > 0 {
			gains[i] = change
		} else {
			losses[i] = -change
		}
	}

	avgGain := 0.0
	avgLoss := 0.0
	for i := 1; i <= period; i++ {
		avgGain += gains[i]
		avgLoss += losses[i]
	}
	avgGain /= float64(period)
	avgLoss /= float64(period)

	if avgLoss == 0 {
		rsi[period] = 100
	} else {
		rs := avgGain / avgLoss
		rsi[period] = 100 - (100 / (1 + rs))
	}

	for i := period + 1; i < len(candles); i++ {
		avgGain = (avgGain*float64(period-1) + gains[i]) / float64(period)
		avgLoss = (avgLoss*float64(period-1) + losses[i]) / float64(period)

		if avgLoss == 0 {
			rsi[i] = 100
		} else {
			rs := avgGain / avgLoss
			rsi[i] = 100 - (100 / (1 + rs))
		}
	}

	return rsi
}

type BollingerBands struct {
	Upper  []float64
	Middle []float64
	Lower  []float64
}

func Bollinger(candles []exchange.Candle, period int, stdDevMult float64) *BollingerBands {
	if len(candles) < period {
		return nil
	}

	bb := &BollingerBands{
		Upper:  make([]float64, len(candles)),
		Middle: make([]float64, len(candles)),
		Lower:  make([]float64, len(candles)),
	}

	for i := period - 1; i < len(candles); i++ {
		sum := 0.0
		for j := i - period + 1; j <= i; j++ {
			sum += candles[j].Close
		}
		sma := sum / float64(period)

		variance := 0.0
		for j := i - period + 1; j <= i; j++ {
			diff := candles[j].Close - sma
			variance += diff * diff
		}
		stdDev := math.Sqrt(variance / float64(period))

		bb.Middle[i] = sma
		bb.Upper[i] = sma + stdDevMult*stdDev
		bb.Lower[i] = sma - stdDevMult*stdDev
	}

	return bb
}

type MACD struct {
	MACD      []float64
	Signal    []float64
	Histogram []float64
}

func CalcMACD(candles []exchange.Candle, fastPeriod, slowPeriod, signalPeriod int) *MACD {
	if len(candles) < slowPeriod {
		return nil
	}

	fastEMA := EMA(candles, fastPeriod)
	slowEMA := EMA(candles, slowPeriod)

	macdLine := make([]float64, len(candles))
	for i := slowPeriod - 1; i < len(candles); i++ {
		macdLine[i] = fastEMA[i] - slowEMA[i]
	}

	signal := make([]float64, len(candles))
	multiplier := 2.0 / float64(signalPeriod+1)

	startIdx := slowPeriod - 1 + signalPeriod - 1
	if startIdx >= len(candles) {
		return nil
	}

	sum := 0.0
	for i := slowPeriod - 1; i < slowPeriod-1+signalPeriod; i++ {
		sum += macdLine[i]
	}
	signal[startIdx] = sum / float64(signalPeriod)

	for i := startIdx + 1; i < len(candles); i++ {
		signal[i] = (macdLine[i]-signal[i-1])*multiplier + signal[i-1]
	}

	histogram := make([]float64, len(candles))
	for i := startIdx; i < len(candles); i++ {
		histogram[i] = macdLine[i] - signal[i]
	}

	return &MACD{
		MACD:      macdLine,
		Signal:    signal,
		Histogram: histogram,
	}
}

// LogReturn computes the natural log return over `period` bars:
//
//	log_ret[i] = ln(close[i] / close[i-period])
//
// This matches Python's  np.log(df["close"] / df["close"].shift(period)).
func LogReturn(candles []exchange.Candle, period int) []float64 {
	if len(candles) < period+1 {
		return nil
	}

	returns := make([]float64, len(candles))
	for i := period; i < len(candles); i++ {
		prev := candles[i-period].Close
		curr := candles[i].Close
		if prev > 0 && curr > 0 {
			returns[i] = math.Log(curr / prev)
		}
	}

	return returns
}

func VolumeRatio(candles []exchange.Candle, period int) []float64 {
	if len(candles) < period {
		return nil
	}

	ratio := make([]float64, len(candles))

	for i := period - 1; i < len(candles); i++ {
		sum := 0.0
		for j := i - period + 1; j <= i; j++ {
			sum += candles[j].Volume
		}
		avgVol := sum / float64(period)

		if avgVol > 0 {
			ratio[i] = candles[i].Volume / avgVol
		}
	}

	return ratio
}

// SMA computes a simple moving average over `period` bars.
// This matches Python's df["close"].rolling(window=period).mean().
func SMA(candles []exchange.Candle, period int) []float64 {
	if len(candles) < period {
		return nil
	}

	sma := make([]float64, len(candles))

	// Compute first window sum
	sum := 0.0
	for i := 0; i < period; i++ {
		sum += candles[i].Close
	}
	sma[period-1] = sum / float64(period)

	// Slide the window
	for i := period; i < len(candles); i++ {
		sum += candles[i].Close - candles[i-period].Close
		sma[i] = sum / float64(period)
	}

	return sma
}

// VolumeSurge returns 1.0 if the current volume exceeds `mult` times
// the rolling `period`-bar average volume, 0.0 otherwise.
// This matches Python's:
//
//	(df["volume"] > df["volume"].rolling(window=100).mean() * 1.5).astype(int)
func VolumeSurge(candles []exchange.Candle, period int, mult float64) []float64 {
	if len(candles) < period {
		return nil
	}

	result := make([]float64, len(candles))

	// Compute first window sum
	sum := 0.0
	for i := 0; i < period; i++ {
		sum += candles[i].Volume
	}

	avgVol := sum / float64(period)
	if candles[period-1].Volume > avgVol*mult {
		result[period-1] = 1.0
	}

	// Slide the window
	for i := period; i < len(candles); i++ {
		sum += candles[i].Volume - candles[i-period].Volume
		avgVol = sum / float64(period)
		if avgVol > 0 && candles[i].Volume > avgVol*mult {
			result[i] = 1.0
		}
	}

	return result
}

// ATR computes the Average True Range over `period` bars.
// This matches Python's ta.volatility.average_true_range(high, low, close, window=period).
//
// True Range = max(high-low, |high-prev_close|, |low-prev_close|)
// ATR = Wilder's smoothed average of True Range.
func ATR(candles []exchange.Candle, period int) []float64 {
	if len(candles) < period+1 {
		return nil
	}

	atr := make([]float64, len(candles))

	// Compute true range for each bar (starting from index 1)
	tr := make([]float64, len(candles))
	for i := 1; i < len(candles); i++ {
		hl := candles[i].High - candles[i].Low
		hc := math.Abs(candles[i].High - candles[i-1].Close)
		lc := math.Abs(candles[i].Low - candles[i-1].Close)
		tr[i] = math.Max(hl, math.Max(hc, lc))
	}

	// First ATR is the simple average of the first `period` true ranges
	sum := 0.0
	for i := 1; i <= period; i++ {
		sum += tr[i]
	}
	atr[period] = sum / float64(period)

	// Wilder's smoothing: ATR[i] = (ATR[i-1] * (period-1) + TR[i]) / period
	for i := period + 1; i < len(candles); i++ {
		atr[i] = (atr[i-1]*float64(period-1) + tr[i]) / float64(period)
	}

	return atr
}

// ROC computes the Rate of Change (percentage change) over `period` bars.
// This matches Python's df["close"].pct_change(period).
//
//	roc[i] = (close[i] - close[i-period]) / close[i-period]
func ROC(candles []exchange.Candle, period int) []float64 {
	if len(candles) < period+1 {
		return nil
	}

	roc := make([]float64, len(candles))
	for i := period; i < len(candles); i++ {
		prev := candles[i-period].Close
		if prev > 0 {
			roc[i] = (candles[i].Close - prev) / prev
		}
	}

	return roc
}

// PriceVolumeDivergence computes:
//
//	(close.diff() * volume.diff()).rolling(window).sum()
//
// matching the Python implementation.
func PriceVolumeDivergence(candles []exchange.Candle, window int) []float64 {
	if len(candles) < window+1 {
		return nil
	}

	// Compute price_diff * volume_diff for each bar
	products := make([]float64, len(candles))
	for i := 1; i < len(candles); i++ {
		priceDiff := candles[i].Close - candles[i-1].Close
		volDiff := candles[i].Volume - candles[i-1].Volume
		products[i] = priceDiff * volDiff
	}

	// Rolling sum over `window` bars
	result := make([]float64, len(candles))
	for i := window; i < len(candles); i++ {
		sum := 0.0
		for j := i - window + 1; j <= i; j++ {
			sum += products[j]
		}
		result[i] = sum
	}

	return result
}

// ---------------------------------------------------------------------------
// Plan D: Trend Following Indicators
// ---------------------------------------------------------------------------

// DonchianUpper computes the rolling highest high over `period` bars,
// EXCLUDING the current bar (shifted by 1 to avoid lookahead).
//
//	result[i] = max(high[i-period], ..., high[i-1])
//
// The first `period` entries are 0.
func DonchianUpper(candles []exchange.Candle, period int) []float64 {
	if len(candles) < period+1 {
		return nil
	}

	result := make([]float64, len(candles))

	for i := period; i < len(candles); i++ {
		maxHigh := candles[i-period].High
		for j := i - period + 1; j < i; j++ {
			if candles[j].High > maxHigh {
				maxHigh = candles[j].High
			}
		}
		result[i] = maxHigh
	}

	return result
}

// DonchianLower computes the rolling lowest low over `period` bars,
// EXCLUDING the current bar (shifted by 1 to avoid lookahead).
//
//	result[i] = min(low[i-period], ..., low[i-1])
//
// The first `period` entries are 0.
func DonchianLower(candles []exchange.Candle, period int) []float64 {
	if len(candles) < period+1 {
		return nil
	}

	result := make([]float64, len(candles))

	for i := period; i < len(candles); i++ {
		minLow := candles[i-period].Low
		for j := i - period + 1; j < i; j++ {
			if candles[j].Low < minLow {
				minLow = candles[j].Low
			}
		}
		result[i] = minLow
	}

	return result
}

// HighestHigh computes the rolling maximum of High over `period` bars
// INCLUDING the current bar.
//
//	result[i] = max(high[i-period+1], ..., high[i])
//
// The first `period-1` entries are 0.
func HighestHigh(candles []exchange.Candle, period int) []float64 {
	if len(candles) < period {
		return nil
	}

	result := make([]float64, len(candles))

	for i := period - 1; i < len(candles); i++ {
		maxHigh := candles[i-period+1].High
		for j := i - period + 2; j <= i; j++ {
			if candles[j].High > maxHigh {
				maxHigh = candles[j].High
			}
		}
		result[i] = maxHigh
	}

	return result
}

// LowestLow computes the rolling minimum of Low over `period` bars
// INCLUDING the current bar.
//
//	result[i] = min(low[i-period+1], ..., low[i])
//
// The first `period-1` entries are 0.
func LowestLow(candles []exchange.Candle, period int) []float64 {
	if len(candles) < period {
		return nil
	}

	result := make([]float64, len(candles))

	for i := period - 1; i < len(candles); i++ {
		minLow := candles[i-period+1].Low
		for j := i - period + 2; j <= i; j++ {
			if candles[j].Low < minLow {
				minLow = candles[j].Low
			}
		}
		result[i] = minLow
	}

	return result
}

// ADX computes the Average Directional Index using Wilder's smoothing.
//
// Steps:
//  1. Compute +DM, -DM, and True Range
//  2. Smooth with Wilder's method (initial = SMA of first `period` values)
//  3. +DI = 100 * smoothed_+DM / smoothed_ATR
//  4. -DI = 100 * smoothed_-DM / smoothed_ATR
//  5. DX = 100 * |+DI - -DI| / (+DI + -DI)
//  6. ADX = Wilder-smoothed DX
//
// Valid values start at index 2*period. Earlier indices are 0.
func ADX(candles []exchange.Candle, period int) []float64 {
	n := len(candles)
	if n < 2*period+1 {
		return nil
	}

	result := make([]float64, n)

	// Step 1: raw +DM, -DM, TR (starting from index 1)
	plusDM := make([]float64, n)
	minusDM := make([]float64, n)
	tr := make([]float64, n)

	for i := 1; i < n; i++ {
		upMove := candles[i].High - candles[i-1].High
		downMove := candles[i-1].Low - candles[i].Low

		if upMove > downMove && upMove > 0 {
			plusDM[i] = upMove
		}
		if downMove > upMove && downMove > 0 {
			minusDM[i] = downMove
		}

		hl := candles[i].High - candles[i].Low
		hc := math.Abs(candles[i].High - candles[i-1].Close)
		lc := math.Abs(candles[i].Low - candles[i-1].Close)
		tr[i] = math.Max(hl, math.Max(hc, lc))
	}

	// Step 2: Wilder smoothing — initial = SMA of first `period` values (indices 1..period)
	smoothPlusDM := 0.0
	smoothMinusDM := 0.0
	smoothTR := 0.0
	for i := 1; i <= period; i++ {
		smoothPlusDM += plusDM[i]
		smoothMinusDM += minusDM[i]
		smoothTR += tr[i]
	}

	// DX values for ADX calculation
	dx := make([]float64, n)

	// Compute first DI and DX at index `period`
	if smoothTR > 0 {
		plusDI := 100.0 * smoothPlusDM / smoothTR
		minusDI := 100.0 * smoothMinusDM / smoothTR
		diSum := plusDI + minusDI
		if diSum > 0 {
			dx[period] = 100.0 * math.Abs(plusDI-minusDI) / diSum
		}
	}

	// Continue Wilder smoothing for remaining bars
	for i := period + 1; i < n; i++ {
		smoothPlusDM = smoothPlusDM - smoothPlusDM/float64(period) + plusDM[i]
		smoothMinusDM = smoothMinusDM - smoothMinusDM/float64(period) + minusDM[i]
		smoothTR = smoothTR - smoothTR/float64(period) + tr[i]

		if smoothTR > 0 {
			plusDI := 100.0 * smoothPlusDM / smoothTR
			minusDI := 100.0 * smoothMinusDM / smoothTR
			diSum := plusDI + minusDI
			if diSum > 0 {
				dx[i] = 100.0 * math.Abs(plusDI-minusDI) / diSum
			}
		}
	}

	// Step 6: ADX = Wilder-smoothed DX
	// Seed ADX with SMA of first `period` DX values (indices period .. 2*period-1)
	adxSum := 0.0
	for i := period; i < 2*period; i++ {
		adxSum += dx[i]
	}
	adxVal := adxSum / float64(period)
	result[2*period-1] = adxVal

	// Continue Wilder smoothing for ADX
	for i := 2 * period; i < n; i++ {
		adxVal = (adxVal*float64(period-1) + dx[i]) / float64(period)
		result[i] = adxVal
	}

	return result
}

// ChandelierExitLong computes the long trailing stop level:
//
//	result[i] = HighestHigh(lookback)[i] - atrMult * ATR(atrPeriod)[i]
//
// This is used for trailing stops on long positions.
func ChandelierExitLong(candles []exchange.Candle, atrPeriod int, atrMult float64, lookback int) []float64 {
	atrVals := ATR(candles, atrPeriod)
	hhVals := HighestHigh(candles, lookback)
	if atrVals == nil || hhVals == nil {
		return nil
	}

	n := len(candles)
	result := make([]float64, n)

	// Valid from max(atrPeriod, lookback-1) onwards
	startIdx := atrPeriod
	if lookback-1 > startIdx {
		startIdx = lookback - 1
	}

	for i := startIdx; i < n; i++ {
		if atrVals[i] > 0 && hhVals[i] > 0 {
			result[i] = hhVals[i] - atrMult*atrVals[i]
		}
	}

	return result
}

// ChandelierExitShort computes the short trailing stop level:
//
//	result[i] = LowestLow(lookback)[i] + atrMult * ATR(atrPeriod)[i]
//
// This is used for trailing stops on short positions.
func ChandelierExitShort(candles []exchange.Candle, atrPeriod int, atrMult float64, lookback int) []float64 {
	atrVals := ATR(candles, atrPeriod)
	llVals := LowestLow(candles, lookback)
	if atrVals == nil || llVals == nil {
		return nil
	}

	n := len(candles)
	result := make([]float64, n)

	startIdx := atrPeriod
	if lookback-1 > startIdx {
		startIdx = lookback - 1
	}

	for i := startIdx; i < n; i++ {
		if atrVals[i] > 0 && llVals[i] > 0 {
			result[i] = llVals[i] + atrMult*atrVals[i]
		}
	}

	return result
}

// ---------------------------------------------------------------------------
// Bollinger Bandwidth (Patch 1: Whipsaw Defense)
// ---------------------------------------------------------------------------

// BollingerBandwidth returns (upper - lower) / middle as a percentage for each bar.
// Used to detect "dead market" conditions where bandwidth is compressed.
func BollingerBandwidth(candles []exchange.Candle, period int, stdDevMult float64) []float64 {
	bb := Bollinger(candles, period, stdDevMult)
	if bb == nil {
		return nil
	}

	n := len(candles)
	result := make([]float64, n)

	for i := period - 1; i < n; i++ {
		if bb.Middle[i] > 0 {
			result[i] = (bb.Upper[i] - bb.Lower[i]) / bb.Middle[i]
		}
	}

	return result
}

// RollingQuantile returns the rolling quantile of values over a given window.
// quantile should be between 0 and 1 (e.g., 0.10 for 10th percentile).
func RollingQuantile(values []float64, window int, quantile float64) []float64 {
	n := len(values)
	if n < window || window < 1 {
		return nil
	}

	result := make([]float64, n)

	for i := window - 1; i < n; i++ {
		// Extract window values
		windowVals := make([]float64, window)
		copy(windowVals, values[i-window+1:i+1])

		// Sort window values
		sortFloat64s(windowVals)

		// Calculate quantile index
		idx := int(float64(window-1) * quantile)
		if idx < 0 {
			idx = 0
		}
		if idx >= window {
			idx = window - 1
		}
		result[i] = windowVals[idx]
	}

	return result
}

// sortFloat64s sorts a slice of float64 in ascending order (simple insertion sort).
func sortFloat64s(vals []float64) {
	for i := 1; i < len(vals); i++ {
		key := vals[i]
		j := i - 1
		for j >= 0 && vals[j] > key {
			vals[j+1] = vals[j]
			j--
		}
		vals[j+1] = key
	}
}
