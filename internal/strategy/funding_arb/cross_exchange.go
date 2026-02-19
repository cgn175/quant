package fundingarb

// IMPORTANT: Cross-exchange arbitrage assumes accounts are PRE-FUNDED on all
// target exchanges. This strategy does NOT transfer funds between exchanges.
// Transfer costs (withdrawal fees, slippage, 10-30min delay) would likely
// eliminate any profit. Ensure adequate balance on each exchange before running.

import (
	"fmt"
	"math"
	"sync"

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
	log.Warn().Msg("cross-exchange arbitrage requires pre-funded accounts on all exchanges — do NOT rely on transfers during arb")
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
	// Fetch funding rates from all exchanges in parallel
	rates := make(map[string]map[string]*exchange.FundingRateInfo)
	var mu sync.Mutex
	var wg sync.WaitGroup

	for exchangeName, client := range m.clients {
		wg.Add(1)
		go func(name string, c exchange.CrossExchangeClient) {
			defer wg.Done()
			exchangeRates := make(map[string]*exchange.FundingRateInfo)
			for _, symbol := range symbols {
				rate, err := c.GetFundingRate(symbol)
				if err != nil {
					log.Warn().Err(err).Str("exchange", name).Str("symbol", symbol).Msg("failed to fetch funding rate")
					continue
				}
				exchangeRates[symbol] = rate
			}
			mu.Lock()
			rates[name] = exchangeRates
			mu.Unlock()
		}(exchangeName, client)
	}
	wg.Wait()

	// Check that at least one exchange returned data
	totalRates := 0
	for _, symbolRates := range rates {
		totalRates += len(symbolRates)
	}
	if totalRates == 0 {
		return nil, fmt.Errorf("failed to fetch funding rates from any exchange")
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

			// Estimated round-trip transfer cost (~0.2%) if funds needed to be moved.
			// Pre-funded accounts avoid this, but we track it for awareness.
			estTransferCostBps := 20.0
			netAnnualizedReturn := annualizedReturn
			
			opportunities = append(opportunities, &exchange.CrossExchangeOpportunity{
				Symbol:              symbol,
				HighExchange:        highExchange,
				LowExchange:         lowExchange,
				HighFundingRate:     highRate,
				LowFundingRate:      lowRate,
				SpreadBps:           spreadBps,
				AnnualizedReturn:    annualizedReturn,
				EstTransferCostBps:  estTransferCostBps,
				NetAnnualizedReturn: netAnnualizedReturn,
			})
		}
	}
	
	return opportunities, nil
}