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

	// --- Model features (33 total, order matters) ---
	// 1. close (raw)
	// 2-3. log returns
	LogReturn1m float64
	LogReturn5m float64
	// 4-7. EMAs (base timeframe)
	EMA5  float64
	EMA9  float64
	EMA21 float64
	EMA50 float64
	// 8-11. Multi-timeframe EMAs
	EMA21_15m float64
	EMA50_15m float64
	EMA21_1h  float64
	EMA50_1h  float64
	// 12. Trend alignment
	TrendAligned float64
	// 13-14. RSI
	RSI7  float64
	RSI14 float64
	// 15-18. Bollinger bands
	BBandUpper  float64
	BBandMiddle float64
	BBandLower  float64
	BBWidth     float64
	// 19-21. MACD
	MACD       float64
	MACDSignal float64
	MACDHist   float64
	// 22-24. Volume features
	VolumeRatio  float64
	VolSurge     float64
	PVDivergence float64
	// 25-26. Time-of-day encoding
	HourSin float64
	HourCos float64
	// 27-29. Session indicators
	IsUSSession   float64
	IsAsiaSession float64
	IsWeekend     float64
	// 30-33. Sentiment
	SentimentScore1h  float64
	SentimentScore24h float64
	MentionsZScore    float64
	SentimentVelocity float64
}

// ToArray converts the feature vector to a float64 slice for model input.
// The order MUST match scripts/build_features.py FEATURE_COLUMNS exactly:
//
//	close, log_ret_1, log_ret_5, ema_5, ema_9, ema_21, ema_50,
//	ema_21_15m, ema_50_15m, ema_21_1h, ema_50_1h, trend_aligned,
//	rsi_7, rsi_14, bb_upper, bb_middle, bb_lower, bb_width,
//	macd, macd_signal, macd_histogram, volume_ratio, vol_surge, pv_divergence,
//	hour_sin, hour_cos, is_us_session, is_asia_session, is_weekend,
//	sentiment_1h, sentiment_24h, mentions_zscore, sentiment_velocity
func (fv *FeatureVector) ToArray() []float64 {
	return []float64{
		fv.Close,
		fv.LogReturn1m,
		fv.LogReturn5m,
		fv.EMA5,
		fv.EMA9,
		fv.EMA21,
		fv.EMA50,
		fv.EMA21_15m,
		fv.EMA50_15m,
		fv.EMA21_1h,
		fv.EMA50_1h,
		fv.TrendAligned,
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
		fv.VolSurge,
		fv.PVDivergence,
		fv.HourSin,
		fv.HourCos,
		fv.IsUSSession,
		fv.IsAsiaSession,
		fv.IsWeekend,
		fv.SentimentScore1h,
		fv.SentimentScore24h,
		fv.MentionsZScore,
		fv.SentimentVelocity,
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
		"log_ret_1",
		"log_ret_5",
		"ema_5",
		"ema_9",
		"ema_21",
		"ema_50",
		"ema_21_15m",
		"ema_50_15m",
		"ema_21_1h",
		"ema_50_1h",
		"trend_aligned",
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
		"vol_surge",
		"pv_divergence",
		"hour_sin",
		"hour_cos",
		"is_us_session",
		"is_asia_session",
		"is_weekend",
		"sentiment_1h",
		"sentiment_24h",
		"mentions_zscore",
		"sentiment_velocity",
	}
}

// Builder computes a FeatureVector from raw candles + sentiment data.
// It delegates to the indicator functions in indicators.go (EMA, RSI,
// Bollinger, CalcMACD, LogReturn, VolumeRatio) which are correct
// implementations that operate on []exchange.Candle.
type Builder struct {
	minCandles int
	// timeframeMultiplier controls multi-timeframe EMA window sizes.
	// For 5m base: 15m = 3x, 1h = 12x.
	mult15m int
	mult1h  int
}

// NewFeatureBuilder creates a new feature builder for 5m timeframe.
// For 5m bars we need enough candles for the slowest indicator:
// EMA-50 on 1h context = 50 * 12 = 600 bars of 5m data.
func NewFeatureBuilder() *Builder {
	return &Builder{
		minCandles: 610, // 50*12 + margin for 1h EMA warm-up
		mult15m:    3,
		mult1h:     12,
	}
}

// NewFeatureBuilderWithTimeframe creates a builder for a specific timeframe.
func NewFeatureBuilderWithTimeframe(timeframe string) *Builder {
	switch timeframe {
	case "1m":
		return &Builder{
			minCandles: 3010, // 50*60 + margin for 1h EMA on 1m
			mult15m:    15,
			mult1h:     60,
		}
	default: // "5m"
		return NewFeatureBuilder()
	}
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

	// ---- EMAs (base timeframe) ----
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

	// ---- Multi-timeframe EMAs (SMA-based rolling, matching Python) ----
	// Python uses df["close"].rolling(window=21*mult, min_periods=21).mean()
	// which is a simple moving average over the scaled window.
	if sma21_15m := SMA(candles, 21*b.mult15m); sma21_15m != nil {
		fv.EMA21_15m = sma21_15m[len(sma21_15m)-1]
	}
	if sma50_15m := SMA(candles, 50*b.mult15m); sma50_15m != nil {
		fv.EMA50_15m = sma50_15m[len(sma50_15m)-1]
	}
	if sma21_1h := SMA(candles, 21*b.mult1h); sma21_1h != nil {
		fv.EMA21_1h = sma21_1h[len(sma21_1h)-1]
	}
	if sma50_1h := SMA(candles, 50*b.mult1h); sma50_1h != nil {
		fv.EMA50_1h = sma50_1h[len(sma50_1h)-1]
	}

	// ---- Trend alignment ----
	// Python: (close > ema_21) & (close > ema_21_15m) & (close > ema_21_1h)
	if fv.Close > fv.EMA21 && fv.Close > fv.EMA21_15m && fv.Close > fv.EMA21_1h {
		fv.TrendAligned = 1.0
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

	// ---- Volume surge (volume > 1.5x 100-bar avg) ----
	if vs := VolumeSurge(candles, 100, 1.5); vs != nil {
		fv.VolSurge = vs[len(vs)-1]
	}

	// ---- Price-volume divergence ----
	if pvd := PriceVolumeDivergence(candles, 10); pvd != nil {
		fv.PVDivergence = pvd[len(pvd)-1]
	}

	// ---- Time-of-day encoding ----
	hour := float64(last.CloseTime.Hour()) + float64(last.CloseTime.Minute())/60.0
	fv.HourSin = math.Sin(2 * math.Pi * hour / 24.0)
	fv.HourCos = math.Cos(2 * math.Pi * hour / 24.0)

	// ---- Session indicators ----
	h := last.CloseTime.Hour()
	if h >= 13 && h < 21 { // 8am-4pm EST = 13-21 UTC
		fv.IsUSSession = 1.0
	}
	if h >= 0 && h < 8 { // Asia hours UTC
		fv.IsAsiaSession = 1.0
	}
	weekday := last.CloseTime.Weekday()
	if weekday == time.Saturday || weekday == time.Sunday {
		fv.IsWeekend = 1.0
	}

	// ---- Sentiment ----
	if sent != nil {
		fv.SentimentScore1h = sent.Score1h
		fv.SentimentScore24h = sent.Score24h
		fv.MentionsZScore = sent.MentionsZScore
		fv.SentimentVelocity = sent.Velocity
	}

	return fv
}
