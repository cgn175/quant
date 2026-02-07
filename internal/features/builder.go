package features

import (
	"math"
	"time"
)

// FeatureVector represents all features for a single bar
type FeatureVector struct {
	Symbol           string
	Timestamp        time.Time
	Open             float64
	High             float64
	Low              float64
	Close            float64
	Volume           float64
	VolumeRatio      float64 // Current volume / rolling average volume
	LogReturn1m      float64
	LogReturn5m      float64
	EMA5             float64
	EMA9             float64
	EMA21            float64
	EMA50            float64
	RSI7             float64
	RSI14            float64
	BBandUpper       float64 // Bollinger Band upper
	BBandLower       float64 // Bollinger Band lower
	BBandMiddle      float64
	BBWidth          float64 // Bollinger Band width (upper - lower)
	MACD             float64
	MACDSignal       float64
	MACDHist         float64
	SentimentScore1h  float64
	SentimentScore24h float64
	MentionsZScore    float64
	SentimentVelocity float64
}

// ToArray converts the feature vector to a float64 array for model input
func (fv *FeatureVector) ToArray() []float64 {
	return []float64{
		fv.LogReturn1m,
		fv.LogReturn5m,
		fv.EMA5,
		fv.EMA9,
		fv.EMA21,
		fv.EMA50,
		fv.RSI7,
		fv.RSI14,
		fv.BBandUpper,
		fv.BBandLower,
		fv.BBandMiddle,
		fv.MACD,
		fv.MACDSignal,
		fv.MACDHist,
		fv.VolumeRatio,
		fv.SentimentScore1h,
		fv.SentimentScore24h,
		fv.MentionsZScore,
		fv.SentimentVelocity,
	}
}

// ToSlice is an alias for ToArray for compatibility
func (fv *FeatureVector) ToSlice() []float64 {
	return fv.ToArray()
}

// Builder computes features for a bar
type Builder struct {
	// Buffers for rolling indicators
	closes      map[string][]float64 // Rolling price history
	volumes     map[string][]float64 // Rolling volume history
	maxBufferLen int
}

// NewBuilder creates a new feature builder
func NewBuilder(bufferLen int) *Builder {
	if bufferLen < 100 {
		bufferLen = 100 // Minimum to compute indicators
	}
	return &Builder{
		closes:       make(map[string][]float64),
		volumes:      make(map[string][]float64),
		maxBufferLen: bufferLen,
	}
}

// NewFeatureBuilder creates a new feature builder with default buffer size
func NewFeatureBuilder() *Builder {
	return NewBuilder(200)
}

// FeatureNames returns the names of all features in order
func FeatureNames() []string {
	return []string{
		"log_return_1m",
		"log_return_5m",
		"ema_5",
		"ema_9",
		"ema_21",
		"ema_50",
		"rsi_7",
		"rsi_14",
		"bband_upper",
		"bband_lower",
		"bband_middle",
		"macd",
		"macd_signal",
		"macd_hist",
		"volume_ratio",
		"sentiment_score_1h",
		"sentiment_score_24h",
		"mentions_zscore",
		"sentiment_velocity",
	}
}

// MinCandles returns minimum number of candles needed before building features
func (b *Builder) MinCandles() int {
	return 50 // Minimum for 50-period indicators
}

// Build computes a feature vector from candles and sentiment data
// Returns nil if there aren't enough candles yet
func (b *Builder) Build(candles interface{}, sentimentData interface{}) *FeatureVector {
	// Handle different input types - expect []Candle from exchange package
	candleList, ok := candles.([]interface{})
	if !ok {
		return nil
	}
	
	if len(candleList) < b.MinCandles() {
		return nil
	}
	
	// Build feature vector from latest candle
	// This would be filled in with actual implementation using exchange.Candle type
	// For now, return a placeholder
	return &FeatureVector{
		Timestamp: time.Now(),
		Close: 0,
		EMA21: 0,
		EMA50: 0,
		RSI14: 0,
		BBandUpper: 0,
		BBandLower: 0,
		BBandMiddle: 0,
		BBWidth: 0,
		SentimentScore1h: 0,
		SentimentScore24h: 0,
	}
}

// BuildFromRaw computes a feature vector for the current bar (internal use)
func (b *Builder) BuildFromRaw(symbol string, close, high, low, open, volume float64, 
	sentiment1h, sentiment24h float64) *FeatureVector {
	
	// Add to rolling buffers
	if b.closes[symbol] == nil {
		b.closes[symbol] = make([]float64, 0, b.maxBufferLen)
		b.volumes[symbol] = make([]float64, 0, b.maxBufferLen)
	}

	b.closes[symbol] = append(b.closes[symbol], close)
	b.volumes[symbol] = append(b.volumes[symbol], volume)

	// Trim buffers if too long
	if len(b.closes[symbol]) > b.maxBufferLen {
		b.closes[symbol] = b.closes[symbol][1:]
		b.volumes[symbol] = b.volumes[symbol][1:]
	}

	closes := b.closes[symbol]
	volumes := b.volumes[symbol]

	fv := &FeatureVector{
		Symbol:            symbol,
		Timestamp:         time.Now(),
		Open:              open,
		High:              high,
		Low:               low,
		Close:             close,
		Volume:            volume,
		SentimentScore1h:  sentiment1h,
		SentimentScore24h: sentiment24h,
	}

	// Compute log returns
	if len(closes) >= 2 {
		fv.LogReturn1m = logReturn(closes[len(closes)-2], close)
	}
	if len(closes) >= 6 {
		fv.LogReturn5m = logReturn(closes[len(closes)-6], close)
	}

	// Compute EMAs
	if len(closes) >= 5 {
		fv.EMA5 = ema(closes, 5)
	}
	if len(closes) >= 9 {
		fv.EMA9 = ema(closes, 9)
	}
	if len(closes) >= 21 {
		fv.EMA21 = ema(closes, 21)
	}
	if len(closes) >= 50 {
		fv.EMA50 = ema(closes, 50)
	}

	// Compute RSI
	if len(closes) >= 7 {
		fv.RSI7 = rsi(closes, 7)
	}
	if len(closes) >= 14 {
		fv.RSI14 = rsi(closes, 14)
	}

	// Compute volume ratio
	if len(volumes) >= 20 {
		avgVol := average(volumes[len(volumes)-20:])
		if avgVol > 0 {
			fv.VolumeRatio = volume / avgVol
		}
	}

	// Compute Bollinger Bands
	if len(closes) >= 20 {
		fv.BBandMiddle = sma(closes[len(closes)-20:], 20)
		stddev := std(closes[len(closes)-20:])
		fv.BBandUpper = fv.BBandMiddle + 2*stddev
		fv.BBandLower = fv.BBandMiddle - 2*stddev
		fv.BBWidth = fv.BBandUpper - fv.BBandLower
	}

	// Compute MACD
	if len(closes) >= 26 {
		ema12 := ema(closes, 12)
		ema26 := ema(closes, 26)
		fv.MACD = ema12 - ema26
		// Signal is 9-period EMA of MACD (simplified)
		fv.MACDSignal = fv.MACD * 0.65 // approximation
		fv.MACDHist = fv.MACD - fv.MACDSignal
	}

	return fv
}

// Helper functions for indicator computation

func logReturn(prev, curr float64) float64 {
	if prev <= 0 {
		return 0
	}
	return (curr - prev) / prev
}

func sma(values []float64, period int) float64 {
	if len(values) < period {
		return 0
	}
	sum := 0.0
	for i := len(values) - period; i < len(values); i++ {
		sum += values[i]
	}
	return sum / float64(period)
}

func ema(values []float64, period int) float64 {
	if len(values) < period {
		return 0
	}

	multiplier := 2.0 / float64(period+1)
	sma := sma(values[:period], period)
	ema := sma

	for i := period; i < len(values); i++ {
		ema = values[i]*multiplier + ema*(1-multiplier)
	}
	return ema
}

func rsi(values []float64, period int) float64 {
	if len(values) < period+1 {
		return 50
	}

	gains := 0.0
	losses := 0.0

	for i := len(values) - period; i < len(values); i++ {
		change := values[i] - values[i-1]
		if change > 0 {
			gains += change
		} else {
			losses -= change
		}
	}

	avgGain := gains / float64(period)
	avgLoss := losses / float64(period)

	if avgLoss == 0 {
		return 100
	}

	rs := avgGain / avgLoss
	return 100 - (100 / (1 + rs))
}

func average(values []float64) float64 {
	if len(values) == 0 {
		return 0
	}
	sum := 0.0
	for _, v := range values {
		sum += v
	}
	return sum / float64(len(values))
}

func std(values []float64) float64 {
	if len(values) == 0 {
		return 0
	}
	avg := average(values)
	sumSquares := 0.0
	for _, v := range values {
		diff := v - avg
		sumSquares += diff * diff
	}
	variance := sumSquares / float64(len(values))
	return math.Sqrt(variance)
}
