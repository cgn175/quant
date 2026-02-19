package exchange

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestOKXClient_Creation(t *testing.T) {
	client := NewOKXClient()
	
	assert.NotNil(t, client)
	assert.NotNil(t, client.httpClient)
	assert.Equal(t, 10*time.Second, client.httpClient.Timeout)
}

func TestOKXClient_PlaceOrder(t *testing.T) {
	client := NewOKXClient()
	
	// Should return error as it's not implemented
	err := client.PlaceOrder("BTCUSDT", "BUY", 0.01, 50000)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "not implemented")
}

func TestOKXClient_Close(t *testing.T) {
	client := NewOKXClient()
	
	// Should not return error
	err := client.Close()
	assert.NoError(t, err)
}

func TestConvertToOKXSymbol(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"BTCUSDT", "BTC-USDT-SWAP"},
		{"ETHUSDT", "ETH-USDT-SWAP"},
		{"SOLUSDT", "SOL-USDT-SWAP"},
		{"BNBUSDT", "BNB-USDT-SWAP"},
		{"SHORT", "SHORT"}, // Edge case
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			result := convertToOKXSymbol(tt.input)
			assert.Equal(t, tt.expected, result)
		})
	}
}

func TestConvertToOKXSpotSymbol(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"BTCUSDT", "BTC-USDT"},
		{"ETHUSDT", "ETH-USDT"},
		{"SOLUSDT", "SOL-USDT"},
		{"BNBUSDT", "BNB-USDT"},
		{"SHORT", "SHORT"}, // Edge case
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			result := convertToOKXSpotSymbol(tt.input)
			assert.Equal(t, tt.expected, result)
		})
	}
}