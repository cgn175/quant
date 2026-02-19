package fundingarb

import (
	"testing"
)

func TestCheckFundingMomentum(t *testing.T) {
	tests := []struct {
		name               string
		current            float64
		threshold          float64
		avg24h             float64
		momentumMultiplier float64
		expected           bool
	}{
		{
			name:               "high and accelerating",
			current:            0.001,  // 0.1%
			threshold:          0.0005, // 0.05%
			avg24h:             0.0007, // 0.07%
			momentumMultiplier: 1.2,
			expected:           true, // 0.001 > 0.0005 AND 0.001 > 0.0007*1.2
		},
		{
			name:               "high but not accelerating",
			current:            0.0008, // 0.08%
			threshold:          0.0005, // 0.05%
			avg24h:             0.0007, // 0.07%
			momentumMultiplier: 1.2,
			expected:           false, // 0.0008 > 0.0005 BUT 0.0008 < 0.0007*1.2
		},
		{
			name:               "below threshold",
			current:            0.0003, // 0.03%
			threshold:          0.0005, // 0.05%
			avg24h:             0.0002, // 0.02%
			momentumMultiplier: 1.2,
			expected:           false, // 0.0003 < 0.0005
		},
		{
			name:               "negative funding (high and accelerating)",
			current:            -0.001,
			threshold:          0.0005,
			avg24h:             -0.0007,
			momentumMultiplier: 1.2,
			expected:           true, // abs values: 0.001 > 0.0005 AND 0.001 > 0.0007*1.2
		},
		{
			name:               "no history (avg24h = 0)",
			current:            0.001,
			threshold:          0.0005,
			avg24h:             0.0,
			momentumMultiplier: 1.2,
			expected:           true, // just use threshold when no history
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := CheckFundingMomentum(tt.current, tt.threshold, tt.avg24h, tt.momentumMultiplier)
			if result != tt.expected {
				t.Errorf("CheckFundingMomentum() = %v, want %v", result, tt.expected)
			}
		})
	}
}

func TestCheckMomentumExit(t *testing.T) {
	tests := []struct {
		name     string
		current  float64
		avg24h   float64
		expected bool
	}{
		{
			name:     "momentum lost (current < avg)",
			current:  0.0005,
			avg24h:   0.0008,
			expected: true,
		},
		{
			name:     "momentum maintained (current > avg)",
			current:  0.001,
			avg24h:   0.0008,
			expected: false,
		},
		{
			name:     "momentum equal",
			current:  0.0008,
			avg24h:   0.0008,
			expected: false,
		},
		{
			name:     "negative funding momentum lost",
			current:  -0.0005,
			avg24h:   -0.0008,
			expected: true, // abs(0.0005) < abs(0.0008)
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := CheckMomentumExit(tt.current, tt.avg24h)
			if result != tt.expected {
				t.Errorf("CheckMomentumExit() = %v, want %v", result, tt.expected)
			}
		})
	}
}
