package marketmaking

import (
	"math"
	"testing"

	"github.com/cgn175/quant-bot/internal/exchange"
)

func TestCalculateOrderBookImbalance(t *testing.T) {
	tests := []struct {
		name     string
		ob       exchange.OrderBook
		depth    int
		expected float64
	}{
		{
			name: "balanced book",
			ob: exchange.OrderBook{
				Symbol: "BTCUSDT",
				Bids: []exchange.PriceLevel{
					{Price: 50000, Quantity: 1.0},
					{Price: 49990, Quantity: 1.0},
				},
				Asks: []exchange.PriceLevel{
					{Price: 50010, Quantity: 1.0},
					{Price: 50020, Quantity: 1.0},
				},
			},
			depth:    2,
			expected: 0.0,
		},
		{
			name: "bullish imbalance (more bids)",
			ob: exchange.OrderBook{
				Symbol: "BTCUSDT",
				Bids: []exchange.PriceLevel{
					{Price: 50000, Quantity: 10.0},
					{Price: 49990, Quantity: 5.0},
				},
				Asks: []exchange.PriceLevel{
					{Price: 50010, Quantity: 1.0},
					{Price: 50020, Quantity: 1.0},
				},
			},
			depth:    2,
			expected: 0.7, // approximately
		},
		{
			name: "bearish imbalance (more asks)",
			ob: exchange.OrderBook{
				Symbol: "BTCUSDT",
				Bids: []exchange.PriceLevel{
					{Price: 50000, Quantity: 1.0},
					{Price: 49990, Quantity: 1.0},
				},
				Asks: []exchange.PriceLevel{
					{Price: 50010, Quantity: 10.0},
					{Price: 50020, Quantity: 5.0},
				},
			},
			depth:    2,
			expected: -0.7, // approximately
		},
		{
			name: "empty book",
			ob: exchange.OrderBook{
				Symbol: "BTCUSDT",
				Bids:   []exchange.PriceLevel{},
				Asks:   []exchange.PriceLevel{},
			},
			depth:    2,
			expected: 0.0,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := CalculateOrderBookImbalance(tt.ob, tt.depth)
			
			// Allow 0.1 tolerance for floating point comparison
			if math.Abs(result-tt.expected) > 0.1 {
				t.Errorf("CalculateOrderBookImbalance() = %v, want %v", result, tt.expected)
			}
		})
	}
}

func TestAdjustSpreadForImbalance(t *testing.T) {
	tests := []struct {
		name           string
		baseSpread     float64
		imbalance      float64
		skewFactor     float64
		expectedBid    float64
		expectedAsk    float64
	}{
		{
			name:        "no imbalance",
			baseSpread:  100.0,
			imbalance:   0.0,
			skewFactor:  0.5,
			expectedBid: 100.0,
			expectedAsk: 100.0,
		},
		{
			name:        "positive imbalance (bullish)",
			baseSpread:  100.0,
			imbalance:   0.5,
			skewFactor:  0.5,
			expectedBid: 75.0,  // 100 * (1 - 0.5*0.5)
			expectedAsk: 125.0, // 100 * (1 + 0.5*0.5)
		},
		{
			name:        "negative imbalance (bearish)",
			baseSpread:  100.0,
			imbalance:   -0.5,
			skewFactor:  0.5,
			expectedBid: 125.0, // 100 * (1 - (-0.5)*0.5)
			expectedAsk: 75.0,  // 100 * (1 + (-0.5)*0.5)
		},
		{
			name:        "extreme imbalance with floor",
			baseSpread:  100.0,
			imbalance:   1.0,
			skewFactor:  1.0,
			expectedBid: 20.0,  // floor at 20% of base
			expectedAsk: 200.0, // 100 * (1 + 1.0*1.0)
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			bidSpread, askSpread := AdjustSpreadForImbalance(tt.baseSpread, tt.imbalance, tt.skewFactor)
			
			if math.Abs(bidSpread-tt.expectedBid) > 0.01 {
				t.Errorf("bidSpread = %v, want %v", bidSpread, tt.expectedBid)
			}
			if math.Abs(askSpread-tt.expectedAsk) > 0.01 {
				t.Errorf("askSpread = %v, want %v", askSpread, tt.expectedAsk)
			}
		})
	}
}
