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
}

type ExchangeConfig struct {
	Name      string `mapstructure:"name"`
	APIKey    string `mapstructure:"api_key"`
	APISecret string `mapstructure:"api_secret"`
	Testnet   bool   `mapstructure:"testnet"`
}

type SentimentConfig struct {
	URL                    string  `mapstructure:"url"`
	PollIntervalSeconds    int     `mapstructure:"poll_interval_seconds"`
	SentimentThresholdLong float64 `mapstructure:"sentiment_threshold_long"`
	SentimentThresholdShort float64 `mapstructure:"sentiment_threshold_short"`
}

type RiskConfig struct {
	MaxRiskPerTradePct float64 `mapstructure:"max_risk_per_trade_pct"`
	MaxDailyLossPct    float64 `mapstructure:"max_daily_loss_pct"`
	MaxOpenPositions   int     `mapstructure:"max_open_positions"`
	MaxLeverage        float64 `mapstructure:"max_leverage"`
}

type ModelConfig struct {
	Path             string  `mapstructure:"path"`
	RuntimeLibPath   string  `mapstructure:"runtime_lib_path"`
	ThresholdUp      float64 `mapstructure:"threshold_up"`
	ThresholdDown    float64 `mapstructure:"threshold_down"`
}

type ExecutionConfig struct {
	UseLimitOrders bool    `mapstructure:"use_limit_orders"`
	SlippageBP     float64 `mapstructure:"slippage_bp"`
}

type MonitoringConfig struct {
	PrometheusPort int `mapstructure:"prometheus_port"`
}

type AlertsConfig struct {
	TelegramBotToken string `mapstructure:"telegram_bot_token"`
	TelegramChatID   int64  `mapstructure:"telegram_chat_id"`
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

	v.SetDefault("model.threshold_up", 0.6)
	v.SetDefault("model.threshold_down", 0.6)

	v.SetDefault("execution.use_limit_orders", false)
	v.SetDefault("execution.slippage_bp", 5.0)

	v.SetDefault("monitoring.prometheus_port", 9090)
}
