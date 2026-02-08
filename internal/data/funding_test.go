package data

import (
	"fmt"
	"sync"
	"testing"
	"time"
)

func TestNewFundingCache(t *testing.T) {
	fc := NewFundingCache(50)
	if fc == nil {
		t.Fatal("expected non-nil cache")
	}
}

func TestAdd_Basic(t *testing.T) {
	fc := NewFundingCache(100)
	fc.Add("BTCUSDT", FundingRate{
		Symbol:    "BTCUSDT",
		Rate:      0.0001,
		Timestamp: time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC),
	})
	if fc.Len("BTCUSDT") != 1 {
		t.Errorf("expected Len=1, got %d", fc.Len("BTCUSDT"))
	}

	fc.Add("BTCUSDT", FundingRate{
		Symbol:    "BTCUSDT",
		Rate:      0.0002,
		Timestamp: time.Date(2024, 1, 1, 8, 0, 0, 0, time.UTC),
	})
	if fc.Len("BTCUSDT") != 2 {
		t.Errorf("expected Len=2, got %d", fc.Len("BTCUSDT"))
	}
}

func TestAdd_DuplicateTimestamp(t *testing.T) {
	fc := NewFundingCache(100)
	ts := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)

	fc.Add("BTCUSDT", FundingRate{Symbol: "BTCUSDT", Rate: 0.0001, Timestamp: ts})
	fc.Add("BTCUSDT", FundingRate{Symbol: "BTCUSDT", Rate: 0.0002, Timestamp: ts})

	if fc.Len("BTCUSDT") != 1 {
		t.Errorf("duplicate timestamp should be skipped, got Len=%d", fc.Len("BTCUSDT"))
	}
}

func TestAdd_Eviction(t *testing.T) {
	fc := NewFundingCache(3)

	for i := 0; i < 5; i++ {
		fc.Add("BTCUSDT", FundingRate{
			Symbol:    "BTCUSDT",
			Rate:      float64(i) * 0.0001,
			Timestamp: time.Date(2024, 1, 1, i*8, 0, 0, 0, time.UTC),
		})
	}

	if fc.Len("BTCUSDT") != 3 {
		t.Errorf("expected Len=3 after eviction, got %d", fc.Len("BTCUSDT"))
	}

	// Latest should be the most recent one
	latest, ok := fc.Latest("BTCUSDT")
	if !ok {
		t.Fatal("expected Latest to return true")
	}
	if latest != 0.0004 {
		t.Errorf("expected latest=0.0004, got %.4f", latest)
	}
}

func TestAdd_SortedOrder(t *testing.T) {
	fc := NewFundingCache(100)

	// Add out of order
	fc.Add("BTCUSDT", FundingRate{Symbol: "BTCUSDT", Rate: 0.0003, Timestamp: time.Date(2024, 1, 1, 16, 0, 0, 0, time.UTC)})
	fc.Add("BTCUSDT", FundingRate{Symbol: "BTCUSDT", Rate: 0.0001, Timestamp: time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)})
	fc.Add("BTCUSDT", FundingRate{Symbol: "BTCUSDT", Rate: 0.0002, Timestamp: time.Date(2024, 1, 1, 8, 0, 0, 0, time.UTC)})

	latest, ok := fc.Latest("BTCUSDT")
	if !ok {
		t.Fatal("expected Latest to return true")
	}
	if latest != 0.0003 {
		t.Errorf("expected latest=0.0003 (most recent by timestamp), got %.4f", latest)
	}
}

func TestLatest_Empty(t *testing.T) {
	fc := NewFundingCache(100)
	rate, ok := fc.Latest("BTCUSDT")
	if ok {
		t.Fatal("expected ok=false for empty cache")
	}
	if rate != 0 {
		t.Errorf("expected rate=0, got %.4f", rate)
	}
}

func TestLatest_WithData(t *testing.T) {
	fc := NewFundingCache(100)
	fc.Add("BTCUSDT", FundingRate{Symbol: "BTCUSDT", Rate: 0.0001, Timestamp: time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)})
	fc.Add("BTCUSDT", FundingRate{Symbol: "BTCUSDT", Rate: 0.0005, Timestamp: time.Date(2024, 1, 1, 8, 0, 0, 0, time.UTC)})

	rate, ok := fc.Latest("BTCUSDT")
	if !ok {
		t.Fatal("expected ok=true")
	}
	if rate != 0.0005 {
		t.Errorf("expected rate=0.0005, got %.4f", rate)
	}
}

func TestMovingAverage_Basic(t *testing.T) {
	fc := NewFundingCache(100)
	// Add 5 rates: 0.0001, 0.0002, 0.0003, 0.0004, 0.0005
	for i := 1; i <= 5; i++ {
		fc.Add("BTCUSDT", FundingRate{
			Symbol:    "BTCUSDT",
			Rate:      float64(i) * 0.0001,
			Timestamp: time.Date(2024, 1, 1, i*8, 0, 0, 0, time.UTC),
		})
	}

	// MA(3) = (0.0003 + 0.0004 + 0.0005) / 3 = 0.0004
	avg := fc.MovingAverage("BTCUSDT", 3)
	expected := 0.0004
	if diff := avg - expected; diff < -0.00001 || diff > 0.00001 {
		t.Errorf("MA(3): got %.6f, want %.6f", avg, expected)
	}
}

func TestMovingAverage_FewerThanRequested(t *testing.T) {
	fc := NewFundingCache(100)
	fc.Add("BTCUSDT", FundingRate{Symbol: "BTCUSDT", Rate: 0.0002, Timestamp: time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)})
	fc.Add("BTCUSDT", FundingRate{Symbol: "BTCUSDT", Rate: 0.0004, Timestamp: time.Date(2024, 1, 1, 8, 0, 0, 0, time.UTC)})

	// Request MA(10) with only 2 rates → average all 2
	avg := fc.MovingAverage("BTCUSDT", 10)
	expected := 0.0003 // (0.0002 + 0.0004) / 2
	if diff := avg - expected; diff < -0.00001 || diff > 0.00001 {
		t.Errorf("MA(10) with 2 rates: got %.6f, want %.6f", avg, expected)
	}
}

func TestMovingAverage_ZeroPeriods(t *testing.T) {
	fc := NewFundingCache(100)
	fc.Add("BTCUSDT", FundingRate{Symbol: "BTCUSDT", Rate: 0.0005, Timestamp: time.Now()})

	avg := fc.MovingAverage("BTCUSDT", 0)
	if avg != 0 {
		t.Errorf("MA(0): expected 0, got %.6f", avg)
	}
}

func TestMovingAverage_Empty(t *testing.T) {
	fc := NewFundingCache(100)
	avg := fc.MovingAverage("BTCUSDT", 3)
	if avg != 0 {
		t.Errorf("MA on empty: expected 0, got %.6f", avg)
	}
}

func TestIsExtreme(t *testing.T) {
	fc := NewFundingCache(100)
	// Add 3 rates with positive avg > 0.0005
	for i := 0; i < 3; i++ {
		fc.Add("BTCUSDT", FundingRate{
			Symbol:    "BTCUSDT",
			Rate:      0.001,
			Timestamp: time.Date(2024, 1, 1, i*8, 0, 0, 0, time.UTC),
		})
	}

	if !fc.IsExtreme("BTCUSDT", 0.0005) {
		t.Error("expected IsExtreme=true for avg=0.001 > threshold=0.0005")
	}
	if fc.IsExtreme("BTCUSDT", 0.01) {
		t.Error("expected IsExtreme=false for avg=0.001 < threshold=0.01")
	}

	// Negative extreme
	fc2 := NewFundingCache(100)
	for i := 0; i < 3; i++ {
		fc2.Add("ETHUSDT", FundingRate{
			Symbol:    "ETHUSDT",
			Rate:      -0.001,
			Timestamp: time.Date(2024, 1, 1, i*8, 0, 0, 0, time.UTC),
		})
	}
	if !fc2.IsExtreme("ETHUSDT", 0.0005) {
		t.Error("expected IsExtreme=true for negative extreme")
	}
}

func TestIsLongCrowded(t *testing.T) {
	fc := NewFundingCache(100)
	for i := 0; i < 3; i++ {
		fc.Add("BTCUSDT", FundingRate{
			Symbol:    "BTCUSDT",
			Rate:      0.001,
			Timestamp: time.Date(2024, 1, 1, i*8, 0, 0, 0, time.UTC),
		})
	}

	if !fc.IsLongCrowded("BTCUSDT", 0.0005) {
		t.Error("expected IsLongCrowded=true for positive avg > threshold")
	}
	if fc.IsLongCrowded("BTCUSDT", 0.01) {
		t.Error("expected IsLongCrowded=false for positive avg < threshold")
	}

	// Negative rates should NOT be long crowded
	fc2 := NewFundingCache(100)
	for i := 0; i < 3; i++ {
		fc2.Add("BTCUSDT", FundingRate{
			Symbol:    "BTCUSDT",
			Rate:      -0.001,
			Timestamp: time.Date(2024, 1, 1, i*8, 0, 0, 0, time.UTC),
		})
	}
	if fc2.IsLongCrowded("BTCUSDT", 0.0005) {
		t.Error("negative avg should not be long crowded")
	}
}

func TestIsShortCrowded(t *testing.T) {
	fc := NewFundingCache(100)
	for i := 0; i < 3; i++ {
		fc.Add("BTCUSDT", FundingRate{
			Symbol:    "BTCUSDT",
			Rate:      -0.001,
			Timestamp: time.Date(2024, 1, 1, i*8, 0, 0, 0, time.UTC),
		})
	}

	if !fc.IsShortCrowded("BTCUSDT", 0.0005) {
		t.Error("expected IsShortCrowded=true for negative avg < -threshold")
	}
	if fc.IsShortCrowded("BTCUSDT", 0.01) {
		t.Error("expected IsShortCrowded=false for negative avg > -threshold")
	}

	// Positive rates should NOT be short crowded
	fc2 := NewFundingCache(100)
	for i := 0; i < 3; i++ {
		fc2.Add("BTCUSDT", FundingRate{
			Symbol:    "BTCUSDT",
			Rate:      0.001,
			Timestamp: time.Date(2024, 1, 1, i*8, 0, 0, 0, time.UTC),
		})
	}
	if fc2.IsShortCrowded("BTCUSDT", 0.0005) {
		t.Error("positive avg should not be short crowded")
	}
}

func TestSizeMultiplier(t *testing.T) {
	fc := NewFundingCache(100)

	// Elevated: |avg| > 0.0003
	for i := 0; i < 3; i++ {
		fc.Add("BTCUSDT", FundingRate{
			Symbol:    "BTCUSDT",
			Rate:      0.0005,
			Timestamp: time.Date(2024, 1, 1, i*8, 0, 0, 0, time.UTC),
		})
	}
	mult := fc.SizeMultiplier("BTCUSDT", 0.0003)
	if mult != 0.5 {
		t.Errorf("expected SizeMultiplier=0.5 for elevated funding, got %.2f", mult)
	}

	// Normal: |avg| < 0.0003
	fc2 := NewFundingCache(100)
	for i := 0; i < 3; i++ {
		fc2.Add("BTCUSDT", FundingRate{
			Symbol:    "BTCUSDT",
			Rate:      0.0001,
			Timestamp: time.Date(2024, 1, 1, i*8, 0, 0, 0, time.UTC),
		})
	}
	mult2 := fc2.SizeMultiplier("BTCUSDT", 0.0003)
	if mult2 != 1.0 {
		t.Errorf("expected SizeMultiplier=1.0 for normal funding, got %.2f", mult2)
	}

	// Negative elevated
	fc3 := NewFundingCache(100)
	for i := 0; i < 3; i++ {
		fc3.Add("BTCUSDT", FundingRate{
			Symbol:    "BTCUSDT",
			Rate:      -0.0005,
			Timestamp: time.Date(2024, 1, 1, i*8, 0, 0, 0, time.UTC),
		})
	}
	mult3 := fc3.SizeMultiplier("BTCUSDT", 0.0003)
	if mult3 != 0.5 {
		t.Errorf("expected SizeMultiplier=0.5 for negative elevated funding, got %.2f", mult3)
	}
}

func TestConcurrentAccess(t *testing.T) {
	fc := NewFundingCache(100)
	var wg sync.WaitGroup

	// 10 goroutines writing
	for g := 0; g < 10; g++ {
		wg.Add(1)
		go func(id int) {
			defer wg.Done()
			for i := 0; i < 50; i++ {
				fc.Add("BTCUSDT", FundingRate{
					Symbol:    "BTCUSDT",
					Rate:      float64(id)*0.001 + float64(i)*0.00001,
					Timestamp: time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC).Add(time.Duration(id*1000+i) * time.Minute),
				})
			}
		}(g)
	}

	// 10 goroutines reading
	for g := 0; g < 10; g++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := 0; i < 50; i++ {
				fc.Latest("BTCUSDT")
				fc.MovingAverage("BTCUSDT", 3)
				fc.IsExtreme("BTCUSDT", 0.0005)
				fc.IsLongCrowded("BTCUSDT", 0.0005)
				fc.IsShortCrowded("BTCUSDT", 0.0005)
				fc.SizeMultiplier("BTCUSDT", 0.0003)
				fc.Len("BTCUSDT")
			}
		}()
	}

	wg.Wait()

	// If we get here without panics, the test passes
	n := fc.Len("BTCUSDT")
	if n <= 0 || n > 100 {
		t.Errorf("expected 0 < Len <= 100, got %d", n)
	}
	fmt.Printf("concurrent test: %d rates stored\n", n)
}
