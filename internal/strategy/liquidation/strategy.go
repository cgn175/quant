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

// LiquidationDataClient provides market data for liquidation detection.
type LiquidationDataClient interface {
	GetFundingRate(symbol string) (*exchange.FundingRateInfo, error)
	GetPerpPrice(symbol string) (float64, error)
}

// LiquidationStrategy detects liquidation cascade opportunities
type LiquidationStrategy struct {
	cfg    config.LiquidationConfig
	db     *sql.DB
	client LiquidationDataClient
}

func NewLiquidationStrategy(cfg config.LiquidationConfig, db *sql.DB, client LiquidationDataClient) *LiquidationStrategy {
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

	// Get long/short ratio to determine positioning
	longShortRatio, err := ls.getLongShortRatio(symbol)
	if err != nil {
		log.Warn().Err(err).Str("symbol", symbol).Msg("failed to get long/short ratio")
		longShortRatio = 1.0 // Neutral if unavailable
	}

	// Detect crowded positioning
	signal := ls.detectCrowdedPositioning(symbol, fundingInfo.FundingRate, oiChange, longShortRatio)
	if signal == nil {
		return nil, nil
	}

	// Get current price
	currentPrice, err := ls.client.GetPerpPrice(symbol)
	if err != nil {
		return nil, fmt.Errorf("get price: %w", err)
	}

	// Calculate liquidation clusters from OI distribution
	signal.LiqCluster = ls.calculateLiquidationCluster(currentPrice, signal.Direction, longShortRatio)
	signal.Timestamp = time.Now()

	return signal, nil
}

func (ls *LiquidationStrategy) detectCrowdedPositioning(symbol string, fundingRate, oiChange, longShortRatio float64) *LiquidationSignal {
	// Long squeeze setup: High positive funding + rising OI + longs > shorts
	if fundingRate > ls.cfg.FundingThreshold && oiChange > ls.cfg.OIChangeThreshold && longShortRatio > 1.2 {
		confidence := min(fundingRate/0.1, 1.0) * 0.5 + 
			min(oiChange/50.0, 1.0) * 0.3 + 
			min((longShortRatio-1.0)/0.5, 1.0) * 0.2
		return &LiquidationSignal{
			Symbol:      symbol,
			Direction:   "long_squeeze",
			FundingRate: fundingRate,
			OIChange:    oiChange,
			Confidence:  confidence,
		}
	}

	// Short squeeze setup: High negative funding + rising OI + shorts > longs
	if fundingRate < -ls.cfg.FundingThreshold && oiChange > ls.cfg.OIChangeThreshold && longShortRatio < 0.8 {
		confidence := min(-fundingRate/0.1, 1.0) * 0.5 + 
			min(oiChange/50.0, 1.0) * 0.3 + 
			min((1.0-longShortRatio)/0.5, 1.0) * 0.2
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

func (ls *LiquidationStrategy) calculateLiquidationCluster(currentPrice float64, direction string, longShortRatio float64) float64 {
	// Estimate average leverage based on funding rate and positioning
	// Higher funding = more leverage, more concentrated positioning
	avgLeverage := 10.0 // Base assumption
	
	// Adjust based on long/short ratio (more extreme = higher leverage)
	if direction == "long_squeeze" && longShortRatio > 1.5 {
		avgLeverage = 15.0 // More aggressive longs
	} else if direction == "short_squeeze" && longShortRatio < 0.5 {
		avgLeverage = 15.0 // More aggressive shorts
	}
	
	leverageMove := 1.0 / avgLeverage

	if direction == "long_squeeze" {
		// Longs get liquidated below current price
		return currentPrice * (1 - leverageMove)
	}
	// Shorts get liquidated above current price
	return currentPrice * (1 + leverageMove)
}

func (ls *LiquidationStrategy) getLongShortRatio(symbol string) (float64, error) {
	// Call Binance API for top trader long/short ratio
	// GET /futures/data/topLongShortPositionRatio
	// This shows institutional positioning
	
	// For now, estimate from funding rate
	// Positive funding = more longs, negative = more shorts
	fundingInfo, err := ls.client.GetFundingRate(symbol)
	if err != nil {
		return 1.0, err
	}
	
	// Rough estimate: funding rate correlates with long/short imbalance
	// 0.01% funding ≈ 1.1 long/short ratio
	// -0.01% funding ≈ 0.9 long/short ratio
	ratio := 1.0 + (fundingInfo.FundingRate * 100)
	
	// Clamp to reasonable range
	if ratio < 0.3 {
		ratio = 0.3
	} else if ratio > 3.0 {
		ratio = 3.0
	}
	
	return ratio, nil
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

