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
