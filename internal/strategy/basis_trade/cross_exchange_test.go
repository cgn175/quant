package basistrade

import (
	"testing"

	"github.com/cgn175/quant-bot/internal/exchange"
)

// Mock exchange client for testing
type mockExchangeClient struct {
	name      string
	spotPrice float64
	perpPrice float64
}

func (m *mockExchangeClient) GetSpotPrice(symbol string) (float64, error) {
	return m.spotPrice, nil
}

func (m *mockExchangeClient) GetPerpPrice(symbol string) (float64, error) {
	return m.perpPrice, nil
}

func (m *mockExchangeClient) GetFundingRate(symbol string) (*exchange.FundingRateInfo, error) {
	return nil, nil
}

func (m *mockExchangeClient) GetOrderBook(symbol string) (*exchange.OrderBook, error) {
	return nil, nil
}

func (m *mockExchangeClient) PlaceOrder(symbol, side string, quantity, price float64) error {
	return nil
}

func (m *mockExchangeClient) Close() error {
	return nil
}

func TestCrossExchangeBasisManager_ScanOpportunities(t *testing.T) {
	tests := []struct {
		name                string
		exchanges           map[string]exchange.CrossExchangeClient
		minBasisAnnualized  float64
		wantOpportunity     bool
		wantSpotExchange    string
		wantPerpExchange    string
		wantAnnualizedBasis float64
	}{
		{
			name: "profitable opportunity exists",
			exchanges: map[string]exchange.CrossExchangeClient{
				"binance": &mockExchangeClient{spotPrice: 50000, perpPrice: 50500}, // 1% basis
				"bybit":   &mockExchangeClient{spotPrice: 49900, perpPrice: 50600}, // 1.4% basis
			},
			minBasisAnnualized:  0.05, // 5% minimum
			wantOpportunity:     true,
			wantSpotExchange:    "bybit",   // Lowest spot (49900)
			wantPerpExchange:    "bybit",   // Highest perp (50600)
			wantAnnualizedBasis: 0.0568, // (50600-49900)/49900 * (365/90) ≈ 5.68%
		},
		{
			name: "cross-exchange opportunity",
			exchanges: map[string]exchange.CrossExchangeClient{
				"binance": &mockExchangeClient{spotPrice: 50000, perpPrice: 51000}, // 2% basis
				"bybit":   &mockExchangeClient{spotPrice: 49800, perpPrice: 50900}, // 2.2% basis
			},
			minBasisAnnualized:  0.08, // 8% minimum
			wantOpportunity:     true,
			wantSpotExchange:    "bybit",   // Lowest spot (49800)
			wantPerpExchange:    "binance", // Highest perp (51000)
			wantAnnualizedBasis: 0.0976, // (51000-49800)/49800 * (365/90) ≈ 9.76%
		},
		{
			name: "below minimum threshold",
			exchanges: map[string]exchange.CrossExchangeClient{
				"binance": &mockExchangeClient{spotPrice: 50000, perpPrice: 50100}, // 0.2% basis
			},
			minBasisAnnualized: 0.05, // 5% minimum
			wantOpportunity:    false,
		},
		{
			name: "no exchanges",
			exchanges:          map[string]exchange.CrossExchangeClient{},
			minBasisAnnualized: 0.05,
			wantOpportunity:    false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			manager := NewCrossExchangeBasisManager(tt.exchanges)
			opp, err := manager.ScanOpportunities("BTCUSDT", tt.minBasisAnnualized)

			if tt.wantOpportunity {
				if err != nil {
					t.Errorf("unexpected error: %v", err)
				}
				if opp == nil {
					t.Fatal("expected opportunity, got nil")
				}
				if opp.SpotExchange != tt.wantSpotExchange {
					t.Errorf("spot exchange = %v, want %v", opp.SpotExchange, tt.wantSpotExchange)
				}
				if opp.PerpExchange != tt.wantPerpExchange {
					t.Errorf("perp exchange = %v, want %v", opp.PerpExchange, tt.wantPerpExchange)
				}
				// Allow 1% tolerance for annualized basis calculation
				if diff := opp.AnnualizedBasis - tt.wantAnnualizedBasis; diff < -0.01 || diff > 0.01 {
					t.Errorf("annualized basis = %v, want %v", opp.AnnualizedBasis, tt.wantAnnualizedBasis)
				}
			} else {
				if opp != nil {
					t.Errorf("expected no opportunity, got %+v", opp)
				}
			}
		})
	}
}

func TestCalculateBasis(t *testing.T) {
	tests := []struct {
		name      string
		perpPrice float64
		spotPrice float64
		want      float64
	}{
		{"positive basis", 51000, 50000, 0.02},
		{"negative basis", 49000, 50000, -0.02},
		{"zero basis", 50000, 50000, 0.0},
		{"zero spot", 50000, 0, 0.0},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := CalculateBasis(tt.perpPrice, tt.spotPrice)
			if diff := got - tt.want; diff < -0.0001 || diff > 0.0001 {
				t.Errorf("CalculateBasis() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestAnnualizeBasis(t *testing.T) {
	tests := []struct {
		name  string
		basis float64
		want  float64
	}{
		{"2% quarterly", 0.02, 0.0811}, // 0.02 * (365/90) ≈ 8.11%
		{"1% quarterly", 0.01, 0.0406}, // 0.01 * (365/90) ≈ 4.06%
		{"zero", 0.0, 0.0},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := AnnualizeBasis(tt.basis)
			if diff := got - tt.want; diff < -0.001 || diff > 0.001 {
				t.Errorf("AnnualizeBasis() = %v, want %v", got, tt.want)
			}
		})
	}
}
