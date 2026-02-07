package features

import (
	"math"
	"time"

	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/sentiment"
)

// FeatureVector represents all features for a single bar.
// The field order and ToArray() output MUST match FEATURE_COLUMNS in
// scripts/build_features.py so that the ONNX model receives features in
// the same order it was trained on.
type FeatureVector struct {
	Symbol    string
	Timestamp time.Time

	// Raw OHLCV
	Open   float64
	High   float64
	Low    float64
	Close  float64
	Volume float64

	// --- Model features (23 total, order matters) ---
	// 1. close (raw)
	// 2-3. log returns
	LogReturn1m float64
	LogReturn5m float64
	// 4-7. EMAs
	EMA5  float64
	EMA9  float64
	EMA21 float64
	EMA50 float64
	// 8-9. RSI
	RSI7  float64
	RSI14 float64
	// 10-13. Bollinger bands
	BBandUpper  float64
	BBandMiddle float64
	BBandLower  float64
	BBWidth     float64
	// 14-16. MACD
	MACD       float64
	MACDSignal float64
	MACDHist   float64
	// 17. Volume ratio
	VolumeRatio float64
	// 18-21. Sentiment
	SentimentScore1h  float64
	SentimentScore24h float64
	MentionsZScore    float64
	SentimentVelocity float64
	// 22-23. Time-of-day encoding
	HourSin float64
	HourCos float64
}

// ToArray converts the feature vector to a float64 slice for model input.
// The order MUST match scripts/build_features.py FEATURE_COLUMNS exactly:
//
//	close, log_ret_1m, log_ret_5m, ema_5, ema_9, ema_21, ema_50,
//	rsi_7, rsi_14, bb_upper, bb_middle, bb_lower, bb_width,
//	macd, macd_signal, macd_histogram, volume_ratio,
//	sentiment_1h, sentiment_24h, mentions_zscore, sentiment_velocity,
//	hour_sin, hour_cos
func (fv *FeatureVector) ToArray() []float64 {
	return []float64{
		fv.Close,
		fv.LogReturn1m,
		fv.LogReturn5m,
		fv.EMA5,
		fv.EMA9,
		fv.EMA21,
		fv.EMA50,
		fv.RSI7,
		fv.RSI14,
		fv.BBandUpper,
		fv.BBandMiddle,
		fv.BBandLower,
		fv.BBWidth,
		fv.MACD,
		fv.MACDSignal,
		fv.MACDHist,
		fv.VolumeRatio,
		fv.SentimentScore1h,
		fv.SentimentScore24h,
		fv.MentionsZScore,
		fv.SentimentVelocity,
		fv.HourSin,
		fv.HourCos,
	}
}

// ToSlice is an alias for ToArray for compatibility.
func (fv *FeatureVector) ToSlice() []float64 {
	return fv.ToArray()
}

// FeatureNames returns the ordered list of feature names matching the
// Python training script's FEATURE_COLUMNS.  The Go predictor uses
// len(FeatureNames()) to size the ONNX input tensor.
func FeatureNames() []string {
	return []string{
		"close",
		"log_ret_1m",
		"log_ret_5m",
		"ema_5",
		"ema_9",
		"ema_21",
		"ema_50",
		"rsi_7",
		"rsi_14",
		"bb_upper",
		"bb_middle",
		"bb_lower",
		"bb_width",
		"macd",
		"macd_signal",
		"macd_histogram",
		"volume_ratio",
		"sentiment_1h",
		"sentiment_24h",
		"mentions_zscore",
		"sentiment_velocity",
		"hour_sin",
		"hour_cos",
	}
}

// Builder computes a FeatureVector from raw candles + sentiment data.
// It delegates to the indicator functions in indicators.go (EMA, RSI,
// Bollinger, CalcMACD, LogReturn, VolumeRatio) which are correct
// implementations that operate on []exchange.Candle.
type Builder struct {
	minCandles int
}

// NewFeatureBuilder creates a new feature builder.
func NewFeatureBuilder() *Builder {
	// We need at least 50 candles to compute the slowest indicator
	// (EMA-50) plus a small warm-up margin.
	return &Builder{minCandles: 55}
}

// MinCandles returns the minimum number of candles required before
// features can be computed.
func (b *Builder) MinCandles() int {
	return b.minCandles
}

// Build computes a FeatureVector from the latest candle in the slice.
// Returns nil when there are not enough candles for indicator warm-up.
//
// Parameters:
//   - candles: time-sorted []exchange.Candle (oldest first).
//   - sent:    latest sentiment data for the symbol (may be nil).
func (b *Builder) Build(candles []exchange.Candle, sent *sentiment.SentimentData) *FeatureVector {
	if len(candles) < b.minCandles {
		return nil
	}

	last := candles[len(candles)-1]

	fv := &FeatureVector{
		Symbol:    last.Symbol,
		Timestamp: last.CloseTime,
		Open:      last.Open,
		High:      last.High,
		Low:       last.Low,
		Close:     last.Close,
		Volume:    last.Volume,
	}

	// ---- Log returns (actual log, matching Python np.log(c/c.shift)) ----
	logRet1 := LogReturn(candles, 1)
	if logRet1 != nil {
		fv.LogReturn1m = logRet1[len(logRet1)-1]
	}
	logRet5 := LogReturn(candles, 5)
	if logRet5 != nil {
		fv.LogReturn5m = logRet5[len(logRet5)-1]
	}

	// ---- EMAs ----
	if ema5 := EMA(candles, 5); ema5 != nil {
		fv.EMA5 = ema5[len(ema5)-1]
	}
	if ema9 := EMA(candles, 9); ema9 != nil {
		fv.EMA9 = ema9[len(ema9)-1]
	}
	if ema21 := EMA(candles, 21); ema21 != nil {
		fv.EMA21 = ema21[len(ema21)-1]
	}
	if ema50 := EMA(candles, 50); ema50 != nil {
		fv.EMA50 = ema50[len(ema50)-1]
	}

	// ---- RSI ----
	if rsi7 := RSI(candles, 7); rsi7 != nil {
		fv.RSI7 = rsi7[len(rsi7)-1]
	}
	if rsi14 := RSI(candles, 14); rsi14 != nil {
		fv.RSI14 = rsi14[len(rsi14)-1]
	}

	// ---- Bollinger Bands (20, 2) ----
	if bb := Bollinger(candles, 20, 2.0); bb != nil {
		idx := len(bb.Upper) - 1
		fv.BBandUpper = bb.Upper[idx]
		fv.BBandMiddle = bb.Middle[idx]
		fv.BBandLower = bb.Lower[idx]
		if fv.BBandMiddle > 0 {
			fv.BBWidth = (fv.BBandUpper - fv.BBandLower) / fv.BBandMiddle
		}
	}

	// ---- MACD (12, 26, 9) ----
	if macd := CalcMACD(candles, 12, 26, 9); macd != nil {
		idx := len(macd.MACD) - 1
		fv.MACD = macd.MACD[idx]
		fv.MACDSignal = macd.Signal[idx]
		fv.MACDHist = macd.Histogram[idx]
	}

	// ---- Volume ratio ----
	if vr := VolumeRatio(candles, 20); vr != nil {
		fv.VolumeRatio = vr[len(vr)-1]
	}

	// ---- Sentiment ----
	if sent != nil {
		fv.SentimentScore1h = sent.Score1h
		fv.SentimentScore24h = sent.Score24h
		fv.MentionsZScore = sent.MentionsZScore
		fv.SentimentVelocity = sent.Velocity
	}

	// ---- Time-of-day encoding ----
	hour := float64(last.CloseTime.Hour()) + float64(last.CloseTime.Minute())/60.0
	fv.HourSin = math.Sin(2 * math.Pi * hour / 24.0)
	fv.HourCos = math.Cos(2 * math.Pi * hour / 24.0)

	return fv
}
