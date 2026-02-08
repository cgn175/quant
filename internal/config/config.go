package config

import (
	"fmt"
	"strings"

	"github.com/spf13/viper"
)

type Config struct {
	Exchange   ExchangeConfig   `mapstructure:"exchange"`
	Symbols    []string         `mapstructure:"symbols"`
	BarSize    string           `mapstructure:"bar_size"`
	Sentiment  SentimentConfig  `mapstructure:"sentiment"`
	Risk       RiskConfig       `mapstructure:"risk"`
	Model      ModelConfig      `mapstructure:"model"`
	Execution  ExecutionConfig  `mapstructure:"execution"`
	Monitoring MonitoringConfig `mapstructure:"monitoring"`
	Alerts     AlertsConfig     `mapstructure:"alerts"`
	Mode       string           `mapstructure:"mode"`
	Strategy   StrategyConfig   `mapstructure:"strategy"`
}

type ExchangeConfig struct {
	Name      string `mapstructure:"name"`
	APIKey    string `mapstructure:"api_key"`
	APISecret string `mapstructure:"api_secret"`
	Testnet   bool   `mapstructure:"testnet"`
}

type SentimentConfig struct {
	URL                     string  `mapstructure:"url"`
	PollIntervalSeconds     int     `mapstructure:"poll_interval_seconds"`
	SentimentThresholdLong  float64 `mapstructure:"sentiment_threshold_long"`
	SentimentThresholdShort float64 `mapstructure:"sentiment_threshold_short"`
}

type RiskConfig struct {
	MaxRiskPerTradePct float64 `mapstructure:"max_risk_per_trade_pct"`
	MaxDailyLossPct    float64 `mapstructure:"max_daily_loss_pct"`
	MaxOpenPositions   int     `mapstructure:"max_open_positions"`
	MaxLeverage        float64 `mapstructure:"max_leverage"`
	InitialEquityVal   float64 `mapstructure:"initial_equity"`
}

// InitialEquity returns the configured initial equity, defaulting to 10000
// if not set or zero.
func (r RiskConfig) InitialEquity() float64 {
	if r.InitialEquityVal > 0 {
		return r.InitialEquityVal
	}
	return 10000.0
}

type ModelConfig struct {
	Path           string  `mapstructure:"path"`
	RuntimeLibPath string  `mapstructure:"runtime_lib_path"`
	ThresholdUp    float64 `mapstructure:"threshold_up"`
	ThresholdDown  float64 `mapstructure:"threshold_down"`
	NumClasses     int     `mapstructure:"num_classes"` // 2 for binary, 3 for multi-class (default: 3)
	Timeframe      string  `mapstructure:"timeframe"`   // "5m", "4h" (default: "5m")
}

type ExecutionConfig struct {
	UseLimitOrders bool    `mapstructure:"use_limit_orders"`
	SlippageBP     float64 `mapstructure:"slippage_bp"`
	FeePercentVal  float64 `mapstructure:"fee_percent"`
}

// FeePercent returns the configured fee percentage (e.g. 0.1 means 0.1%).
// Defaults to 0.1 if not set or zero.
func (e ExecutionConfig) FeePercent() float64 {
	if e.FeePercentVal > 0 {
		return e.FeePercentVal
	}
	return 0.1
}

type MonitoringConfig struct {
	PrometheusPort int `mapstructure:"prometheus_port"`
}

type AlertsConfig struct {
	TelegramBotToken string `mapstructure:"telegram_bot_token"`
	TelegramChatID   int64  `mapstructure:"telegram_chat_id"`
}

// StrategyConfig holds strategy-specific settings.
type StrategyConfig struct {
	Type           string              `mapstructure:"type"` // "ml", "trend_following"
	DonchianPeriod int                 `mapstructure:"donchian_period"`
	EMAFast        int                 `mapstructure:"ema_fast"`
	EMASlow        int                 `mapstructure:"ema_slow"`
	EMAConfirmBars int                 `mapstructure:"ema_confirm_bars"`
	EMATrend       int                 `mapstructure:"ema_trend"`
	VolumePeriod   int                 `mapstructure:"volume_period"`
	ATRPeriod      int                 `mapstructure:"atr_period"`
	ATRStopMult    float64             `mapstructure:"atr_stop_multiplier"`
	ADXPeriod      int                 `mapstructure:"adx_period"`
	ADXThreshold   float64             `mapstructure:"adx_threshold"`
	VolatilityLow  float64             `mapstructure:"volatility_low"`
	VolatilityHigh float64             `mapstructure:"volatility_high"`
	FundingFilter  FundingFilterConfig  `mapstructure:"funding_filter"`
	PartialExits   PartialExitsConfig   `mapstructure:"partial_exits"`
	ChandelierLookback int             `mapstructure:"chandelier_lookback"`
	MaxPositionsPerSector int          `mapstructure:"max_positions_per_sector"` // Patch 3: Correlation Guard
}

// FundingFilterConfig holds funding rate filter parameters.
type FundingFilterConfig struct {
	Enabled            bool    `mapstructure:"enabled"`
	ExtremeThreshold   float64 `mapstructure:"extreme_threshold"`
	ElevatedThreshold  float64 `mapstructure:"elevated_threshold"`
	SizeReduction      float64 `mapstructure:"size_reduction"`
	PollIntervalSec    int     `mapstructure:"poll_interval_seconds"`
}

// PartialExitsConfig holds partial exit parameters.
type PartialExitsConfig struct {
	Enabled        bool    `mapstructure:"enabled"`
	FirstTargetR   float64 `mapstructure:"first_target_r"`
	FirstExitPct   float64 `mapstructure:"first_exit_pct"`
	SecondTargetR  float64 `mapstructure:"second_target_r"`
	SecondExitPct  float64 `mapstructure:"second_exit_pct"`
}

// IsTrendFollowing returns true if the strategy type is trend_following.
func (c *Config) IsTrendFollowing() bool {
	return c.Strategy.Type == "trend_following"
}

// Validate checks configuration values for correctness.
func (c *Config) Validate() error {
	// Risk parameters (apply to all strategies)
	if c.Risk.MaxRiskPerTradePct <= 0 || c.Risk.MaxRiskPerTradePct >= 100 {
		return fmt.Errorf("risk.max_risk_per_trade_pct must be > 0 and < 100, got %.2f", c.Risk.MaxRiskPerTradePct)
	}
	if c.Risk.MaxDailyLossPct <= 0 || c.Risk.MaxDailyLossPct >= 100 {
		return fmt.Errorf("risk.max_daily_loss_pct must be > 0 and < 100, got %.2f", c.Risk.MaxDailyLossPct)
	}
	if c.Risk.MaxOpenPositions <= 0 {
		return fmt.Errorf("risk.max_open_positions must be > 0, got %d", c.Risk.MaxOpenPositions)
	}
	if c.Risk.MaxLeverage <= 0 {
		return fmt.Errorf("risk.max_leverage must be > 0, got %.2f", c.Risk.MaxLeverage)
	}

	// Trend-following-specific validation
	if c.IsTrendFollowing() {
		s := c.Strategy
		if s.DonchianPeriod <= 0 {
			return fmt.Errorf("strategy.donchian_period must be > 0, got %d", s.DonchianPeriod)
		}
		if s.EMAFast <= 0 {
			return fmt.Errorf("strategy.ema_fast must be > 0, got %d", s.EMAFast)
		}
		if s.EMASlow <= s.EMAFast {
			return fmt.Errorf("strategy.ema_slow (%d) must be > ema_fast (%d)", s.EMASlow, s.EMAFast)
		}
		if s.EMATrend <= 0 {
			return fmt.Errorf("strategy.ema_trend must be > 0, got %d", s.EMATrend)
		}
		if s.ATRPeriod <= 0 {
			return fmt.Errorf("strategy.atr_period must be > 0, got %d", s.ATRPeriod)
		}
		if s.ATRStopMult <= 0 {
			return fmt.Errorf("strategy.atr_stop_multiplier must be > 0, got %.2f", s.ATRStopMult)
		}
		if s.ADXPeriod <= 0 {
			return fmt.Errorf("strategy.adx_period must be > 0, got %d", s.ADXPeriod)
		}
		if s.ADXThreshold <= 0 {
			return fmt.Errorf("strategy.adx_threshold must be > 0, got %.2f", s.ADXThreshold)
		}
		if s.VolatilityLow >= s.VolatilityHigh {
			return fmt.Errorf("strategy.volatility_low (%.2f) must be < volatility_high (%.2f)", s.VolatilityLow, s.VolatilityHigh)
		}
		if s.ChandelierLookback <= 0 {
			return fmt.Errorf("strategy.chandelier_lookback must be > 0, got %d", s.ChandelierLookback)
		}

		// Partial exits validation
		if s.PartialExits.Enabled {
			if s.PartialExits.FirstTargetR <= 0 {
				return fmt.Errorf("strategy.partial_exits.first_target_r must be > 0, got %.2f", s.PartialExits.FirstTargetR)
			}
			if s.PartialExits.SecondTargetR <= s.PartialExits.FirstTargetR {
				return fmt.Errorf("strategy.partial_exits.second_target_r (%.2f) must be > first_target_r (%.2f)", s.PartialExits.SecondTargetR, s.PartialExits.FirstTargetR)
			}
			if s.PartialExits.FirstExitPct <= 0 || s.PartialExits.FirstExitPct > 1.0 {
				return fmt.Errorf("strategy.partial_exits.first_exit_pct must be > 0 and <= 1.0, got %.2f", s.PartialExits.FirstExitPct)
			}
			if s.PartialExits.SecondExitPct <= 0 || s.PartialExits.SecondExitPct > 1.0 {
				return fmt.Errorf("strategy.partial_exits.second_exit_pct must be > 0 and <= 1.0, got %.2f", s.PartialExits.SecondExitPct)
			}
		}
	}

	return nil
}

func Load(path string) (*Config, error) {
	v := viper.New()

	v.SetConfigFile(path)
	v.SetConfigType("yaml")

	v.SetEnvPrefix("QUANT")
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))
	v.AutomaticEnv()

	setDefaults(v)

	if err := v.ReadInConfig(); err != nil {
		return nil, fmt.Errorf("failed to read config: %w", err)
	}

	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return nil, fmt.Errorf("failed to unmarshal config: %w", err)
	}

	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("config validation failed: %w", err)
	}

	return &cfg, nil
}

func setDefaults(v *viper.Viper) {
	v.SetDefault("bar_size", "1m")
	v.SetDefault("mode", "paper")
	v.SetDefault("symbols", []string{"BTCUSDT"})

	v.SetDefault("exchange.name", "binance")
	v.SetDefault("exchange.testnet", true)

	v.SetDefault("sentiment.url", "http://localhost:8000")
	v.SetDefault("sentiment.poll_interval_seconds", 60)
	v.SetDefault("sentiment.sentiment_threshold_long", 0.3)
	v.SetDefault("sentiment.sentiment_threshold_short", -0.3)

	v.SetDefault("risk.max_risk_per_trade_pct", 1.0)
	v.SetDefault("risk.max_daily_loss_pct", 3.0)
	v.SetDefault("risk.max_open_positions", 3)
	v.SetDefault("risk.max_leverage", 2.0)
	v.SetDefault("risk.initial_equity", 10000.0)

	v.SetDefault("model.threshold_up", 0.6)
	v.SetDefault("model.threshold_down", 0.6)
	v.SetDefault("model.num_classes", 3)
	v.SetDefault("model.timeframe", "5m")

	v.SetDefault("execution.use_limit_orders", false)
	v.SetDefault("execution.slippage_bp", 5.0)
	v.SetDefault("execution.fee_percent", 0.1)

	v.SetDefault("monitoring.prometheus_port", 9090)

	// Strategy defaults (Plan D: Trend Following)
	v.SetDefault("strategy.type", "ml")
	v.SetDefault("strategy.donchian_period", 20)
	v.SetDefault("strategy.ema_fast", 9)
	v.SetDefault("strategy.ema_slow", 21)
	v.SetDefault("strategy.ema_confirm_bars", 5)
	v.SetDefault("strategy.ema_trend", 50)
	v.SetDefault("strategy.volume_period", 20)
	v.SetDefault("strategy.atr_period", 14)
	v.SetDefault("strategy.atr_stop_multiplier", 3.0)
	v.SetDefault("strategy.adx_period", 14)
	v.SetDefault("strategy.adx_threshold", 20.0)
	v.SetDefault("strategy.volatility_low", 0.5)
	v.SetDefault("strategy.volatility_high", 2.5)
	v.SetDefault("strategy.chandelier_lookback", 10)
	v.SetDefault("strategy.max_positions_per_sector", 1) // Patch 3: Correlation Guard
	v.SetDefault("strategy.funding_filter.enabled", true)
	v.SetDefault("strategy.funding_filter.extreme_threshold", 0.0005)
	v.SetDefault("strategy.funding_filter.elevated_threshold", 0.0003)
	v.SetDefault("strategy.funding_filter.size_reduction", 0.5)
	v.SetDefault("strategy.funding_filter.poll_interval_seconds", 300)
	v.SetDefault("strategy.partial_exits.enabled", true)
	v.SetDefault("strategy.partial_exits.first_target_r", 3.0)
	v.SetDefault("strategy.partial_exits.first_exit_pct", 0.25)
	v.SetDefault("strategy.partial_exits.second_target_r", 6.0)
	v.SetDefault("strategy.partial_exits.second_exit_pct", 0.25)
}
