package features

import (
	"math"
	"time"

	"github.com/cgn175/quant-bot/internal/exchange"
)

// FeatureVector4H represents all features for a single 4h bar.
// The field order and ToArray() output MUST match FEATURE_COLUMNS_4H in
// scripts/train_4h.py so that the ONNX model receives features in
// the same order it was trained on.
type FeatureVector4H struct {
	Symbol    string
	Timestamp time.Time

	// Raw OHLCV (not part of model input, but useful for logging/execution)
	Open   float64
	High   float64
	Low    float64
	Close  float64
	Volume float64

	// --- Model features (33 total, order matters) ---
	// 1. close
	// 2-5. log returns
	LogReturn1  float64 // 1-bar (4h)
	LogReturn2  float64 // 2-bar (8h)
	LogReturn6  float64 // 6-bar (24h)
	LogReturn12 float64 // 12-bar (48h)
	// 6-9. EMAs
	EMA5  float64
	EMA9  float64
	EMA21 float64
	EMA50 float64
	// 10-12. Daily/weekly SMAs
	SMA6  float64 // 6 bars = 1 day
	SMA30 float64 // 30 bars = 5 days
	SMA42 float64 // 42 bars = 1 week
	// 13. Trend alignment
	TrendAligned float64
	// 14-15. RSI
	RSI7  float64
	RSI14 float64
	// 16-20. Bollinger bands
	BBandUpper  float64
	BBandMiddle float64
	BBandLower  float64
	BBWidth     float64
	BBPct       float64
	// 21-23. MACD
	MACD       float64
	MACDSignal float64
	MACDHist   float64
	// 24-25. Volume
	VolumeRatio float64
	VolSurge    float64
	// 26-27. Volatility
	ATR14    float64
	ATRRatio float64
	// 28-29. Momentum
	ROC6  float64 // 24h momentum
	ROC12 float64 // 48h momentum
	// 30-33. Time encoding
	HourSin float64
	HourCos float64
	DaySin  float64
	DayCos  float64
}

// ToArray converts the 4H feature vector to a float64 slice for model input.
// The order MUST match scripts/train_4h.py FEATURE_COLUMNS_4H exactly:
//
//	close, log_ret_1, log_ret_2, log_ret_6, log_ret_12,
//	ema_5, ema_9, ema_21, ema_50, sma_6, sma_30, sma_42, trend_aligned,
//	rsi_7, rsi_14, bb_upper, bb_middle, bb_lower, bb_width, bb_pct,
//	macd, macd_signal, macd_histogram, volume_ratio, vol_surge,
//	atr_14, atr_ratio, roc_6, roc_12,
//	hour_sin, hour_cos, day_sin, day_cos
func (fv *FeatureVector4H) ToArray() []float64 {
	return []float64{
		fv.Close,
		fv.LogReturn1,
		fv.LogReturn2,
		fv.LogReturn6,
		fv.LogReturn12,
		fv.EMA5,
		fv.EMA9,
		fv.EMA21,
		fv.EMA50,
		fv.SMA6,
		fv.SMA30,
		fv.SMA42,
		fv.TrendAligned,
		fv.RSI7,
		fv.RSI14,
		fv.BBandUpper,
		fv.BBandMiddle,
		fv.BBandLower,
		fv.BBWidth,
		fv.BBPct,
		fv.MACD,
		fv.MACDSignal,
		fv.MACDHist,
		fv.VolumeRatio,
		fv.VolSurge,
		fv.ATR14,
		fv.ATRRatio,
		fv.ROC6,
		fv.ROC12,
		fv.HourSin,
		fv.HourCos,
		fv.DaySin,
		fv.DayCos,
	}
}

// FeatureNames4H returns the ordered list of feature names matching the
// Python training script's FEATURE_COLUMNS_4H.
func FeatureNames4H() []string {
	return []string{
		"close",
		"log_ret_1",
		"log_ret_2",
		"log_ret_6",
		"log_ret_12",
		"ema_5",
		"ema_9",
		"ema_21",
		"ema_50",
		"sma_6",
		"sma_30",
		"sma_42",
		"trend_aligned",
		"rsi_7",
		"rsi_14",
		"bb_upper",
		"bb_middle",
		"bb_lower",
		"bb_width",
		"bb_pct",
		"macd",
		"macd_signal",
		"macd_histogram",
		"volume_ratio",
		"vol_surge",
		"atr_14",
		"atr_ratio",
		"roc_6",
		"roc_12",
		"hour_sin",
		"hour_cos",
		"day_sin",
		"day_cos",
	}
}

// Builder4H computes a FeatureVector4H from raw 4h candles.
// It delegates to the indicator functions in indicators.go.
type Builder4H struct {
	minCandles int
}

// NewFeatureBuilder4H creates a new feature builder for 4h timeframe.
// For 4h bars the slowest indicator is EMA-50, so we need ~55 bars.
func NewFeatureBuilder4H() *Builder4H {
	return &Builder4H{
		minCandles: 60, // EMA-50 + margin for warm-up
	}
}

// MinCandles returns the minimum number of 4h candles required before
// features can be computed.
func (b *Builder4H) MinCandles() int {
	return b.minCandles
}

// Build computes a FeatureVector4H from the latest candle in the slice.
// Returns nil when there are not enough candles for indicator warm-up.
//
// Parameters:
//   - candles: time-sorted []exchange.Candle (oldest first).
func (b *Builder4H) Build(candles []exchange.Candle) *FeatureVector4H {
	if len(candles) < b.minCandles {
		return nil
	}

	last := candles[len(candles)-1]

	fv := &FeatureVector4H{
		Symbol:    last.Symbol,
		Timestamp: last.CloseTime,
		Open:      last.Open,
		High:      last.High,
		Low:       last.Low,
		Close:     last.Close,
		Volume:    last.Volume,
	}

	// ---- Log returns ----
	if lr1 := LogReturn(candles, 1); lr1 != nil {
		fv.LogReturn1 = lr1[len(lr1)-1]
	}
	if lr2 := LogReturn(candles, 2); lr2 != nil {
		fv.LogReturn2 = lr2[len(lr2)-1]
	}
	if lr6 := LogReturn(candles, 6); lr6 != nil {
		fv.LogReturn6 = lr6[len(lr6)-1]
	}
	if lr12 := LogReturn(candles, 12); lr12 != nil {
		fv.LogReturn12 = lr12[len(lr12)-1]
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

	// ---- SMAs (daily/weekly context) ----
	if sma6 := SMA(candles, 6); sma6 != nil {
		fv.SMA6 = sma6[len(sma6)-1]
	}
	if sma30 := SMA(candles, 30); sma30 != nil {
		fv.SMA30 = sma30[len(sma30)-1]
	}
	if sma42 := SMA(candles, 42); sma42 != nil {
		fv.SMA42 = sma42[len(sma42)-1]
	}

	// ---- Trend alignment ----
	// Python: (close > ema_21) & (close > sma_30) & (close > sma_42)
	if fv.Close > fv.EMA21 && fv.Close > fv.SMA30 && fv.Close > fv.SMA42 {
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
		// bb_pct = (close - lower) / (upper - lower)
		width := fv.BBandUpper - fv.BBandLower
		if width > 0 {
			fv.BBPct = (fv.Close - fv.BBandLower) / width
		}
	}

	// ---- MACD (12, 26, 9) ----
	if macd := CalcMACD(candles, 12, 26, 9); macd != nil {
		idx := len(macd.MACD) - 1
		fv.MACD = macd.MACD[idx]
		fv.MACDSignal = macd.Signal[idx]
		fv.MACDHist = macd.Histogram[idx]
	}

	// ---- Volume ratio (20-bar rolling average) ----
	if vr := VolumeRatio(candles, 20); vr != nil {
		fv.VolumeRatio = vr[len(vr)-1]
	}

	// ---- Volume surge (volume > 1.5x 50-bar avg) ----
	// Python train_4h.py uses window=50 for vol_surge
	if vs := VolumeSurge(candles, 50, 1.5); vs != nil {
		fv.VolSurge = vs[len(vs)-1]
	}

	// ---- ATR (14-period) ----
	if atr := ATR(candles, 14); atr != nil {
		fv.ATR14 = atr[len(atr)-1]
		if fv.Close > 0 {
			fv.ATRRatio = fv.ATR14 / fv.Close
		}
	}

	// ---- Rate of Change ----
	if roc6 := ROC(candles, 6); roc6 != nil {
		fv.ROC6 = roc6[len(roc6)-1]
	}
	if roc12 := ROC(candles, 12); roc12 != nil {
		fv.ROC12 = roc12[len(roc12)-1]
	}

	// ---- Time encoding ----
	hour := float64(last.CloseTime.Hour()) + float64(last.CloseTime.Minute())/60.0
	fv.HourSin = math.Sin(2 * math.Pi * hour / 24.0)
	fv.HourCos = math.Cos(2 * math.Pi * hour / 24.0)

	dayOfWeek := float64(last.CloseTime.Weekday())
	fv.DaySin = math.Sin(2 * math.Pi * dayOfWeek / 7.0)
	fv.DayCos = math.Cos(2 * math.Pi * dayOfWeek / 7.0)

	return fv
}
