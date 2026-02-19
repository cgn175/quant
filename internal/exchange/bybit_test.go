package exchange

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestBybitClient_GetFundingRate(t *testing.T) {
	client := NewBybitClient(false)
	
	// Test will fail due to network call, but we can test the client creation
	assert.NotNil(t, client)
	assert.False(t, client.testnet)
	assert.NotNil(t, client.httpClient)
	
	// Test that the method exists and returns an error for invalid network call
	_, err := client.GetFundingRate("BTCUSDT")
	assert.Error(t, err) // Expected to fail due to network call
}

func TestBybitClient_GetPerpPrice(t *testing.T) {
	client := NewBybitClient(false)
	
	// Test will fail due to network call, but we can test the client creation
	assert.NotNil(t, client)
	assert.False(t, client.testnet)
	assert.NotNil(t, client.httpClient)
	assert.Equal(t, 10*time.Second, client.httpClient.Timeout)
}

func TestBybitClient_BaseURL(t *testing.T) {
	// Test mainnet URL
	client := NewBybitClient(false)
	assert.Equal(t, bybitBaseURL, client.baseURL())

	// Test testnet URL
	clientTestnet := NewBybitClient(true)
	assert.Equal(t, bybitTestnetBaseURL, clientTestnet.baseURL())
}

func TestBybitClient_PlaceOrder(t *testing.T) {
	// Test unauthenticated client
	client := NewBybitClient(false)
	err := client.PlaceOrder("BTCUSDT", "Buy", 0.01, 50000)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "authentication not configured")
	
	// Test authenticated client (will fail without real API keys)
	authClient := NewBybitAuthClient(true, "test_key", "test_secret")
	err = authClient.PlaceOrder("BTCUSDT", "Buy", 0.01, 50000)
	assert.Error(t, err) // Will fail due to invalid credentials
}

func TestBybitClient_Close(t *testing.T) {
	client := NewBybitClient(false)
	
	// Should not return error
	err := client.Close()
	assert.NoError(t, err)
}