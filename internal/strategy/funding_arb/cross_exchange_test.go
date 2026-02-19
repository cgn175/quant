package fundingarb

import (
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