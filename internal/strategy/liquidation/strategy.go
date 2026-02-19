package liquidation

import (
	"database/sql"
	"fmt"
	"time"

	"github.com/cgn175/quant-bot/internal/config"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/rs/zerolog/log"
)

// LiquidationSignal represents a liquidation cascade opportunity
type LiquidationSignal struct {
	Symbol          string
	Direction       string  // "long_squeeze" or "short_squeeze"
	FundingRate     float64
	OIChange        float64 // % change in last 24h
	LiqCluster      float64 // Price level with high liquidation risk
	Confidence      float64 // 0-1
	Timestamp       time.Time
}

// LiquidationStrategy detects liquidation cascade opportunities
type LiquidationStrategy struct {
	cfg    config.LiquidationConfig
	db     *sql.DB
	client interface {
		GetFundingRate(symbol string) (*exchange.FundingRateInfo, error)
		GetPerpPrice(symbol string) (float64, error)
	}
}

func NewLiquidationStrategy(cfg config.LiquidationConfig, db *sql.DB, client interface {
	GetFundingRate(symbol string) (*exchange.FundingRateInfo, error)
	GetPerpPrice(symbol string) (float64, error)
}) *LiquidationStrategy {
	return &LiquidationStrategy{
		cfg:    cfg,
		db:     db,
		client: client,
	}
}

// ScanOpportunities scans for liquidation cascade setups
func (ls *LiquidationStrategy) ScanOpportunities(symbol string) (*LiquidationSignal, error) {
	// Get current funding rate
	fundingInfo, err := ls.client.GetFundingRate(symbol)
	if err != nil {
		return nil, fmt.Errorf("get funding rate: %w", err)
	}

	// Get OI change from database
	oiChange, err := ls.getOIChange(symbol, 24*time.Hour)
	if err != nil {
		log.Warn().Err(err).Str("symbol", symbol).Msg("failed to get OI change")
		oiChange = 0
	}

	// Detect crowded positioning
	signal := ls.detectCrowdedPositioning(symbol, fundingInfo.FundingRate, oiChange)
	if signal == nil {
		return nil, nil
	}

	// Estimate liquidation cluster
	currentPrice, err := ls.client.GetPerpPrice(symbol)
	if err != nil {
		return nil, fmt.Errorf("get price: %w", err)
	}

	signal.LiqCluster = ls.estimateLiquidationCluster(currentPrice, signal.Direction)
	signal.Timestamp = time.Now()

	return signal, nil
}

func (ls *LiquidationStrategy) detectCrowdedPositioning(symbol string, fundingRate, oiChange float64) *LiquidationSignal {
	// Long squeeze setup: High positive funding + rising OI
	if fundingRate > ls.cfg.FundingThreshold && oiChange > ls.cfg.OIChangeThreshold {
		confidence := min(fundingRate/0.1, 1.0) * 0.7 + min(oiChange/50.0, 1.0) * 0.3
		return &LiquidationSignal{
			Symbol:      symbol,
			Direction:   "long_squeeze",
			FundingRate: fundingRate,
			OIChange:    oiChange,
			Confidence:  confidence,
		}
	}

	// Short squeeze setup: High negative funding + rising OI
	if fundingRate < -ls.cfg.FundingThreshold && oiChange > ls.cfg.OIChangeThreshold {
		confidence := min(-fundingRate/0.1, 1.0) * 0.7 + min(oiChange/50.0, 1.0) * 0.3
		return &LiquidationSignal{
			Symbol:      symbol,
			Direction:   "short_squeeze",
			FundingRate: fundingRate,
			OIChange:    oiChange,
			Confidence:  confidence,
		}
	}

	return nil
}

func (ls *LiquidationStrategy) estimateLiquidationCluster(currentPrice float64, direction string) float64 {
	// Estimate liquidation level based on typical leverage
	// Assume 10x leverage average (10% move triggers liquidation)
	leverageMove := 0.10

	if direction == "long_squeeze" {
		// Longs get liquidated below current price
		return currentPrice * (1 - leverageMove)
	}
	// Shorts get liquidated above current price
	return currentPrice * (1 + leverageMove)
}

func (ls *LiquidationStrategy) getOIChange(symbol string, period time.Duration) (float64, error) {
	cutoff := time.Now().Add(-period).Unix()

	var oldOI, newOI float64
	err := ls.db.QueryRow(`
		SELECT open_interest FROM open_interest
		WHERE symbol = ? AND timestamp >= ? AND timestamp < ?
		ORDER BY timestamp ASC LIMIT 1
	`, symbol, cutoff, cutoff+3600).Scan(&oldOI)
	if err != nil {
		return 0, err
	}

	err = ls.db.QueryRow(`
		SELECT open_interest FROM open_interest
		WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1
	`, symbol).Scan(&newOI)
	if err != nil {
		return 0, err
	}

	if oldOI == 0 {
		return 0, nil
	}

	return ((newOI - oldOI) / oldOI) * 100, nil
}

func min(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}
