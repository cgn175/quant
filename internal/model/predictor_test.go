package model

import (
	"testing"
)

func TestPrediction_ArgMax(t *testing.T) {
	tests := []struct {
		name     string
		pred     Prediction
		expected int
	}{
		{
			name:     "up highest",
			pred:     Prediction{ProbDown: 0.1, ProbNeutral: 0.2, ProbUp: 0.7},
			expected: ClassUp,
		},
		{
			name:     "down highest",
			pred:     Prediction{ProbDown: 0.7, ProbNeutral: 0.2, ProbUp: 0.1},
			expected: ClassDown,
		},
		{
			name:     "neutral highest",
			pred:     Prediction{ProbDown: 0.2, ProbNeutral: 0.6, ProbUp: 0.2},
			expected: ClassNeutral,
		},
		{
			name:     "up and neutral tie, up wins",
			pred:     Prediction{ProbDown: 0.2, ProbNeutral: 0.4, ProbUp: 0.4},
			expected: ClassUp,
		},
		{
			name:     "all equal, down wins",
			pred:     Prediction{ProbDown: 0.33, ProbNeutral: 0.33, ProbUp: 0.33},
			expected: ClassDown,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := tt.pred.ArgMax(); got != tt.expected {
				t.Errorf("ArgMax() = %v, want %v", got, tt.expected)
			}
		})
	}
}
