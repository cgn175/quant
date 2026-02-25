package fundingarb

import (
	"fmt"
	"testing"
	"time"

	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/mock"
)

// MockCrossExchangeClient is a mock implementation of CrossExchangeClient
type MockCrossExchangeClient struct {
	mock.Mock
}

func (m *MockCrossExchangeClient) GetFundingRate(symbol string) (*exchange.FundingRateInfo, error) {
	args := m.Called(symbol)
	if args.Get(0) == nil {
		return nil, args.Error(1)
	}
	return args.Get(0).(*exchange.FundingRateInfo), args.Error(1)
}

func (m *MockCrossExchangeClient) GetPerpPrice(symbol string) (float64, error) {
	args := m.Called(symbol)
	return args.Get(0).(float64), args.Error(1)
}

func (m *MockCrossExchangeClient) GetSpotPrice(symbol string) (float64, error) {
	args := m.Called(symbol)
	return args.Get(0).(float64), args.Error(1)
}

func (m *MockCrossExchangeClient) GetOrderBook(symbol string) (*exchange.OrderBook, error) {
	args := m.Called(symbol)
	return args.Get(0).(*exchange.OrderBook), args.Error(1)
}

func (m *MockCrossExchangeClient) PlaceOrder(symbol, side string, quantity, price float64) error {
	args := m.Called(symbol, side, quantity, price)
	return args.Error(0)
}

func (m *MockCrossExchangeClient) Close() error {
	args := m.Called()
	return args.Error(0)
}

func TestCrossExchangeManager_ScanOpportunities(t *testing.T) {
	manager := NewCrossExchangeManager(nil)

	// Setup mock clients
	binanceClient := &MockCrossExchangeClient{}
	bybitClient := &MockCrossExchangeClient{}

	manager.AddExchange("binance", binanceClient)
	manager.AddExchange("bybit", bybitClient)

	// Setup mock responses - make sure to return pointers
	binanceRate := &exchange.FundingRateInfo{
		Symbol:      "BTCUSDT",
		FundingRate: 0.001, // 0.1% (high)
		FundingTime: time.Now(),
		MarkPrice:   50000,
	}
	
	bybitRate := &exchange.FundingRateInfo{
		Symbol:      "BTCUSDT",
		FundingRate: 0.0005, // 0.05% (low)
		FundingTime: time.Now(),
		MarkPrice:   50000,
	}

	binanceClient.On("GetFundingRate", "BTCUSDT").Return(binanceRate, nil)
	bybitClient.On("GetFundingRate", "BTCUSDT").Return(bybitRate, nil)

	// Test scanning for opportunities
	opportunities, err := manager.ScanCrossExchangeOpportunities([]string{"BTCUSDT"}, 3) // 3 bps minimum (lower than 5 bps spread)

	assert.NoError(t, err)
	
	// Debug: print opportunities if test fails
	if len(opportunities) == 0 {
		t.Logf("No opportunities found. Expected 1 opportunity with 5 bps spread (above 3 bps threshold)")
		t.FailNow()
	}
	
	assert.Len(t, opportunities, 1)

	opp := opportunities[0]
	assert.Equal(t, "BTCUSDT", opp.Symbol)
	assert.Equal(t, "binance", opp.HighExchange)
	assert.Equal(t, "bybit", opp.LowExchange)
	assert.Equal(t, 0.001, opp.HighFundingRate)
	assert.Equal(t, 0.0005, opp.LowFundingRate)
	assert.Equal(t, 5.0, opp.SpreadBps) // 0.0005 * 10000 = 5 bps
	assert.Equal(t, 50000.0, opp.MarkPrice) // Average mark price from both exchanges
	assert.Greater(t, opp.AnnualizedReturn, 0.0)

	binanceClient.AssertExpectations(t)
	bybitClient.AssertExpectations(t)
}

func TestCrossExchangeManager_NoOpportunityBelowThreshold(t *testing.T) {
	manager := NewCrossExchangeManager(nil)

	binanceClient := &MockCrossExchangeClient{}
	bybitClient := &MockCrossExchangeClient{}

	manager.AddExchange("binance", binanceClient)
	manager.AddExchange("bybit", bybitClient)

	// Setup mock responses with small spread
	binanceClient.On("GetFundingRate", "BTCUSDT").Return(&exchange.FundingRateInfo{
		Symbol:      "BTCUSDT",
		FundingRate: 0.0006, // 0.06%
		FundingTime: time.Now(),
		MarkPrice:   50000,
	}, nil)

	bybitClient.On("GetFundingRate", "BTCUSDT").Return(&exchange.FundingRateInfo{
		Symbol:      "BTCUSDT",
		FundingRate: 0.0005, // 0.05%
		FundingTime: time.Now(),
		MarkPrice:   50000,
	}, nil)

	// Test with high minimum spread (should find no opportunities)
	opportunities, err := manager.ScanCrossExchangeOpportunities([]string{"BTCUSDT"}, 20) // 20 bps minimum

	assert.NoError(t, err)
	assert.Len(t, opportunities, 0) // Spread is only 1 bps, below 20 bps threshold
}

func TestCalculateFundingAverage(t *testing.T) {
	// Test with nil store
	avg := CalculateFundingAverage(nil, "BTCUSDT", 24)
	assert.Equal(t, 0.0, avg)
}

func TestCrossExchangeManager_AllExchangesFail(t *testing.T) {
	manager := NewCrossExchangeManager(nil)

	binanceClient := &MockCrossExchangeClient{}
	bybitClient := &MockCrossExchangeClient{}

	manager.AddExchange("binance", binanceClient)
	manager.AddExchange("bybit", bybitClient)

	binanceClient.On("GetFundingRate", "BTCUSDT").Return(nil, fmt.Errorf("api error"))
	bybitClient.On("GetFundingRate", "BTCUSDT").Return(nil, fmt.Errorf("api error"))

	_, err := manager.ScanCrossExchangeOpportunities([]string{"BTCUSDT"}, 3)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "failed to fetch funding rates from any exchange")

	binanceClient.AssertExpectations(t)
	bybitClient.AssertExpectations(t)
}

func TestCrossExchangeManager_MultipleSymbols(t *testing.T) {
	manager := NewCrossExchangeManager(nil)

	binanceClient := &MockCrossExchangeClient{}
	bybitClient := &MockCrossExchangeClient{}

	manager.AddExchange("binance", binanceClient)
	manager.AddExchange("bybit", bybitClient)

	now := time.Now()

	// BTCUSDT: large spread → opportunity
	binanceClient.On("GetFundingRate", "BTCUSDT").Return(&exchange.FundingRateInfo{
		Symbol: "BTCUSDT", FundingRate: 0.002, FundingTime: now, MarkPrice: 50000,
	}, nil)
	bybitClient.On("GetFundingRate", "BTCUSDT").Return(&exchange.FundingRateInfo{
		Symbol: "BTCUSDT", FundingRate: 0.0005, FundingTime: now, MarkPrice: 50000,
	}, nil)

	// ETHUSDT: small spread → no opportunity
	binanceClient.On("GetFundingRate", "ETHUSDT").Return(&exchange.FundingRateInfo{
		Symbol: "ETHUSDT", FundingRate: 0.0003, FundingTime: now, MarkPrice: 3000,
	}, nil)
	bybitClient.On("GetFundingRate", "ETHUSDT").Return(&exchange.FundingRateInfo{
		Symbol: "ETHUSDT", FundingRate: 0.0002, FundingTime: now, MarkPrice: 3000,
	}, nil)

	// SOLUSDT: moderate spread → opportunity at low threshold
	binanceClient.On("GetFundingRate", "SOLUSDT").Return(&exchange.FundingRateInfo{
		Symbol: "SOLUSDT", FundingRate: 0.001, FundingTime: now, MarkPrice: 100,
	}, nil)
	bybitClient.On("GetFundingRate", "SOLUSDT").Return(&exchange.FundingRateInfo{
		Symbol: "SOLUSDT", FundingRate: 0.0003, FundingTime: now, MarkPrice: 100,
	}, nil)

	symbols := []string{"BTCUSDT", "ETHUSDT", "SOLUSDT"}
	opportunities, err := manager.ScanCrossExchangeOpportunities(symbols, 5)

	assert.NoError(t, err)

	// BTCUSDT spread: (0.002 - 0.0005) * 10000 = 15 bps → above 5
	// ETHUSDT spread: (0.0003 - 0.0002) * 10000 = 1 bps → below 5
	// SOLUSDT spread: (0.001 - 0.0003) * 10000 = 7 bps → above 5
	assert.Len(t, opportunities, 2)

	symbolsFound := map[string]bool{}
	for _, opp := range opportunities {
		symbolsFound[opp.Symbol] = true
		assert.Greater(t, opp.SpreadBps, 5.0)
		assert.Greater(t, opp.AnnualizedReturn, 0.0)
	}
	assert.True(t, symbolsFound["BTCUSDT"])
	assert.True(t, symbolsFound["SOLUSDT"])

	binanceClient.AssertExpectations(t)
	bybitClient.AssertExpectations(t)
}

func TestCrossExchangeManager_SingleExchange(t *testing.T) {
	manager := NewCrossExchangeManager(nil)

	binanceClient := &MockCrossExchangeClient{}
	manager.AddExchange("binance", binanceClient)

	binanceClient.On("GetFundingRate", "BTCUSDT").Return(&exchange.FundingRateInfo{
		Symbol:      "BTCUSDT",
		FundingRate: 0.005, // Very high rate
		FundingTime: time.Now(),
		MarkPrice:   50000,
	}, nil)

	opportunities, err := manager.ScanCrossExchangeOpportunities([]string{"BTCUSDT"}, 1)

	assert.NoError(t, err)
	assert.Len(t, opportunities, 0) // Need ≥2 exchanges for arb

	binanceClient.AssertExpectations(t)
}