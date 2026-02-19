package config

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func validBaseConfig() Config {
	return Config{
		Risk: RiskConfig{
			MaxRiskPerTradePct: 1.0,
			MaxDailyLossPct:    3.0,
			MaxOpenPositions:   3,
			MaxLeverage:        2.0,
		},
	}
}

func validTrendConfig() Config {
	c := validBaseConfig()
	c.Strategy = StrategyConfig{
		Type:               "trend_following",
		DonchianPeriod:     20,
		EMAFast:            9,
		EMASlow:            21,
		EMATrend:           50,
		ATRPeriod:          14,
		ATRStopMult:        3.0,
		ADXPeriod:          14,
		ADXThreshold:       20.0,
		VolatilityLow:      0.5,
		VolatilityHigh:     2.5,
		ChandelierLookback: 10,
	}
	return c
}

func validMMConfig() Config {
	c := validBaseConfig()
	c.Strategy = StrategyConfig{
		Type: "market_making",
		MarketMaking: MarketMakingConfig{
			SpreadPct:            0.005,
			OrderAmount:          0.01,
			RefreshTimeMs:        10000,
			Gamma:                0.1,
			MaxInventory:         1.0,
			MinSpreadPct:         0.001,
			MaxSpreadPct:         0.02,
			VolRegimeEnabled:     true,
			VolCalmThreshold:     0.02,
			VolElevatedThreshold: 0.05,
			VolExtremeThreshold:  0.10,
		},
	}
	return c
}

func validFundingArbConfig() Config {
	c := validBaseConfig()
	c.Strategy = StrategyConfig{
		Type: "funding_arb",
		FundingArb: FundingArbConfig{
			MinFundingRate:  0.0005,
			ExitThreshold:  0.0001,
			MaxPositions:   3,
			PositionSizeUSD: 1000.0,
			MaxLossPct:     0.03,
		},
	}
	return c
}

func validBasisTradeConfig() Config {
	c := validBaseConfig()
	c.Strategy = StrategyConfig{
		Type: "basis_trade",
		BasisTrade: BasisTradeConfig{
			MinBasisAnnualized: 0.15,
			ExitBasis:          0.05,
			MaxPositions:       3,
			PositionSizeUSD:    1000.0,
		},
	}
	return c
}

func TestValidate_ValidConfigs(t *testing.T) {
	configs := []struct {
		name string
		cfg  Config
	}{
		{"trend_following", validTrendConfig()},
		{"market_making", validMMConfig()},
		{"funding_arb", validFundingArbConfig()},
		{"basis_trade", validBasisTradeConfig()},
	}
	for _, tc := range configs {
		t.Run(tc.name, func(t *testing.T) {
			assert.NoError(t, tc.cfg.Validate())
		})
	}
}

func TestValidate_MarketMaking_Invalid(t *testing.T) {
	tests := []struct {
		name   string
		modify func(*Config)
		errMsg string
	}{
		{
			"zero_spread",
			func(c *Config) { c.Strategy.MarketMaking.SpreadPct = 0 },
			"spread_pct must be > 0",
		},
		{
			"negative_order_amount",
			func(c *Config) { c.Strategy.MarketMaking.OrderAmount = -1 },
			"order_amount must be > 0",
		},
		{
			"zero_refresh_time",
			func(c *Config) { c.Strategy.MarketMaking.RefreshTimeMs = 0 },
			"refresh_time_ms must be > 0",
		},
		{
			"negative_gamma",
			func(c *Config) { c.Strategy.MarketMaking.Gamma = -0.5 },
			"gamma must be >= 0",
		},
		{
			"min_spread_above_max",
			func(c *Config) {
				c.Strategy.MarketMaking.MinSpreadPct = 0.05
				c.Strategy.MarketMaking.MaxSpreadPct = 0.01
			},
			"min_spread_pct",
		},
		{
			"vol_calm_above_elevated",
			func(c *Config) {
				c.Strategy.MarketMaking.VolCalmThreshold = 0.06
				c.Strategy.MarketMaking.VolElevatedThreshold = 0.05
			},
			"vol_calm_threshold",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := validMMConfig()
			tt.modify(&cfg)
			err := cfg.Validate()
			assert.Error(t, err)
			assert.Contains(t, err.Error(), tt.errMsg)
		})
	}
}

func TestValidate_FundingArb_Invalid(t *testing.T) {
	tests := []struct {
		name   string
		modify func(*Config)
		errMsg string
	}{
		{
			"zero_min_funding_rate",
			func(c *Config) { c.Strategy.FundingArb.MinFundingRate = 0 },
			"min_funding_rate must be > 0",
		},
		{
			"negative_exit_threshold",
			func(c *Config) { c.Strategy.FundingArb.ExitThreshold = -0.001 },
			"exit_threshold must be >= 0",
		},
		{
			"exit_above_min_rate",
			func(c *Config) {
				c.Strategy.FundingArb.ExitThreshold = 0.001
				c.Strategy.FundingArb.MinFundingRate = 0.0005
			},
			"exit_threshold",
		},
		{
			"zero_max_positions",
			func(c *Config) { c.Strategy.FundingArb.MaxPositions = 0 },
			"max_positions must be > 0",
		},
		{
			"max_loss_too_high",
			func(c *Config) { c.Strategy.FundingArb.MaxLossPct = 1.0 },
			"max_loss_pct must be > 0 and < 1.0",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := validFundingArbConfig()
			tt.modify(&cfg)
			err := cfg.Validate()
			assert.Error(t, err)
			assert.Contains(t, err.Error(), tt.errMsg)
		})
	}
}

func TestValidate_BasisTrade_Invalid(t *testing.T) {
	tests := []struct {
		name   string
		modify func(*Config)
		errMsg string
	}{
		{
			"zero_min_basis",
			func(c *Config) { c.Strategy.BasisTrade.MinBasisAnnualized = 0 },
			"min_basis_annualized must be > 0",
		},
		{
			"negative_exit_basis",
			func(c *Config) { c.Strategy.BasisTrade.ExitBasis = -0.01 },
			"exit_basis must be >= 0",
		},
		{
			"exit_above_min_basis",
			func(c *Config) {
				c.Strategy.BasisTrade.ExitBasis = 0.20
				c.Strategy.BasisTrade.MinBasisAnnualized = 0.15
			},
			"exit_basis",
		},
		{
			"zero_position_size",
			func(c *Config) { c.Strategy.BasisTrade.PositionSizeUSD = 0 },
			"position_size_usd must be > 0",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := validBasisTradeConfig()
			tt.modify(&cfg)
			err := cfg.Validate()
			assert.Error(t, err)
			assert.Contains(t, err.Error(), tt.errMsg)
		})
	}
}
