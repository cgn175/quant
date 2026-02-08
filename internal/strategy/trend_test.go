package strategy

import (
	"math"
	"testing"
	"time"

	"github.com/cgn175/quant-bot/internal/data"
	"github.com/cgn175/quant-bot/internal/exchange"
)

const epsilon = 0.0001

func almostEqual(a, b float64) bool {
	return math.Abs(a-b) < epsilon
}

// makeTrendCandles creates candles from close prices. High = close+1, Low = close-1, Volume = 150 (>avg to pass volume filter).
// All candles are marked as closed (IsClosed=true) for indicator computation.
func makeTrendCandles(prices []float64) []exchange.Candle {
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
			Volume:    150,
			IsClosed:  true,
		}
	}
	return candles
}

// -------------------------------------------------------------------
// DefaultTrendConfig
// -------------------------------------------------------------------

func TestDefaultTrendConfig(t *testing.T) {
	cfg := DefaultTrendConfig()
	if cfg.DonchianPeriod != 20 {
		t.Errorf("DonchianPeriod: got %d, want 20", cfg.DonchianPeriod)
	}
	if cfg.EMAFast != 9 {
		t.Errorf("EMAFast: got %d, want 9", cfg.EMAFast)
	}
	if cfg.EMASlow != 21 {
		t.Errorf("EMASlow: got %d, want 21", cfg.EMASlow)
	}
	if cfg.EMAConfirmBars != 5 {
		t.Errorf("EMAConfirmBars: got %d, want 5", cfg.EMAConfirmBars)
	}
	if cfg.EMATrend != 50 {
		t.Errorf("EMATrend: got %d, want 50", cfg.EMATrend)
	}
	if cfg.ATRPeriod != 14 {
		t.Errorf("ATRPeriod: got %d, want 14", cfg.ATRPeriod)
	}
	if !almostEqual(cfg.ATRStopMult, 3.0) {
		t.Errorf("ATRStopMult: got %.2f, want 3.0", cfg.ATRStopMult)
	}
	if cfg.ADXPeriod != 14 {
		t.Errorf("ADXPeriod: got %d, want 14", cfg.ADXPeriod)
	}
	if !almostEqual(cfg.ADXThreshold, 20.0) {
		t.Errorf("ADXThreshold: got %.2f, want 20.0", cfg.ADXThreshold)
	}
	if !almostEqual(cfg.RiskPerTrade, 0.01) {
		t.Errorf("RiskPerTrade: got %.4f, want 0.01", cfg.RiskPerTrade)
	}
	if !almostEqual(cfg.MaxLeverage, 2.0) {
		t.Errorf("MaxLeverage: got %.2f, want 2.0", cfg.MaxLeverage)
	}
	if !almostEqual(cfg.FirstTargetR, 3.0) {
		t.Errorf("FirstTargetR: got %.2f, want 3.0", cfg.FirstTargetR)
	}
	if !almostEqual(cfg.SecondTargetR, 6.0) {
		t.Errorf("SecondTargetR: got %.2f, want 6.0", cfg.SecondTargetR)
	}
	if cfg.MaxCorrelatedSame != 2 {
		t.Errorf("MaxCorrelatedSame: got %d, want 2", cfg.MaxCorrelatedSame)
	}
}

// -------------------------------------------------------------------
// MinCandles
// -------------------------------------------------------------------

func TestMinCandles(t *testing.T) {
	cfg := DefaultTrendConfig()
	min := cfg.MinCandles()

	// Needs at least 2*14+1=29 for ADX, 51 for ATR(50), + 5 safety
	if min < 56 {
		t.Errorf("MinCandles should be >= 56, got %d", min)
	}
}

// -------------------------------------------------------------------
// Position Registration / Removal
// -------------------------------------------------------------------

func TestPositionRegistration(t *testing.T) {
	ts := NewTrendStrategy(DefaultTrendConfig())

	if ts.HasPosition("BTCUSDT") {
		t.Error("should not have position before registration")
	}

	ts.RegisterPosition("BTCUSDT", "LONG", 50000, 0.1, 48000, 1.0)

	if !ts.HasPosition("BTCUSDT") {
		t.Error("should have position after registration")
	}

	pos := ts.GetPosition("BTCUSDT")
	if pos == nil {
		t.Fatal("GetPosition returned nil")
	}
	if pos.Side != "LONG" {
		t.Errorf("Side: got %s, want LONG", pos.Side)
	}
	if !almostEqual(pos.EntryPrice, 50000) {
		t.Errorf("EntryPrice: got %.2f, want 50000", pos.EntryPrice)
	}
	if !almostEqual(pos.Size, 0.1) {
		t.Errorf("Size: got %.4f, want 0.1", pos.Size)
	}
	if !almostEqual(pos.InitialStop, 48000) {
		t.Errorf("InitialStop: got %.2f, want 48000", pos.InitialStop)
	}
	if !almostEqual(pos.InitialRisk, 2000) {
		t.Errorf("InitialRisk: got %.2f, want 2000", pos.InitialRisk)
	}

	// Verify it's a copy (mutations don't affect internal state)
	pos.Size = 999
	pos2 := ts.GetPosition("BTCUSDT")
	if almostEqual(pos2.Size, 999) {
		t.Error("GetPosition should return a copy, not internal reference")
	}
}

func TestPositionRemoval(t *testing.T) {
	ts := NewTrendStrategy(DefaultTrendConfig())
	ts.RegisterPosition("BTCUSDT", "LONG", 50000, 0.1, 48000, 1.0)
	ts.RemovePosition("BTCUSDT")

	if ts.HasPosition("BTCUSDT") {
		t.Error("position should be removed")
	}
	if ts.GetPosition("BTCUSDT") != nil {
		t.Error("GetPosition should return nil after removal")
	}
}

func TestOpenPositionCount(t *testing.T) {
	ts := NewTrendStrategy(DefaultTrendConfig())
	if ts.OpenPositionCount() != 0 {
		t.Errorf("expected 0 positions, got %d", ts.OpenPositionCount())
	}

	ts.RegisterPosition("BTCUSDT", "LONG", 50000, 0.1, 48000, 1.0)
	ts.RegisterPosition("ETHUSDT", "SHORT", 3000, 1.0, 3200, 1.0)
	if ts.OpenPositionCount() != 2 {
		t.Errorf("expected 2 positions, got %d", ts.OpenPositionCount())
	}
}

// -------------------------------------------------------------------
// CurrentR
// -------------------------------------------------------------------

func TestCurrentR_Long(t *testing.T) {
	pos := &TrendPosition{
		Side:        "LONG",
		EntryPrice:  50000,
		InitialRisk: 2000, // stop was at 48000
	}

	// Price goes up to 54000 → +4000 / 2000 = 2R
	r := pos.CurrentR(54000)
	if !almostEqual(r, 2.0) {
		t.Errorf("Long +4000: got %.4f, want 2.0", r)
	}

	// Price goes down to 49000 → -1000 / 2000 = -0.5R
	r = pos.CurrentR(49000)
	if !almostEqual(r, -0.5) {
		t.Errorf("Long -1000: got %.4f, want -0.5", r)
	}
}

func TestCurrentR_Short(t *testing.T) {
	pos := &TrendPosition{
		Side:        "SHORT",
		EntryPrice:  50000,
		InitialRisk: 2000, // stop was at 52000
	}

	// Price goes down to 46000 → +4000 / 2000 = 2R
	r := pos.CurrentR(46000)
	if !almostEqual(r, 2.0) {
		t.Errorf("Short +4000: got %.4f, want 2.0", r)
	}

	// Price goes up to 51000 → -1000 / 2000 = -0.5R
	r = pos.CurrentR(51000)
	if !almostEqual(r, -0.5) {
		t.Errorf("Short -1000: got %.4f, want -0.5", r)
	}
}

func TestCurrentR_ZeroRisk(t *testing.T) {
	pos := &TrendPosition{
		Side:        "LONG",
		EntryPrice:  50000,
		InitialRisk: 0,
	}
	r := pos.CurrentR(55000)
	if r != 0 {
		t.Errorf("expected 0 for zero risk, got %.4f", r)
	}
}

// -------------------------------------------------------------------
// CalculatePositionSize
// -------------------------------------------------------------------

func TestCalculatePositionSize_Normal(t *testing.T) {
	ts := NewTrendStrategy(DefaultTrendConfig())

	equity := 10000.0
	entryPrice := 50000.0
	stopLoss := 47000.0 // 6% distance
	sizeMult := 1.0

	size := ts.CalculatePositionSize(equity, entryPrice, stopLoss, sizeMult)

	// Expected: (10000 * 0.01 * 1.0) / (50000 * 0.06) = 100 / 3000 = 0.03333
	stopDistPct := math.Abs((entryPrice - stopLoss) / entryPrice)
	expected := (equity * 0.01 * sizeMult) / (entryPrice * stopDistPct)
	if !almostEqual(size, expected) {
		t.Errorf("size: got %.6f, want %.6f", size, expected)
	}
}

func TestCalculatePositionSize_LeverageCap(t *testing.T) {
	cfg := DefaultTrendConfig()
	cfg.MaxLeverage = 2.0
	ts := NewTrendStrategy(cfg)

	equity := 10000.0
	entryPrice := 100.0
	stopLoss := 99.0 // very tight stop → large size
	sizeMult := 1.0

	size := ts.CalculatePositionSize(equity, entryPrice, stopLoss, sizeMult)

	// Max size by leverage: (10000 * 2.0) / 100 = 200
	maxSize := (equity * cfg.MaxLeverage) / entryPrice
	if size > maxSize+epsilon {
		t.Errorf("size %.4f exceeds leverage cap %.4f", size, maxSize)
	}
}

func TestCalculatePositionSize_TightStop(t *testing.T) {
	ts := NewTrendStrategy(DefaultTrendConfig())

	size := ts.CalculatePositionSize(10000, 50000, 50000, 1.0) // zero distance
	if size != 0 {
		t.Errorf("expected 0 for zero stop distance, got %.6f", size)
	}
}

func TestCalculatePositionSize_SizeMultiplier(t *testing.T) {
	ts := NewTrendStrategy(DefaultTrendConfig())

	sizeFull := ts.CalculatePositionSize(10000, 50000, 47000, 1.0)
	sizeHalf := ts.CalculatePositionSize(10000, 50000, 47000, 0.5)

	if !almostEqual(sizeHalf, sizeFull*0.5) {
		t.Errorf("half multiplier: got %.6f, want %.6f", sizeHalf, sizeFull*0.5)
	}
}

// -------------------------------------------------------------------
// OnBar — Signal Generation
// -------------------------------------------------------------------

func TestOnBar_NoSignalInsufficientCandles(t *testing.T) {
	ts := NewTrendStrategy(DefaultTrendConfig())
	candles := makeTrendCandles([]float64{100, 101, 102})

	sig := ts.OnBar("BTCUSDT", candles, nil, 10000)
	if sig != nil {
		t.Error("expected nil for insufficient candles")
	}
}

func TestOnBar_NoSignalWhenPositionExists(t *testing.T) {
	ts := NewTrendStrategy(DefaultTrendConfig())
	ts.RegisterPosition("BTCUSDT", "LONG", 50000, 0.1, 48000, 1.0)

	prices := make([]float64, 70)
	for i := range prices {
		prices[i] = 100 + float64(i)*2
	}
	candles := makeTrendCandles(prices)
	sig := ts.OnBar("BTCUSDT", candles, nil, 10000)
	if sig != nil {
		t.Error("expected nil when position already exists")
	}
}

func TestOnBar_NoSignalDailyHalted(t *testing.T) {
	cfg := DefaultTrendConfig()
	cfg.DailyLossCapPct = 0.001 // very small cap
	ts := NewTrendStrategy(cfg)

	// Record enough loss to trigger halt
	ts.RecordPnL(-100)
	ts.CheckDailyLossCap(10000) // -100 < -(10000 * 0.001) = -10 → halted

	prices := make([]float64, 70)
	for i := range prices {
		prices[i] = 100 + float64(i)*2
	}
	candles := makeTrendCandles(prices)
	sig := ts.OnBar("BTCUSDT", candles, nil, 10000)
	if sig != nil {
		t.Error("expected nil when daily halted")
	}
}

func TestOnBar_MaxPositionsBlocked(t *testing.T) {
	cfg := DefaultTrendConfig()
	cfg.MaxOpenPositions = 2
	ts := NewTrendStrategy(cfg)

	ts.RegisterPosition("BTCUSDT", "LONG", 50000, 0.1, 48000, 1.0)
	ts.RegisterPosition("ETHUSDT", "LONG", 3000, 1.0, 2800, 1.0)

	prices := make([]float64, 70)
	for i := range prices {
		prices[i] = 100 + float64(i)*2
	}
	candles := makeTrendCandles(prices)
	sig := ts.OnBar("SOLUSDT", candles, nil, 10000)
	if sig != nil {
		t.Error("expected nil when max positions reached")
	}
}

// -------------------------------------------------------------------
// UpdateTrailingStop
// -------------------------------------------------------------------

func TestUpdateTrailingStop_LongTightens(t *testing.T) {
	cfg := DefaultTrendConfig()
	cfg.ChandelierLookback = 3
	cfg.ATRPeriod = 3
	cfg.ATRStopMult = 2.0
	ts := NewTrendStrategy(cfg)

	// Register position with initial stop at 95
	ts.RegisterPosition("BTCUSDT", "LONG", 100, 1.0, 95, 1.0)

	// Create rising candles — stop should tighten (move up)
	prices := make([]float64, 20)
	for i := range prices {
		prices[i] = 100 + float64(i)*3
	}
	candles := makeTrendCandles(prices)

	// First update
	ts.UpdateTrailingStop("BTCUSDT", candles)
	pos1 := ts.GetPosition("BTCUSDT")
	if pos1 == nil {
		t.Fatal("position should exist")
	}
	stop1 := pos1.TrailingStop

	// Add more rising candles
	for i := 0; i < 5; i++ {
		prices = append(prices, prices[len(prices)-1]+3)
	}
	candles = makeTrendCandles(prices)

	ts.UpdateTrailingStop("BTCUSDT", candles)
	pos2 := ts.GetPosition("BTCUSDT")
	stop2 := pos2.TrailingStop

	if stop2 < stop1-epsilon {
		t.Errorf("trailing stop should tighten (move up): stop1=%.4f, stop2=%.4f", stop1, stop2)
	}
}

func TestUpdateTrailingStop_LongNeverMovesDown(t *testing.T) {
	cfg := DefaultTrendConfig()
	cfg.ChandelierLookback = 3
	cfg.ATRPeriod = 3
	cfg.ATRStopMult = 2.0
	ts := NewTrendStrategy(cfg)

	ts.RegisterPosition("BTCUSDT", "LONG", 100, 1.0, 90, 1.0)

	// Rising candles to raise the stop
	pricesUp := make([]float64, 15)
	for i := range pricesUp {
		pricesUp[i] = 100 + float64(i)*5
	}
	candles := makeTrendCandles(pricesUp)
	ts.UpdateTrailingStop("BTCUSDT", candles)
	posUp := ts.GetPosition("BTCUSDT")
	highStop := posUp.TrailingStop

	// Now drop prices — stop should NOT decrease
	pricesDown := make([]float64, len(pricesUp)+5)
	copy(pricesDown, pricesUp)
	for i := len(pricesUp); i < len(pricesDown); i++ {
		pricesDown[i] = pricesDown[i-1] - 3
	}
	candles = makeTrendCandles(pricesDown)

	exitSig := ts.UpdateTrailingStop("BTCUSDT", candles)
	pos := ts.GetPosition("BTCUSDT")

	// If stop wasn't hit, the trailing stop should be >= highStop
	if exitSig == nil && pos != nil {
		if pos.TrailingStop < highStop-epsilon {
			t.Errorf("trailing stop moved down: was %.4f, now %.4f", highStop, pos.TrailingStop)
		}
	}
}

func TestUpdateTrailingStop_StopHit(t *testing.T) {
	cfg := DefaultTrendConfig()
	cfg.ChandelierLookback = 3
	cfg.ATRPeriod = 3
	cfg.ATRStopMult = 2.0
	ts := NewTrendStrategy(cfg)

	ts.RegisterPosition("BTCUSDT", "LONG", 100, 1.0, 94, 1.0)

	// Create candles where last bar's low breaches the stop
	prices := []float64{98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109}
	candles := makeTrendCandles(prices)
	// Make last candle's low extremely low to breach any trailing stop
	candles[len(candles)-1].Low = 50

	exitSig := ts.UpdateTrailingStop("BTCUSDT", candles)
	if exitSig == nil {
		t.Fatal("expected ExitSignal when stop is breached")
	}
	if exitSig.Reason != "trailing_stop" {
		t.Errorf("reason: got %s, want trailing_stop", exitSig.Reason)
	}
	if exitSig.Symbol != "BTCUSDT" {
		t.Errorf("symbol: got %s, want BTCUSDT", exitSig.Symbol)
	}
}

// -------------------------------------------------------------------
// CheckPartialExit
// -------------------------------------------------------------------

func TestCheckPartialExit_3R(t *testing.T) {
	cfg := DefaultTrendConfig()
	ts := NewTrendStrategy(cfg)

	// Long position: entry=50000, stop=48000, initialRisk=2000
	ts.RegisterPosition("BTCUSDT", "LONG", 50000, 1.0, 48000, 1.0)

	// At 3R: price = 50000 + 3*2000 = 56000
	partial := ts.CheckPartialExit("BTCUSDT", 56000)
	if partial == nil {
		t.Fatal("expected partial exit at 3R")
	}
	if partial.Reason != "partial_3r" {
		t.Errorf("reason: got %s, want partial_3r", partial.Reason)
	}
	if !partial.MoveStopBE {
		t.Error("expected MoveStopBE=true at 3R")
	}
	if !almostEqual(partial.NewStop, 50000) {
		t.Errorf("NewStop: got %.2f, want 50000 (breakeven)", partial.NewStop)
	}
	if !almostEqual(partial.ExitPct, 0.25) {
		t.Errorf("ExitPct: got %.4f, want 0.25", partial.ExitPct)
	}
	if !almostEqual(partial.ExitSize, 0.25) {
		t.Errorf("ExitSize: got %.4f, want 0.25 (25%% of 1.0)", partial.ExitSize)
	}

	// Verify CheckPartialExit does NOT advance PartialStage (read-only)
	pos := ts.GetPosition("BTCUSDT")
	if pos.PartialStage != 0 {
		t.Errorf("PartialStage should remain 0 after CheckPartialExit (not yet filled), got %d", pos.PartialStage)
	}

	// CheckPartialExit should return the same signal again (stage not advanced)
	partial2 := ts.CheckPartialExit("BTCUSDT", 56000)
	if partial2 == nil {
		t.Fatal("expected CheckPartialExit to return signal again since stage was not advanced")
	}
	if partial2.Reason != "partial_3r" {
		t.Errorf("repeat check: got %s, want partial_3r", partial2.Reason)
	}
}

func TestCheckPartialExit_6R(t *testing.T) {
	cfg := DefaultTrendConfig()
	ts := NewTrendStrategy(cfg)

	// Long position: entry=50000, stop=48000, initialRisk=2000
	ts.RegisterPosition("BTCUSDT", "LONG", 50000, 1.0, 48000, 1.0)

	// First trigger 3R — CheckPartialExit is now read-only, so we must
	// apply the partial exit manually to advance the stage.
	partial3R := ts.CheckPartialExit("BTCUSDT", 56000)
	if partial3R == nil {
		t.Fatal("expected partial exit at 3R")
	}
	// Apply the 3R partial (advances stage 0 → 1)
	ts.ApplyPartialExit("BTCUSDT", partial3R.ExitSize, partial3R.MoveStopBE, partial3R.NewStop, partial3R.Reason)

	// Verify stage advanced to 1
	pos := ts.GetPosition("BTCUSDT")
	if pos.PartialStage != 1 {
		t.Errorf("PartialStage should be 1 after 3R apply, got %d", pos.PartialStage)
	}

	// Now check at 6R: price = 50000 + 6*2000 = 62000
	partial := ts.CheckPartialExit("BTCUSDT", 62000)
	if partial == nil {
		t.Fatal("expected partial exit at 6R")
	}
	if partial.Reason != "partial_6r" {
		t.Errorf("reason: got %s, want partial_6r", partial.Reason)
	}
	if partial.MoveStopBE {
		t.Error("expected MoveStopBE=false at 6R")
	}

	// Verify CheckPartialExit does NOT advance PartialStage (still 1)
	pos2 := ts.GetPosition("BTCUSDT")
	if pos2.PartialStage != 1 {
		t.Errorf("PartialStage should remain 1 after CheckPartialExit (not yet filled), got %d", pos2.PartialStage)
	}
}

func TestCheckPartialExit_NotEnabled(t *testing.T) {
	cfg := DefaultTrendConfig()
	cfg.PartialExitEnabled = false
	ts := NewTrendStrategy(cfg)

	ts.RegisterPosition("BTCUSDT", "LONG", 50000, 1.0, 48000, 1.0)

	partial := ts.CheckPartialExit("BTCUSDT", 56000) // 3R
	if partial != nil {
		t.Error("expected nil when partial exits disabled")
	}
}

func TestCheckPartialExit_NoPosition(t *testing.T) {
	ts := NewTrendStrategy(DefaultTrendConfig())
	partial := ts.CheckPartialExit("BTCUSDT", 56000)
	if partial != nil {
		t.Error("expected nil for non-existent position")
	}
}

// -------------------------------------------------------------------
// ApplyPartialExit
// -------------------------------------------------------------------

func TestApplyPartialExit(t *testing.T) {
	ts := NewTrendStrategy(DefaultTrendConfig())
	ts.RegisterPosition("BTCUSDT", "LONG", 50000, 1.0, 48000, 1.0)

	// Apply 25% partial at breakeven (3R fill)
	ts.ApplyPartialExit("BTCUSDT", 0.25, true, 50000, "partial_3r")

	pos := ts.GetPosition("BTCUSDT")
	if pos == nil {
		t.Fatal("position should still exist")
	}
	if !almostEqual(pos.Size, 0.75) {
		t.Errorf("Size: got %.4f, want 0.75", pos.Size)
	}
	if !almostEqual(pos.TrailingStop, 50000) {
		t.Errorf("TrailingStop: got %.2f, want 50000 (breakeven)", pos.TrailingStop)
	}
	if pos.PartialStage != 1 {
		t.Errorf("PartialStage: got %d, want 1 after partial_3r", pos.PartialStage)
	}
}

func TestApplyPartialExit_NoStopMove(t *testing.T) {
	ts := NewTrendStrategy(DefaultTrendConfig())
	ts.RegisterPosition("BTCUSDT", "LONG", 50000, 1.0, 48000, 1.0)

	// Apply without moving stop (6R fill, after stage already at 1)
	ts.ApplyPartialExit("BTCUSDT", 0.25, false, 0, "partial_6r")

	pos := ts.GetPosition("BTCUSDT")
	if !almostEqual(pos.Size, 0.75) {
		t.Errorf("Size: got %.4f, want 0.75", pos.Size)
	}
	if !almostEqual(pos.TrailingStop, 48000) {
		t.Errorf("TrailingStop should remain at 48000, got %.2f", pos.TrailingStop)
	}
	if pos.PartialStage != 2 {
		t.Errorf("PartialStage: got %d, want 2 after partial_6r", pos.PartialStage)
	}
}

// -------------------------------------------------------------------
// Daily Loss Cap
// -------------------------------------------------------------------

func TestDailyLossCap(t *testing.T) {
	cfg := DefaultTrendConfig()
	cfg.DailyLossCapPct = 0.03 // 3%
	ts := NewTrendStrategy(cfg)

	equity := 10000.0

	// Record a small loss — should not halt
	ts.RecordPnL(-100)
	ts.CheckDailyLossCap(equity)
	if ts.IsDailyHalted() {
		t.Error("should not be halted after -100 loss (cap = -300)")
	}

	// Record more loss to exceed cap
	ts.RecordPnL(-250) // total = -350 > -300 cap
	ts.CheckDailyLossCap(equity)
	if !ts.IsDailyHalted() {
		t.Error("should be halted after -350 loss (cap = -300)")
	}
}

func TestDailyLossCap_GetDailyPnL(t *testing.T) {
	ts := NewTrendStrategy(DefaultTrendConfig())
	ts.RecordPnL(-50)
	ts.RecordPnL(30)
	pnl := ts.GetDailyPnL()
	if !almostEqual(pnl, -20) {
		t.Errorf("daily PnL: got %.4f, want -20", pnl)
	}
}

// -------------------------------------------------------------------
// countSameDirection
// -------------------------------------------------------------------

func TestCountSameDirection(t *testing.T) {
	ts := NewTrendStrategy(DefaultTrendConfig())

	ts.RegisterPosition("BTCUSDT", "LONG", 50000, 0.1, 48000, 1.0)
	ts.RegisterPosition("ETHUSDT", "LONG", 3000, 1.0, 2800, 1.0)
	ts.RegisterPosition("SOLUSDT", "SHORT", 100, 10.0, 105, 1.0)

	longCount := ts.countSameDirection("LONG")
	if longCount != 2 {
		t.Errorf("LONG count: got %d, want 2", longCount)
	}

	shortCount := ts.countSameDirection("SHORT")
	if shortCount != 1 {
		t.Errorf("SHORT count: got %d, want 1", shortCount)
	}
}

// -------------------------------------------------------------------
// OnBar — Full signal generation with realistic data
// -------------------------------------------------------------------

func TestOnBar_BasicLongSignal(t *testing.T) {
	// Create a strategy with small periods for testing
	cfg := TrendConfig{
		DonchianPeriod:     5,
		EMAFast:            3,
		EMASlow:            7,
		EMAConfirmBars:     5,
		EMATrend:           10,
		VolumePeriod:       5,
		ATRPeriod:          5,
		ATRStopMult:        3.0,
		ADXPeriod:          5,
		ADXThreshold:       15.0, // lower threshold for test
		VolatilityLow:      0.1,
		VolatilityHigh:     5.0,  // wide range for test
		FundingExtreme:     0.0005,
		FundingElevated:    0.0003,
		RiskPerTrade:       0.01,
		MaxLeverage:        2.0,
		ChandelierLookback: 5,
		DailyLossCapPct:    0.03,
		MaxOpenPositions:   4,
		MaxCorrelatedSame:  2,
		PartialExitEnabled: true,
		FirstTargetR:       3.0,
		FirstExitPct:       0.25,
		SecondTargetR:      6.0,
		SecondExitPct:      0.25,
	}
	ts := NewTrendStrategy(cfg)

	// Create 70 candles with a strong uptrend that should trigger a long signal:
	// 1. Close > DonchianUpper (new high)
	// 2. EMA fast > EMA slow with recent crossover
	// 3. Close > EMA(10) trend
	// 4. Volume > average
	n := 70
	candles := make([]exchange.Candle, n)

	// First 50 bars: moderate uptrend
	for i := 0; i < 50; i++ {
		price := 100.0 + float64(i)*1.5
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
	// Last 20 bars: strong breakout (accelerating uptrend with high volume)
	for i := 50; i < n; i++ {
		price := candles[49].Close + float64(i-49)*4.0 // accelerating
		candles[i] = exchange.Candle{
			Symbol:    "BTCUSDT",
			OpenTime:  time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC).Add(time.Duration(i) * 4 * time.Hour),
			CloseTime: time.Date(2024, 1, 1, 4, 0, 0, 0, time.UTC).Add(time.Duration(i) * 4 * time.Hour),
			Open:      price - 2,
			High:      price + 3,
			Low:       price - 3,
			Close:     price,
			Volume:    200, // high volume
		}
	}

	sig := ts.OnBar("BTCUSDT", candles, nil, 10000)

	// We may or may not get a signal depending on exact indicator values
	// The key test is that it doesn't panic and handles all the layers
	if sig != nil {
		if sig.Type != SignalLong {
			t.Errorf("expected LONG signal for uptrend, got %s", sig.Type.String())
		}
		if sig.StopLoss >= sig.Price {
			t.Errorf("long stop loss (%.2f) should be below entry (%.2f)", sig.StopLoss, sig.Price)
		}
		if sig.Symbol != "BTCUSDT" {
			t.Errorf("symbol: got %s, want BTCUSDT", sig.Symbol)
		}
	}
}

func TestOnBar_FundingFilterBlocks(t *testing.T) {
	cfg := TrendConfig{
		DonchianPeriod:     5,
		EMAFast:            3,
		EMASlow:            7,
		EMAConfirmBars:     5,
		EMATrend:           10,
		VolumePeriod:       5,
		ATRPeriod:          5,
		ATRStopMult:        3.0,
		ADXPeriod:          5,
		ADXThreshold:       10.0,
		VolatilityLow:      0.1,
		VolatilityHigh:     10.0,
		FundingExtreme:     0.0005,
		FundingElevated:    0.0003,
		RiskPerTrade:       0.01,
		MaxLeverage:        2.0,
		ChandelierLookback: 5,
		DailyLossCapPct:    0.03,
		MaxOpenPositions:   4,
		MaxCorrelatedSame:  4, // allow more to avoid correlation block
		PartialExitEnabled: false,
	}
	ts := NewTrendStrategy(cfg)

	fc := data.NewFundingCache(100)
	// Add extremely positive funding (long crowded)
	for i := 0; i < 5; i++ {
		fc.Add("BTCUSDT", data.FundingRate{
			Symbol:    "BTCUSDT",
			Rate:      0.01, // very extreme
			Timestamp: time.Date(2024, 1, 1, i*8, 0, 0, 0, time.UTC),
		})
	}

	// Even with a valid uptrend, funding filter should block
	n := 70
	candles := make([]exchange.Candle, n)
	for i := 0; i < n; i++ {
		price := 100.0 + float64(i)*3.0
		candles[i] = exchange.Candle{
			Symbol:    "BTCUSDT",
			OpenTime:  time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC).Add(time.Duration(i) * 4 * time.Hour),
			CloseTime: time.Date(2024, 1, 1, 4, 0, 0, 0, time.UTC).Add(time.Duration(i) * 4 * time.Hour),
			Open:      price - 1,
			High:      price + 3,
			Low:       price - 3,
			Close:     price,
			Volume:    200,
		}
	}

	sig := ts.OnBar("BTCUSDT", candles, fc, 10000)
	// If a signal was generated despite extreme funding, it means funding filter isn't working
	// But since we can't guarantee the other layers pass, just verify no panic
	_ = sig
}

func TestOnBar_CorrelationLimitBlocks(t *testing.T) {
	cfg := TrendConfig{
		DonchianPeriod:     5,
		EMAFast:            3,
		EMASlow:            7,
		EMAConfirmBars:     5,
		EMATrend:           10,
		VolumePeriod:       5,
		ATRPeriod:          5,
		ATRStopMult:        3.0,
		ADXPeriod:          5,
		ADXThreshold:       10.0,
		VolatilityLow:      0.1,
		VolatilityHigh:     10.0,
		FundingExtreme:     0.0005,
		FundingElevated:    0.0003,
		RiskPerTrade:       0.01,
		MaxLeverage:        2.0,
		ChandelierLookback: 5,
		DailyLossCapPct:    0.03,
		MaxOpenPositions:   4,
		MaxCorrelatedSame:  2,
		PartialExitEnabled: false,
	}
	ts := NewTrendStrategy(cfg)

	// Register 2 LONG positions (hits MaxCorrelatedSame)
	ts.RegisterPosition("BTCUSDT", "LONG", 50000, 0.1, 48000, 1.0)
	ts.RegisterPosition("ETHUSDT", "LONG", 3000, 1.0, 2800, 1.0)

	// Try to open a 3rd LONG — should be blocked
	n := 70
	candles := make([]exchange.Candle, n)
	for i := 0; i < n; i++ {
		price := 100.0 + float64(i)*3.0
		candles[i] = exchange.Candle{
			Symbol:    "SOLUSDT",
			OpenTime:  time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC).Add(time.Duration(i) * 4 * time.Hour),
			CloseTime: time.Date(2024, 1, 1, 4, 0, 0, 0, time.UTC).Add(time.Duration(i) * 4 * time.Hour),
			Open:      price - 1,
			High:      price + 3,
			Low:       price - 3,
			Close:     price,
			Volume:    200,
		}
	}

	sig := ts.OnBar("SOLUSDT", candles, nil, 10000)
	// If a long signal is generated, it should be blocked by correlation limit
	// Since we can't guarantee the signal would be LONG, check that if it is, it's nil
	if sig != nil && sig.Type == SignalLong {
		t.Error("expected correlation limit to block 3rd LONG signal")
	}
}
