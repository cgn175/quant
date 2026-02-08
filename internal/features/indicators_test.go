package features

import (
	"math"
	"testing"
	"time"

	"github.com/cgn175/quant-bot/internal/exchange"
)

const epsilon = 0.0001

func almostEqual(a, b float64) bool {
	return math.Abs(a-b) < epsilon
}

// makeCandles creates candles from close prices. High = close+1, Low = close-1, Open = Close, Volume = 100.
func makeCandles(prices []float64) []exchange.Candle {
	candles := make([]exchange.Candle, len(prices))
	for i, p := range prices {
		candles[i] = exchange.Candle{
			Symbol:    "BTCUSDT",
			OpenTime:  time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC).Add(time.Duration(i) * 4 * time.Hour),
			CloseTime: time.Date(2024, 1, 1, 4, 0, 0, 0, time.UTC).Add(time.Duration(i) * 4 * time.Hour),
			Open:      p,
			High:      p + 1,
			Low:       p - 1,
			Close:     p,
			Volume:    100,
		}
	}
	return candles
}

// makeCandlesOHLCV creates candles with explicit OHLCV data.
func makeCandlesOHLCV(data [][5]float64) []exchange.Candle {
	candles := make([]exchange.Candle, len(data))
	for i, d := range data {
		candles[i] = exchange.Candle{
			Symbol:    "BTCUSDT",
			OpenTime:  time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC).Add(time.Duration(i) * 4 * time.Hour),
			CloseTime: time.Date(2024, 1, 1, 4, 0, 0, 0, time.UTC).Add(time.Duration(i) * 4 * time.Hour),
			Open:      d[0],
			High:      d[1],
			Low:       d[2],
			Close:     d[3],
			Volume:    d[4],
		}
	}
	return candles
}

// -------------------------------------------------------------------
// EMA
// -------------------------------------------------------------------

func TestEMA_NilOnInsufficientData(t *testing.T) {
	candles := makeCandles([]float64{100, 101, 102})
	result := EMA(candles, 5)
	if result != nil {
		t.Fatal("expected nil for insufficient data")
	}
}

func TestEMA_TracksTrend(t *testing.T) {
	prices := []float64{100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 120}
	candles := makeCandles(prices)
	result := EMA(candles, 5)
	if result == nil {
		t.Fatal("expected non-nil result")
	}

	// EMA should be increasing for upward trend
	for i := 5; i < len(result); i++ {
		if result[i] <= result[i-1] {
			t.Errorf("EMA should be increasing at index %d: %.4f <= %.4f", i, result[i], result[i-1])
		}
	}
}

func TestEMA_SeedValue(t *testing.T) {
	prices := []float64{10, 20, 30, 40, 50}
	candles := makeCandles(prices)
	result := EMA(candles, 5)
	if result == nil {
		t.Fatal("expected non-nil result")
	}
	// Seed at index 4 = SMA of first 5 = (10+20+30+40+50)/5 = 30
	if !almostEqual(result[4], 30.0) {
		t.Errorf("EMA seed: got %.4f, want 30.0", result[4])
	}
}

// -------------------------------------------------------------------
// RSI
// -------------------------------------------------------------------

func TestRSI_NilOnInsufficientData(t *testing.T) {
	candles := makeCandles([]float64{100, 101})
	result := RSI(candles, 14)
	if result != nil {
		t.Fatal("expected nil for insufficient data")
	}
}

// -------------------------------------------------------------------
// SMA
// -------------------------------------------------------------------

func TestSMA_NilOnInsufficientData(t *testing.T) {
	candles := makeCandles([]float64{100, 101})
	result := SMA(candles, 5)
	if result != nil {
		t.Fatal("expected nil for insufficient data")
	}
}

func TestSMA_CorrectValues(t *testing.T) {
	prices := []float64{10, 20, 30, 40, 50}
	candles := makeCandles(prices)
	result := SMA(candles, 3)
	if result == nil {
		t.Fatal("expected non-nil result")
	}
	// SMA(3) at index 2 = (10+20+30)/3 = 20
	if !almostEqual(result[2], 20.0) {
		t.Errorf("SMA[2]: got %.4f, want 20.0", result[2])
	}
	// SMA(3) at index 3 = (20+30+40)/3 = 30
	if !almostEqual(result[3], 30.0) {
		t.Errorf("SMA[3]: got %.4f, want 30.0", result[3])
	}
	// SMA(3) at index 4 = (30+40+50)/3 = 40
	if !almostEqual(result[4], 40.0) {
		t.Errorf("SMA[4]: got %.4f, want 40.0", result[4])
	}
}

// -------------------------------------------------------------------
// ATR
// -------------------------------------------------------------------

func TestATR_NilOnInsufficientData(t *testing.T) {
	candles := makeCandles([]float64{100, 101, 102})
	result := ATR(candles, 14)
	if result != nil {
		t.Fatal("expected nil for insufficient data")
	}
}

func TestATR_UniformCandles(t *testing.T) {
	// With uniform H/L spread (H=C+1, L=C-1), true range should be ~2 for each bar
	prices := make([]float64, 20)
	for i := range prices {
		prices[i] = 100 // constant price
	}
	candles := makeCandles(prices)
	result := ATR(candles, 5)
	if result == nil {
		t.Fatal("expected non-nil result")
	}

	// After warm-up, ATR should stabilize near 2.0 (H-L = 2 for each bar)
	for i := 10; i < len(result); i++ {
		if !almostEqual(result[i], 2.0) {
			t.Errorf("ATR[%d]: got %.4f, want ~2.0", i, result[i])
		}
	}
}

func TestATR_WilderSmoothing(t *testing.T) {
	// After a spike, Wilder smoothing should produce gradually decreasing values
	prices := make([]float64, 25)
	for i := range prices {
		prices[i] = 100
	}
	candles := makeCandles(prices)
	// Insert a big spike at bar 15
	candles[15].High = 120
	candles[15].Low = 80

	result := ATR(candles, 5)
	if result == nil {
		t.Fatal("expected non-nil result")
	}

	// After the spike, ATR should be elevated then decay
	if result[15] <= result[14] {
		t.Error("ATR should spike at bar 15")
	}
	for i := 16; i < 22; i++ {
		if result[i] > result[i-1]+epsilon {
			t.Errorf("ATR should be decaying at index %d: %.4f > %.4f", i, result[i], result[i-1])
		}
	}
}

// -------------------------------------------------------------------
// VolumeRatio
// -------------------------------------------------------------------

func TestVolumeRatio_NilOnInsufficientData(t *testing.T) {
	candles := makeCandles([]float64{100, 101})
	result := VolumeRatio(candles, 5)
	if result != nil {
		t.Fatal("expected nil for insufficient data")
	}
}

func TestVolumeRatio_HighVolume(t *testing.T) {
	prices := make([]float64, 10)
	for i := range prices {
		prices[i] = 100
	}
	candles := makeCandles(prices)
	// Make last candle have 3x volume
	candles[9].Volume = 300

	result := VolumeRatio(candles, 5)
	if result == nil {
		t.Fatal("expected non-nil result")
	}

	// Volume ratio at last bar should be > 1.0
	if result[9] <= 1.0 {
		t.Errorf("expected volume ratio > 1.0 at last bar, got %.4f", result[9])
	}
}

// -------------------------------------------------------------------
// DonchianUpper
// -------------------------------------------------------------------

func TestDonchianUpper_NilOnInsufficientData(t *testing.T) {
	candles := makeCandles([]float64{100, 101, 102})
	result := DonchianUpper(candles, 5)
	if result != nil {
		t.Fatal("expected nil for insufficient data")
	}
}

func TestDonchianUpper_ExcludesCurrentBar(t *testing.T) {
	// Prices: 100, 105, 103, 108, 102, 110
	// High:   101, 106, 104, 109, 103, 111
	// DonchianUpper(period=3) at index 3 = max(high[0], high[1], high[2]) = max(101,106,104) = 106
	// DonchianUpper(period=3) at index 4 = max(high[1], high[2], high[3]) = max(106,104,109) = 109
	// DonchianUpper(period=3) at index 5 = max(high[2], high[3], high[4]) = max(104,109,103) = 109
	candles := makeCandles([]float64{100, 105, 103, 108, 102, 110})
	result := DonchianUpper(candles, 3)
	if result == nil {
		t.Fatal("expected non-nil result")
	}

	// Index 3: max(high[0..2]) = max(101,106,104) = 106
	if !almostEqual(result[3], 106.0) {
		t.Errorf("DonchianUpper[3]: got %.4f, want 106.0", result[3])
	}
	// Index 4: max(high[1..3]) = max(106,104,109) = 109
	if !almostEqual(result[4], 109.0) {
		t.Errorf("DonchianUpper[4]: got %.4f, want 109.0", result[4])
	}
	// Index 5: max(high[2..4]) = max(104,109,103) = 109 (NOT 111)
	if !almostEqual(result[5], 109.0) {
		t.Errorf("DonchianUpper[5]: got %.4f, want 109.0 (must exclude current bar high=111)", result[5])
	}
}

func TestDonchianUpper_FirstEntriesZero(t *testing.T) {
	candles := makeCandles([]float64{100, 105, 103, 108, 102, 110})
	result := DonchianUpper(candles, 3)
	if result == nil {
		t.Fatal("expected non-nil result")
	}
	for i := 0; i < 3; i++ {
		if result[i] != 0 {
			t.Errorf("DonchianUpper[%d] should be 0, got %.4f", i, result[i])
		}
	}
}

// -------------------------------------------------------------------
// DonchianLower
// -------------------------------------------------------------------

func TestDonchianLower_NilOnInsufficientData(t *testing.T) {
	candles := makeCandles([]float64{100, 101, 102})
	result := DonchianLower(candles, 5)
	if result != nil {
		t.Fatal("expected nil for insufficient data")
	}
}

func TestDonchianLower_ExcludesCurrentBar(t *testing.T) {
	// Prices: 100, 95, 103, 90, 102, 85
	// Low:    99,  94, 102, 89, 101, 84
	// DonchianLower(period=3) at index 3 = min(low[0], low[1], low[2]) = min(99,94,102) = 94
	// DonchianLower(period=3) at index 5 = min(low[2], low[3], low[4]) = min(102,89,101) = 89 (NOT 84)
	candles := makeCandles([]float64{100, 95, 103, 90, 102, 85})
	result := DonchianLower(candles, 3)
	if result == nil {
		t.Fatal("expected non-nil result")
	}

	if !almostEqual(result[3], 94.0) {
		t.Errorf("DonchianLower[3]: got %.4f, want 94.0", result[3])
	}
	if !almostEqual(result[5], 89.0) {
		t.Errorf("DonchianLower[5]: got %.4f, want 89.0 (must exclude current bar low=84)", result[5])
	}
}

// -------------------------------------------------------------------
// HighestHigh
// -------------------------------------------------------------------

func TestHighestHigh_NilOnInsufficientData(t *testing.T) {
	candles := makeCandles([]float64{100, 101})
	result := HighestHigh(candles, 5)
	if result != nil {
		t.Fatal("expected nil for insufficient data")
	}
}

func TestHighestHigh_IncludesCurrentBar(t *testing.T) {
	// Prices: 100, 105, 103, 108, 102
	// High:   101, 106, 104, 109, 103
	// HighestHigh(3) at index 4 = max(high[2], high[3], high[4]) = max(104,109,103) = 109
	candles := makeCandles([]float64{100, 105, 103, 108, 102})
	result := HighestHigh(candles, 3)
	if result == nil {
		t.Fatal("expected non-nil result")
	}

	// At index 4, includes current bar
	if !almostEqual(result[4], 109.0) {
		t.Errorf("HighestHigh[4]: got %.4f, want 109.0", result[4])
	}
	// At index 2 = max(high[0..2]) = max(101,106,104) = 106
	if !almostEqual(result[2], 106.0) {
		t.Errorf("HighestHigh[2]: got %.4f, want 106.0", result[2])
	}
}

// -------------------------------------------------------------------
// LowestLow
// -------------------------------------------------------------------

func TestLowestLow_NilOnInsufficientData(t *testing.T) {
	candles := makeCandles([]float64{100, 101})
	result := LowestLow(candles, 5)
	if result != nil {
		t.Fatal("expected nil for insufficient data")
	}
}

func TestLowestLow_IncludesCurrentBar(t *testing.T) {
	// Prices: 100, 95, 103, 90, 102
	// Low:    99,  94, 102, 89, 101
	// LowestLow(3) at index 4 = min(low[2], low[3], low[4]) = min(102,89,101) = 89
	candles := makeCandles([]float64{100, 95, 103, 90, 102})
	result := LowestLow(candles, 3)
	if result == nil {
		t.Fatal("expected non-nil result")
	}

	if !almostEqual(result[4], 89.0) {
		t.Errorf("LowestLow[4]: got %.4f, want 89.0", result[4])
	}
}

// -------------------------------------------------------------------
// ADX
// -------------------------------------------------------------------

func TestADX_NilOnInsufficientData(t *testing.T) {
	candles := makeCandles([]float64{100, 101, 102})
	result := ADX(candles, 14)
	if result != nil {
		t.Fatal("expected nil for insufficient data")
	}
}

func TestADX_TrendingMarketHighADX(t *testing.T) {
	// Create 40 candles with a strong uptrend
	n := 40
	candles := make([]exchange.Candle, n)
	for i := 0; i < n; i++ {
		price := 100.0 + float64(i)*3.0 // strong uptrend: +3 per bar
		candles[i] = exchange.Candle{
			Symbol:    "BTCUSDT",
			OpenTime:  time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC).Add(time.Duration(i) * 4 * time.Hour),
			CloseTime: time.Date(2024, 1, 1, 4, 0, 0, 0, time.UTC).Add(time.Duration(i) * 4 * time.Hour),
			Open:      price - 1,
			High:      price + 2,
			Low:       price - 2,
			Close:     price,
			Volume:    100,
		}
	}

	result := ADX(candles, 7)
	if result == nil {
		t.Fatal("expected non-nil result for trending data")
	}

	// ADX should be elevated (> 20) for strong trend
	lastADX := result[len(result)-1]
	if lastADX < 20 {
		t.Errorf("ADX for trending market should be > 20, got %.4f", lastADX)
	}
}

func TestADX_ChoppyMarketLowADX(t *testing.T) {
	// Create 40 candles with choppy/ranging price
	n := 40
	candles := make([]exchange.Candle, n)
	for i := 0; i < n; i++ {
		// Oscillate: 100, 102, 100, 102, ...
		price := 100.0
		if i%2 == 1 {
			price = 102.0
		}
		candles[i] = exchange.Candle{
			Symbol:    "BTCUSDT",
			OpenTime:  time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC).Add(time.Duration(i) * 4 * time.Hour),
			CloseTime: time.Date(2024, 1, 1, 4, 0, 0, 0, time.UTC).Add(time.Duration(i) * 4 * time.Hour),
			Open:      price,
			High:      price + 1,
			Low:       price - 1,
			Close:     price,
			Volume:    100,
		}
	}

	result := ADX(candles, 7)
	if result == nil {
		t.Fatal("expected non-nil result for choppy data")
	}

	lastADX := result[len(result)-1]
	if lastADX > 25 {
		t.Errorf("ADX for choppy market should be < 25, got %.4f", lastADX)
	}
}

func TestADX_WarmupZeros(t *testing.T) {
	prices := make([]float64, 40)
	for i := range prices {
		prices[i] = 100.0 + float64(i)
	}
	candles := makeCandles(prices)
	period := 7
	result := ADX(candles, period)
	if result == nil {
		t.Fatal("expected non-nil result")
	}

	// First 2*period-1 values should be 0
	for i := 0; i < 2*period-1; i++ {
		if result[i] != 0 {
			t.Errorf("ADX[%d] should be 0 during warm-up, got %.4f", i, result[i])
		}
	}
	// Value at 2*period-1 should be non-zero
	if result[2*period-1] == 0 {
		t.Errorf("ADX[%d] should be non-zero after warm-up", 2*period-1)
	}
}

// -------------------------------------------------------------------
// ChandelierExitLong
// -------------------------------------------------------------------

func TestChandelierExitLong_NilOnInsufficientData(t *testing.T) {
	candles := makeCandles([]float64{100, 101, 102})
	result := ChandelierExitLong(candles, 14, 3.0, 10)
	if result != nil {
		t.Fatal("expected nil for insufficient data")
	}
}

func TestChandelierExitLong_LessThanHighestHigh(t *testing.T) {
	prices := make([]float64, 30)
	for i := range prices {
		prices[i] = 100.0 + float64(i)*2.0
	}
	candles := makeCandles(prices)
	result := ChandelierExitLong(candles, 5, 3.0, 5)
	if result == nil {
		t.Fatal("expected non-nil result")
	}

	hhVals := HighestHigh(candles, 5)
	for i := 5; i < len(result); i++ {
		if result[i] > 0 && hhVals[i] > 0 {
			if result[i] >= hhVals[i] {
				t.Errorf("ChandelierExitLong[%d] (%.4f) should be < HighestHigh (%.4f)", i, result[i], hhVals[i])
			}
		}
	}
}

func TestChandelierExitLong_Formula(t *testing.T) {
	prices := make([]float64, 25)
	for i := range prices {
		prices[i] = 100.0 + float64(i)*2.0
	}
	candles := makeCandles(prices)
	atrPeriod := 5
	mult := 3.0
	lookback := 5

	result := ChandelierExitLong(candles, atrPeriod, mult, lookback)
	atrVals := ATR(candles, atrPeriod)
	hhVals := HighestHigh(candles, lookback)

	if result == nil || atrVals == nil || hhVals == nil {
		t.Fatal("expected non-nil results")
	}

	// Verify formula at a valid index
	idx := 15
	expected := hhVals[idx] - mult*atrVals[idx]
	if !almostEqual(result[idx], expected) {
		t.Errorf("ChandelierExitLong[%d]: got %.4f, want %.4f (HH=%.4f, ATR=%.4f)", idx, result[idx], expected, hhVals[idx], atrVals[idx])
	}
}

// -------------------------------------------------------------------
// ChandelierExitShort
// -------------------------------------------------------------------

func TestChandelierExitShort_NilOnInsufficientData(t *testing.T) {
	candles := makeCandles([]float64{100, 101, 102})
	result := ChandelierExitShort(candles, 14, 3.0, 10)
	if result != nil {
		t.Fatal("expected nil for insufficient data")
	}
}

func TestChandelierExitShort_GreaterThanLowestLow(t *testing.T) {
	prices := make([]float64, 30)
	for i := range prices {
		prices[i] = 200.0 - float64(i)*2.0
	}
	candles := makeCandles(prices)
	result := ChandelierExitShort(candles, 5, 3.0, 5)
	if result == nil {
		t.Fatal("expected non-nil result")
	}

	llVals := LowestLow(candles, 5)
	for i := 5; i < len(result); i++ {
		if result[i] > 0 && llVals[i] > 0 {
			if result[i] <= llVals[i] {
				t.Errorf("ChandelierExitShort[%d] (%.4f) should be > LowestLow (%.4f)", i, result[i], llVals[i])
			}
		}
	}
}

func TestChandelierExitShort_Formula(t *testing.T) {
	prices := make([]float64, 25)
	for i := range prices {
		prices[i] = 200.0 - float64(i)*2.0
	}
	candles := makeCandles(prices)
	atrPeriod := 5
	mult := 3.0
	lookback := 5

	result := ChandelierExitShort(candles, atrPeriod, mult, lookback)
	atrVals := ATR(candles, atrPeriod)
	llVals := LowestLow(candles, lookback)

	if result == nil || atrVals == nil || llVals == nil {
		t.Fatal("expected non-nil results")
	}

	idx := 15
	expected := llVals[idx] + mult*atrVals[idx]
	if !almostEqual(result[idx], expected) {
		t.Errorf("ChandelierExitShort[%d]: got %.4f, want %.4f (LL=%.4f, ATR=%.4f)", idx, result[idx], expected, llVals[idx], atrVals[idx])
	}
}
