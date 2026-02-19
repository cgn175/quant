package fundingarb

import (
	"math"

	"github.com/cgn175/quant-bot/internal/data"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/rs/zerolog/log"
)

// CrossExchangeManager handles cross-exchange funding rate arbitrage
type CrossExchangeManager struct {
	clients map[string]exchange.CrossExchangeClient
	store   *data.FundingStore
}

func NewCrossExchangeManager(store *data.FundingStore) *CrossExchangeManager {
	return &CrossExchangeManager{
		clients: make(map[string]exchange.CrossExchangeClient),
		store:   store,
	}
}

func (m *CrossExchangeManager) AddExchange(name string, client exchange.CrossExchangeClient) {
	m.clients[name] = client
}

// ScanCrossExchangeOpportunities finds funding rate arbitrage opportunities across exchanges
func (m *CrossExchangeManager) ScanCrossExchangeOpportunities(symbols []string, minSpreadBps float64) ([]*exchange.CrossExchangeOpportunity, error) {
	// Fetch funding rates from all exchanges
	rates := make(map[string]map[string]*exchange.FundingRateInfo)
	
	for exchangeName, client := range m.clients {
		exchangeRates := make(map[string]*exchange.FundingRateInfo)
		for _, symbol := range symbols {
			rate, err := client.GetFundingRate(symbol)
			if err != nil {
				log.Warn().Err(err).Str("exchange", exchangeName).Str("symbol", symbol).Msg("failed to fetch funding rate")
				continue
			}
			exchangeRates[symbol] = rate
		}
		rates[exchangeName] = exchangeRates
	}

	// Find arbitrage opportunities
	var opportunities []*exchange.CrossExchangeOpportunity
	
	for _, symbol := range symbols {
		var exchangeRates []struct {
			name string
			rate float64
		}
		
		// Collect rates for this symbol from all exchanges
		for exchangeName, symbolRates := range rates {
			if rate, exists := symbolRates[symbol]; exists {
				exchangeRates = append(exchangeRates, struct {
					name string
					rate float64
				}{exchangeName, rate.FundingRate})
			}
		}
		
		if len(exchangeRates) < 2 {
			continue // Need at least 2 exchanges
		}
		
		// Find highest and lowest funding rates
		var highExchange, lowExchange string
		var highRate, lowRate float64
		
		for i, er := range exchangeRates {
			if i == 0 {
				highExchange = er.name
				lowExchange = er.name
				highRate = er.rate
				lowRate = er.rate
			} else {
				if er.rate > highRate {
					highExchange = er.name
					highRate = er.rate
				}
				if er.rate < lowRate {
					lowExchange = er.name
					lowRate = er.rate
				}
			}
		}
		
		// Calculate spread in basis points
		spreadBps := math.Abs(highRate - lowRate) * 10000
		
		if spreadBps >= minSpreadBps {
			// Annualized return: spread * 3 payments/day * 365 days
			annualizedReturn := spreadBps * 3 * 365 / 10000 * 100
			
			opportunities = append(opportunities, &exchange.CrossExchangeOpportunity{
				Symbol:           symbol,
				HighExchange:     highExchange,
				LowExchange:      lowExchange,
				HighFundingRate:  highRate,
				LowFundingRate:   lowRate,
				SpreadBps:        spreadBps,
				AnnualizedReturn: annualizedReturn,
			})
		}
	}
	
	return opportunities, nil
}