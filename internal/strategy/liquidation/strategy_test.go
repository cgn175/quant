package liquidation

import (
	"database/sql"
	"fmt"
	"testing"
	"time"

	"github.com/cgn175/quant-bot/internal/config"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/mock"
	_ "modernc.org/sqlite"
)

// MockLiquidationClient is a mock implementation of LiquidationDataClient
type MockLiquidationClient struct {
	mock.Mock
}

func (m *MockLiquidationClient) GetFundingRate(symbol string) (*exchange.FundingRateInfo, error) {
	args := m.Called(symbol)
	if args.Get(0) == nil {
		return nil, args.Error(1)
	}
	return args.Get(0).(*exchange.FundingRateInfo), args.Error(1)
}

func (m *MockLiquidationClient) GetPerpPrice(symbol string) (float64, error) {
	args := m.Called(symbol)
	return args.Get(0).(float64), args.Error(1)
}

func setupTestDB(t *testing.T) *sql.DB {
	db, err := sql.Open("sqlite", ":memory:")
	assert.NoError(t, err)

	_, err = db.Exec(`CREATE TABLE open_interest (
		symbol TEXT NOT NULL,
		timestamp INTEGER NOT NULL,
		open_interest REAL NOT NULL
	)`)
	assert.NoError(t, err)

	t.Cleanup(func() { db.Close() })
	return db
}

func insertOI(db *sql.DB, symbol string, timestamp int64, oi float64) {
	db.Exec("INSERT INTO open_interest (symbol, timestamp, open_interest) VALUES (?, ?, ?)",
		symbol, timestamp, oi)
}

func TestLiquidationStrategy_LongSqueeze(t *testing.T) {
	db := setupTestDB(t)
	client := &MockLiquidationClient{}

	cfg := config.LiquidationConfig{
		FundingThreshold:  0.01,
		OIChangeThreshold: 10.0,
	}

	// Insert OI data: old OI=100, new OI=130 → 30% increase
	// getOIChange queries for old OI with: timestamp >= (now-24h) AND timestamp < (now-24h)+3600
	// So old OI must be within first hour of the 24h window
	now := time.Now()
	oldTime := now.Add(-24*time.Hour + 30*time.Minute) // Within [cutoff, cutoff+3600)
	insertOI(db, "BTCUSDT", oldTime.Unix(), 100.0)
	insertOI(db, "BTCUSDT", now.Unix(), 130.0)

	client.On("GetFundingRate", "BTCUSDT").Return(&exchange.FundingRateInfo{
		Symbol:      "BTCUSDT",
		FundingRate: 0.05, // High positive funding
		FundingTime: now,
		MarkPrice:   50000,
	}, nil)
	client.On("GetPerpPrice", "BTCUSDT").Return(50000.0, nil)

	strategy := NewLiquidationStrategy(cfg, db, client)
	signal, err := strategy.ScanOpportunities("BTCUSDT")

	assert.NoError(t, err)
	assert.NotNil(t, signal)
	assert.Equal(t, "long_squeeze", signal.Direction)
	assert.Equal(t, 0.05, signal.FundingRate)
	assert.Greater(t, signal.OIChange, 0.0)
	assert.Greater(t, signal.Confidence, 0.0)
	assert.Less(t, signal.LiqCluster, 50000.0) // Longs liquidated below price

	client.AssertExpectations(t)
}

func TestLiquidationStrategy_ShortSqueeze(t *testing.T) {
	db := setupTestDB(t)
	client := &MockLiquidationClient{}

	cfg := config.LiquidationConfig{
		FundingThreshold:  0.01,
		OIChangeThreshold: 10.0,
	}

	now := time.Now()
	oldTime := now.Add(-24*time.Hour + 30*time.Minute) // Within [cutoff, cutoff+3600)
	insertOI(db, "ETHUSDT", oldTime.Unix(), 200.0)
	insertOI(db, "ETHUSDT", now.Unix(), 260.0) // 30% increase

	client.On("GetFundingRate", "ETHUSDT").Return(&exchange.FundingRateInfo{
		Symbol:      "ETHUSDT",
		FundingRate: -0.05, // High negative funding
		FundingTime: now,
		MarkPrice:   3000,
	}, nil)
	client.On("GetPerpPrice", "ETHUSDT").Return(3000.0, nil)

	strategy := NewLiquidationStrategy(cfg, db, client)
	signal, err := strategy.ScanOpportunities("ETHUSDT")

	assert.NoError(t, err)
	assert.NotNil(t, signal)
	assert.Equal(t, "short_squeeze", signal.Direction)
	assert.Equal(t, -0.05, signal.FundingRate)
	assert.Greater(t, signal.OIChange, 0.0)
	assert.Greater(t, signal.Confidence, 0.0)
	assert.Greater(t, signal.LiqCluster, 3000.0) // Shorts liquidated above price

	client.AssertExpectations(t)
}

func TestLiquidationStrategy_NoSignal(t *testing.T) {
	db := setupTestDB(t)
	client := &MockLiquidationClient{}

	cfg := config.LiquidationConfig{
		FundingThreshold:  0.01,
		OIChangeThreshold: 10.0,
	}

	// Low funding rate → no signal
	client.On("GetFundingRate", "BTCUSDT").Return(&exchange.FundingRateInfo{
		Symbol:      "BTCUSDT",
		FundingRate: 0.005, // Below threshold
		FundingTime: time.Now(),
		MarkPrice:   50000,
	}, nil)

	strategy := NewLiquidationStrategy(cfg, db, client)
	signal, err := strategy.ScanOpportunities("BTCUSDT")

	assert.NoError(t, err)
	assert.Nil(t, signal)

	client.AssertExpectations(t)
}

func TestLiquidationStrategy_FundingError(t *testing.T) {
	db := setupTestDB(t)
	client := &MockLiquidationClient{}

	cfg := config.LiquidationConfig{
		FundingThreshold:  0.01,
		OIChangeThreshold: 10.0,
	}

	client.On("GetFundingRate", "BTCUSDT").Return(nil, fmt.Errorf("api timeout"))

	strategy := NewLiquidationStrategy(cfg, db, client)
	signal, err := strategy.ScanOpportunities("BTCUSDT")

	assert.Error(t, err)
	assert.Nil(t, signal)
	assert.Contains(t, err.Error(), "get funding rate")

	client.AssertExpectations(t)
}

func TestCalculateLiquidationCluster(t *testing.T) {
	strategy := &LiquidationStrategy{cfg: config.LiquidationConfig{}}

	tests := []struct {
		name      string
		price     float64
		direction string
		wantBelow bool // true if cluster should be below price
	}{
		{
			name:      "long_squeeze cluster is below price",
			price:     50000.0,
			direction: "long_squeeze",
			wantBelow: true,
		},
		{
			name:      "short_squeeze cluster is above price",
			price:     50000.0,
			direction: "short_squeeze",
			wantBelow: false,
		},
		{
			name:      "long_squeeze with low price",
			price:     100.0,
			direction: "long_squeeze",
			wantBelow: true,
		},
		{
			name:      "short_squeeze with low price",
			price:     100.0,
			direction: "short_squeeze",
			wantBelow: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Use neutral ratio for tests
			longShortRatio := 1.0
			cluster := strategy.calculateLiquidationCluster(tt.price, tt.direction, longShortRatio)
			if tt.wantBelow {
				assert.Less(t, cluster, tt.price)
			} else {
				assert.Greater(t, cluster, tt.price)
			}
		})
	}
}

func TestDetectCrowdedPositioning_Confidence(t *testing.T) {
	cfg := config.LiquidationConfig{
		FundingThreshold:  0.01,
		OIChangeThreshold: 5.0,
	}
	strategy := &LiquidationStrategy{cfg: cfg}

	tests := []struct {
		name        string
		fundingRate float64
		oiChange    float64
		wantSignal  bool
	}{
		{
			name:        "moderate long squeeze",
			fundingRate: 0.03,
			oiChange:    20.0,
			wantSignal:  true,
		},
		{
			name:        "extreme long squeeze",
			fundingRate: 0.10,
			oiChange:    50.0,
			wantSignal:  true,
		},
		{
			name:        "moderate short squeeze",
			fundingRate: -0.03,
			oiChange:    20.0,
			wantSignal:  true,
		},
		{
			name:        "below threshold",
			fundingRate: 0.005,
			oiChange:    20.0,
			wantSignal:  false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			longShortRatio := 1.3 // Simulate long-heavy positioning for long squeeze
			if tt.fundingRate < 0 {
				longShortRatio = 0.7 // Short-heavy for short squeeze
			}
			signal := strategy.detectCrowdedPositioning("BTCUSDT", tt.fundingRate, tt.oiChange, longShortRatio)
			if !tt.wantSignal {
				assert.Nil(t, signal)
				return
			}
			assert.NotNil(t, signal)
			assert.Greater(t, signal.Confidence, 0.0)
			assert.LessOrEqual(t, signal.Confidence, 1.0)
		})
	}
}
