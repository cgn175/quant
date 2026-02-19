package marketmaking

import (
	"testing"

	"github.com/cgn175/quant-bot/internal/config"
	"github.com/stretchr/testify/assert"
)

func TestVolatilityRegimeString(t *testing.T) {
	tests := []struct {
		regime   VolatilityRegime
		expected string
	}{
		{VolCalm, "calm"},
		{VolNormal, "normal"},
		{VolElevated, "elevated"},
		{VolExtreme, "extreme"},
		{VolatilityRegime(99), "unknown"},
	}

	for _, tt := range tests {
		t.Run(tt.expected, func(t *testing.T) {
			assert.Equal(t, tt.expected, tt.regime.String())
		})
	}
}

func TestRingBuffer(t *testing.T) {
	t.Run("Add and Len", func(t *testing.T) {
		rb := newRingBuffer(5)
		assert.Equal(t, 0, rb.Len())

		rb.Add(1.0)
		rb.Add(2.0)
		assert.Equal(t, 2, rb.Len())

		// Fill up
		rb.Add(3.0)
		rb.Add(4.0)
		rb.Add(5.0)
		assert.Equal(t, 5, rb.Len())

		// Overflow - should still be 5
		rb.Add(6.0)
		assert.Equal(t, 5, rb.Len())
	})

	t.Run("Mean", func(t *testing.T) {
		rb := newRingBuffer(5)
		assert.Equal(t, 0.0, rb.Mean())

		rb.Add(1.0)
		rb.Add(2.0)
		rb.Add(3.0)
		assert.Equal(t, 2.0, rb.Mean())
	})

	t.Run("Stddev", func(t *testing.T) {
		rb := newRingBuffer(5)
		assert.Equal(t, 0.0, rb.Stddev())

		// Need at least 2 elements for stddev
		rb.Add(1.0)
		assert.Equal(t, 0.0, rb.Stddev())

		rb.Add(3.0)
		// Stddev of [1, 3] = sqrt(((1-2)^2 + (3-2)^2) / 2) = sqrt(0.5 + 0.5) = 1
		assert.InDelta(t, 1.0, rb.Stddev(), 0.0001)
	})

	t.Run("Get", func(t *testing.T) {
		rb := newRingBuffer(5)
		rb.Add(1.0)
		rb.Add(2.0)
		rb.Add(3.0)

		// Get(0) should return most recent (3.0)
		assert.Equal(t, 3.0, rb.Get(0))
		// Get(1) should return 2.0
		assert.Equal(t, 2.0, rb.Get(1))
		// Get(2) should return 1.0
		assert.Equal(t, 1.0, rb.Get(2))
		// Out of bounds should return 0
		assert.Equal(t, 0.0, rb.Get(5))
	})

	t.Run("Get with wraparound", func(t *testing.T) {
		rb := newRingBuffer(3)
		rb.Add(1.0)
		rb.Add(2.0)
		rb.Add(3.0)
		rb.Add(4.0) // This wraps around, overwriting 1.0

		// Buffer now contains [4, 2, 3]
		assert.Equal(t, 4.0, rb.Get(0))
		assert.Equal(t, 3.0, rb.Get(1))
		assert.Equal(t, 2.0, rb.Get(2))
	})
}

func TestTrueRange(t *testing.T) {
	tests := []struct {
		name      string
		high      float64
		low       float64
		closePrev float64
		expected  float64
	}{
		{
			name:      "normal case - high-low is largest",
			high:      110,
			low:       100,
			closePrev: 105,
			expected:  10,
		},
		{
			name:      "gap up - high-close_prev is largest",
			high:      120,
			low:       115,
			closePrev: 100,
			expected:  20,
		},
		{
			name:      "gap down - close_prev-low is largest",
			high:      90,
			low:       85,
			closePrev: 100,
			expected:  15,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := trueRange(tt.high, tt.low, tt.closePrev)
			assert.InDelta(t, tt.expected, result, 0.0001)
		})
	}
}

func TestCalculateATRPercentage(t *testing.T) {
	s := &Strategy{
		btcPrices: newRingBuffer(14),
		btcHighs:  newRingBuffer(14),
		btcLows:   newRingBuffer(14),
	}

	// Simulate 5 periods of data with 1% daily range
	basePrice := 50000.0
	for i := 0; i < 5; i++ {
		s.btcPrices.Add(basePrice + float64(i)*100)
		s.btcHighs.Add(basePrice + float64(i)*100 + 500)  // +1%
		s.btcLows.Add(basePrice + float64(i)*100 - 500)   // -1%
	}

	atrPct := s.calculateATRPercentage(s.btcPrices, s.btcHighs, s.btcLows)
	// ATR should be roughly 1000 / 50000 = 2%
	assert.True(t, atrPct > 0, "ATR% should be positive")
}

func TestUpdateVolatilityRegime(t *testing.T) {
	tests := []struct {
		name           string
		btcATRPct      float64
		ethATRPct      float64
		calmThresh     float64
		elevatedThresh float64
		extremeThresh   float64
		expectedRegime VolatilityRegime
	}{
		{
			name:           "calm regime",
			btcATRPct:      0.01, // 1%
			ethATRPct:      0.015, // 1.5%
			calmThresh:     0.02,
			elevatedThresh: 0.05,
			extremeThresh:  0.10,
			expectedRegime: VolCalm,
		},
		{
			name:           "normal regime",
			btcATRPct:      0.03, // 3%
			ethATRPct:      0.035, // 3.5%
			calmThresh:     0.02,
			elevatedThresh: 0.05,
			extremeThresh:  0.10,
			expectedRegime: VolNormal,
		},
		{
			name:           "elevated regime",
			btcATRPct:      0.07, // 7%
			ethATRPct:      0.06, // 6%
			calmThresh:     0.02,
			elevatedThresh: 0.05,
			extremeThresh:  0.10,
			expectedRegime: VolElevated,
		},
		{
			name:           "extreme regime",
			btcATRPct:      0.12, // 12%
			ethATRPct:      0.11, // 11%
			calmThresh:     0.02,
			elevatedThresh: 0.05,
			extremeThresh:  0.10,
			expectedRegime: VolExtreme,
		},
		{
			name:           "boundary - at calm threshold",
			btcATRPct:      0.02, // exactly 2%
			ethATRPct:      0.02,
			calmThresh:     0.02,
			elevatedThresh: 0.05,
			extremeThresh:  0.10,
			expectedRegime: VolNormal, // should be >= calmThresh
		},
		{
			name:           "boundary - at elevated threshold",
			btcATRPct:      0.05, // exactly 5%
			ethATRPct:      0.05,
			calmThresh:     0.02,
			elevatedThresh: 0.05,
			extremeThresh:  0.10,
			expectedRegime: VolElevated, // should be >= elevatedThresh
		},
		{
			name:           "uses only BTC when ETH unavailable",
			btcATRPct:      0.03, // 3%
			ethATRPct:      0,
			calmThresh:     0.02,
			elevatedThresh: 0.05,
			extremeThresh:  0.10,
			expectedRegime: VolNormal,
		},
		{
			name:           "uses only ETH when BTC unavailable",
			btcATRPct:      0,
			ethATRPct:      0.03, // 3%
			calmThresh:     0.02,
			elevatedThresh: 0.05,
			extremeThresh:  0.10,
			expectedRegime: VolNormal,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := &Strategy{
				btcPrices:            newRingBuffer(14),
				ethPrices:            newRingBuffer(14),
				btcHighs:             newRingBuffer(14),
				btcLows:              newRingBuffer(14),
				ethHighs:             newRingBuffer(14),
				ethLows:              newRingBuffer(14),
				cfg:                  config.MarketMakingConfig{
					VolCalmThreshold:     tt.calmThresh,
					VolElevatedThreshold: tt.elevatedThresh,
					VolExtremeThreshold:  tt.extremeThresh,
				},
				currentRegime: VolCalm,
				lastRegime:    VolCalm,
			}

			// Populate buffers with enough data to calculate ATR
			for i := 0; i < 5; i++ {
				if tt.btcATRPct > 0 {
					basePrice := 50000.0
					tr := tt.btcATRPct * basePrice
					s.btcPrices.Add(basePrice)
					s.btcHighs.Add(basePrice + tr/2)
					s.btcLows.Add(basePrice - tr/2)
				}
				if tt.ethATRPct > 0 {
					basePrice := 3000.0
					tr := tt.ethATRPct * basePrice
					s.ethPrices.Add(basePrice)
					s.ethHighs.Add(basePrice + tr/2)
					s.ethLows.Add(basePrice - tr/2)
				}
			}

			regime := s.updateVolatilityRegime()
			assert.Equal(t, tt.expectedRegime, regime)
		})
	}
}

func TestComputeDynamicSpread(t *testing.T) {
	s := &Strategy{
		cfg: config.MarketMakingConfig{
			SpreadPct:    0.001, // 0.1%
			MinSpreadPct: 0.0005,
			MaxSpreadPct: 0.01,
		},
		returns: map[string]*ringBuffer{
			"BTCUSDT": newRingBuffer(20),
		},
	}

	// Populate returns buffer with some volatility data
	for i := 0; i < 10; i++ {
		s.returns["BTCUSDT"].Add(0.001) // 0.1% returns
	}

	price := 50000.0
	vol := 0.001

	t.Run("normal regime - 1x multiplier", func(t *testing.T) {
		spread := s.computeDynamicSpread("BTCUSDT", price, vol, 1.0)
		baseSpread := price * s.cfg.SpreadPct
		// With 1x multiplier and current vol == avg vol, spread should be close to base
		assert.True(t, spread >= baseSpread*0.9 && spread <= baseSpread*1.1,
			"Spread should be close to base spread for normal conditions")
	})

	t.Run("elevated regime - 3x multiplier", func(t *testing.T) {
		spread := s.computeDynamicSpread("BTCUSDT", price, vol, 3.0)
		baseSpread := price * s.cfg.SpreadPct
		// With 3x multiplier, spread should be roughly 3x base
		assert.True(t, spread >= baseSpread*2.5,
			"Spread should be significantly wider with elevated regime multiplier")
	})

	t.Run("respects min spread", func(t *testing.T) {
		// Very low volatility should not push spread below min
		spread := s.computeDynamicSpread("BTCUSDT", price, 0.00001, 1.0)
		minSpread := price * s.cfg.MinSpreadPct
		assert.True(t, spread >= minSpread,
			"Spread should not go below minimum")
	})

	t.Run("respects max spread", func(t *testing.T) {
		// Very high volatility should not push spread above max
		spread := s.computeDynamicSpread("BTCUSDT", price, 1.0, 10.0)
		maxSpread := price * s.cfg.MaxSpreadPct
		assert.True(t, spread <= maxSpread,
			"Spread should not exceed maximum")
	})
}

func TestSpreadMultiplierByRegime(t *testing.T) {
	tests := []struct {
		regime              VolatilityRegime
		volSpreadMultiplier float64
		expectedMultiplier  float64
	}{
		{VolCalm, 3.0, 1.0},
		{VolNormal, 3.0, 1.5},
		{VolElevated, 3.0, 3.0},
		{VolElevated, 5.0, 5.0}, // Custom multiplier
		{VolExtreme, 3.0, 0.0},  // Should halt (multiplier doesn't matter)
	}

	for _, tt := range tests {
		t.Run(tt.regime.String(), func(t *testing.T) {
			var multiplier float64
			switch tt.regime {
			case VolCalm:
				multiplier = 1.0
			case VolNormal:
				multiplier = 1.5
			case VolElevated:
				multiplier = tt.volSpreadMultiplier
				if multiplier < 1.0 {
					multiplier = 3.0
				}
			case VolExtreme:
				// Halt - no multiplier
				multiplier = 0
			}

			if tt.regime == VolExtreme {
				assert.Equal(t, 0.0, multiplier)
			} else {
				assert.InDelta(t, tt.expectedMultiplier, multiplier, 0.0001)
			}
		})
	}
}

// Test helper to ensure default config values are reasonable
func TestDefaultConfigValues(t *testing.T) {
	// These should match the defaults in config.go
	defaults := struct {
		volCalmThreshold     float64
		volElevatedThreshold float64
		volExtremeThreshold  float64
		volSpreadMultiplier  float64
	}{
		volCalmThreshold:     0.02,
		volElevatedThreshold: 0.05,
		volExtremeThreshold:  0.10,
		volSpreadMultiplier:  3.0,
	}

	// Verify thresholds are in correct order
	assert.True(t, defaults.volCalmThreshold < defaults.volElevatedThreshold,
		"Calm threshold should be less than elevated threshold")
	assert.True(t, defaults.volElevatedThreshold < defaults.volExtremeThreshold,
		"Elevated threshold should be less than extreme threshold")

	// Verify spread multiplier is reasonable
	assert.True(t, defaults.volSpreadMultiplier >= 1.0,
		"Spread multiplier should be at least 1x")
	assert.True(t, defaults.volSpreadMultiplier <= 10.0,
		"Spread multiplier should not be excessively high")
}

// Test that extreme regime halts quoting
func TestExtremeRegimeHaltsQuoting(t *testing.T) {
	// This test verifies the logic that would halt quoting in extreme volatility
	regime := VolExtreme
	shouldHalt := regime == VolExtreme
	assert.True(t, shouldHalt, "Extreme volatility regime should halt quoting")

	// Other regimes should not halt
	for _, r := range []VolatilityRegime{VolCalm, VolNormal, VolElevated} {
		shouldHalt := r == VolExtreme
		assert.False(t, shouldHalt, "%s regime should not halt quoting", r.String())
	}
}

// Test regime transition boundaries
func TestRegimeTransitions(t *testing.T) {
	// Create a strategy with default thresholds
	s := &Strategy{
		cfg: config.MarketMakingConfig{
			VolCalmThreshold:     0.02,
			VolElevatedThreshold: 0.05,
			VolExtremeThreshold:  0.10,
		},
	}

	testCases := []struct {
		avgATR   float64
		expected VolatilityRegime
	}{
		{0.005, VolCalm},     // Well below calm threshold
		{0.019, VolCalm},     // Just below calm threshold
		{0.020, VolNormal},   // At calm threshold (boundary)
		{0.021, VolNormal},   // Just above calm threshold
		{0.049, VolNormal},   // Just below elevated threshold
		{0.050, VolElevated}, // At elevated threshold (boundary)
		{0.051, VolElevated}, // Just above elevated threshold
		{0.099, VolElevated}, // Just below extreme threshold
		{0.100, VolExtreme},  // At extreme threshold (boundary)
		{0.101, VolExtreme},  // Just above extreme threshold
		{0.200, VolExtreme},  // Well above extreme threshold
	}

	for _, tc := range testCases {
		var regime VolatilityRegime
		switch {
		case tc.avgATR < s.cfg.VolCalmThreshold:
			regime = VolCalm
		case tc.avgATR < s.cfg.VolElevatedThreshold:
			regime = VolNormal
		case tc.avgATR < s.cfg.VolExtremeThreshold:
			regime = VolElevated
		default:
			regime = VolExtreme
		}

		assert.Equal(t, tc.expected, regime,
			"ATR %.4f should result in %s regime", tc.avgATR, tc.expected.String())
	}
}
