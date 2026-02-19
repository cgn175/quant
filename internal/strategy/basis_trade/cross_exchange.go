package basistrade

import (
	"fmt"
	"math"

	"github.com/cgn175/quant-bot/internal/exchange"
)

// CrossExchangeBasisOpportunity represents a basis arbitrage opportunity across exchanges
type CrossExchangeBasisOpportunity struct {
	Symbol          string
	SpotExchange    string  // Exchange with best spot price (lowest)
	PerpExchange    string  // Exchange with best perp price (highest premium)
	SpotPrice       float64
	PerpPrice       float64
	Basis           float64 // Perp premium over spot (percentage)
	AnnualizedBasis float64 // Annualized basis (assuming 90-day convergence)
}

// CrossExchangeBasisManager scans for basis opportunities across multiple exchanges
type CrossExchangeBasisManager struct {
	exchanges map[string]exchange.CrossExchangeClient
}

// NewCrossExchangeBasisManager creates a new cross-exchange basis manager
func NewCrossExchangeBasisManager(exchanges map[string]exchange.CrossExchangeClient) *CrossExchangeBasisManager {
	return &CrossExchangeBasisManager{
		exchanges: exchanges,
	}
}

// ScanOpportunities finds the best basis opportunity for a symbol across exchanges
func (m *CrossExchangeBasisManager) ScanOpportunities(symbol string, minBasisAnnualized float64) (*CrossExchangeBasisOpportunity, error) {
	if len(m.exchanges) == 0 {
		return nil, fmt.Errorf("no exchanges configured")
	}

	var bestOpp *CrossExchangeBasisOpportunity
	var lowestSpotPrice float64 = math.MaxFloat64
	var lowestSpotExchange string
	var highestPerpPrice float64 = 0.0
	var highestPerpExchange string

	// Find lowest spot price across exchanges
	for name, client := range m.exchanges {
		spotPrice, err := client.GetSpotPrice(symbol)
		if err != nil {
			continue // Skip if error
		}
		if spotPrice < lowestSpotPrice {
			lowestSpotPrice = spotPrice
			lowestSpotExchange = name
		}
	}

	// Find highest perp price across exchanges
	for name, client := range m.exchanges {
		perpPrice, err := client.GetPerpPrice(symbol)
		if err != nil {
			continue // Skip if error
		}
		if perpPrice > highestPerpPrice {
			highestPerpPrice = perpPrice
			highestPerpExchange = name
		}
	}

	// Calculate basis if we found both
	if lowestSpotExchange != "" && highestPerpExchange != "" && lowestSpotPrice > 0 {
		basis := (highestPerpPrice - lowestSpotPrice) / lowestSpotPrice
		
		// Annualize assuming 90-day convergence (typical quarterly futures)
		// Annualized = basis * (365 / 90)
		annualizedBasis := basis * (365.0 / 90.0)

		// Only return if meets minimum threshold
		if annualizedBasis >= minBasisAnnualized {
			bestOpp = &CrossExchangeBasisOpportunity{
				Symbol:          symbol,
				SpotExchange:    lowestSpotExchange,
				PerpExchange:    highestPerpExchange,
				SpotPrice:       lowestSpotPrice,
				PerpPrice:       highestPerpPrice,
				Basis:           basis,
				AnnualizedBasis: annualizedBasis,
			}
		}
	}

	return bestOpp, nil
}

// CalculateBasis calculates the basis between perp and spot prices
func CalculateBasis(perpPrice, spotPrice float64) float64 {
	if spotPrice == 0 {
		return 0
	}
	return (perpPrice - spotPrice) / spotPrice
}

// AnnualizeBasis converts basis to annualized rate (assuming 90-day convergence)
func AnnualizeBasis(basis float64) float64 {
	return basis * (365.0 / 90.0)
}
