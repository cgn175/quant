package data

import (
	"sort"
	"sync"
	"time"
)

// FundingRate represents a single funding rate snapshot.
type FundingRate struct {
	Symbol    string
	Rate      float64
	Timestamp time.Time
}

// FundingCache stores funding rates per symbol and provides thread-safe
// access to moving averages and extreme-detection helpers.
type FundingCache struct {
	mu      sync.RWMutex
	rates   map[string][]FundingRate // symbol -> sorted by timestamp (oldest first)
	maxSize int                      // max rates to keep per symbol
}

// NewFundingCache creates a new FundingCache. maxSize limits how many rates
// are retained per symbol (FIFO eviction). A reasonable default is 100
// (~33 days at 8h intervals).
func NewFundingCache(maxSize int) *FundingCache {
	return &FundingCache{
		rates:   make(map[string][]FundingRate),
		maxSize: maxSize,
	}
}

// Add appends a funding rate for the given symbol. Rates are kept sorted
// by timestamp. Duplicates (same timestamp) are silently skipped.
func (fc *FundingCache) Add(symbol string, rate FundingRate) {
	fc.mu.Lock()
	defer fc.mu.Unlock()

	rates := fc.rates[symbol]

	// Skip duplicate timestamp
	for _, r := range rates {
		if r.Timestamp.Equal(rate.Timestamp) {
			return
		}
	}

	rates = append(rates, rate)

	// Keep sorted by timestamp
	sort.Slice(rates, func(i, j int) bool {
		return rates[i].Timestamp.Before(rates[j].Timestamp)
	})

	// Evict oldest if over maxSize
	if len(rates) > fc.maxSize {
		rates = rates[len(rates)-fc.maxSize:]
	}

	fc.rates[symbol] = rates
}

// Latest returns the most recent funding rate for a symbol.
// Returns 0 and false if no rates exist.
func (fc *FundingCache) Latest(symbol string) (float64, bool) {
	fc.mu.RLock()
	defer fc.mu.RUnlock()

	rates := fc.rates[symbol]
	if len(rates) == 0 {
		return 0, false
	}
	return rates[len(rates)-1].Rate, true
}

// MovingAverage computes the simple moving average of the last `periods`
// funding rates for the given symbol. Returns 0 if no rates exist.
// If fewer than `periods` rates exist, averages all available.
func (fc *FundingCache) MovingAverage(symbol string, periods int) float64 {
	fc.mu.RLock()
	defer fc.mu.RUnlock()

	rates := fc.rates[symbol]
	if len(rates) == 0 || periods <= 0 {
		return 0
	}

	n := periods
	if n > len(rates) {
		n = len(rates)
	}

	sum := 0.0
	start := len(rates) - n
	for i := start; i < len(rates); i++ {
		sum += rates[i].Rate
	}

	return sum / float64(n)
}

// IsExtreme returns true if the absolute value of the moving average
// (last 3 rates ≈ 24h context) exceeds the threshold.
func (fc *FundingCache) IsExtreme(symbol string, threshold float64) bool {
	avg := fc.MovingAverage(symbol, 3)
	if avg < 0 {
		return -avg > threshold
	}
	return avg > threshold
}

// IsLongCrowded returns true if the moving average (last 3 rates) is
// positive and exceeds the threshold — meaning the market is extremely long.
func (fc *FundingCache) IsLongCrowded(symbol string, threshold float64) bool {
	avg := fc.MovingAverage(symbol, 3)
	return avg > threshold
}

// IsShortCrowded returns true if the moving average (last 3 rates) is
// negative and its absolute value exceeds the threshold — meaning the
// market is extremely short.
func (fc *FundingCache) IsShortCrowded(symbol string, threshold float64) bool {
	avg := fc.MovingAverage(symbol, 3)
	return avg < -threshold
}

// SizeMultiplier returns 0.5 if the absolute moving average exceeds
// `elevated` (but is not necessarily extreme), otherwise 1.0.
func (fc *FundingCache) SizeMultiplier(symbol string, elevated float64) float64 {
	avg := fc.MovingAverage(symbol, 3)
	if avg < 0 {
		avg = -avg
	}
	if avg > elevated {
		return 0.5
	}
	return 1.0
}

// Len returns the number of stored rates for a symbol.
func (fc *FundingCache) Len(symbol string) int {
	fc.mu.RLock()
	defer fc.mu.RUnlock()
	return len(fc.rates[symbol])
}
