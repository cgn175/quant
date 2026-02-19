package config

import (
	"fmt"
	"strings"

	"github.com/spf13/viper"
)

type Config struct {
	Exchange        ExchangeConfig      `mapstructure:"exchange"`
	Symbols         []string            `mapstructure:"symbols"`
	BarSize         string              `mapstructure:"bar_size"`
	Sentiment       SentimentConfig     `mapstructure:"sentiment"`
	Risk            RiskConfig          `mapstructure:"risk"`
	PortfolioRisk   PortfolioRiskConfig `mapstructure:"portfolio_risk"`
	Model           ModelConfig         `mapstructure:"model"`
	Execution       ExecutionConfig     `mapstructure:"execution"`
	Monitoring      MonitoringConfig    `mapstructure:"monitoring"`
	Alerts          AlertsConfig        `mapstructure:"alerts"`
	Mode            string              `mapstructure:"mode"`
	Strategy        StrategyConfig      `mapstructure:"strategy"`
	Storage         StorageConfig       `mapstructure:"storage"`
}

type ExchangeConfig struct {
	Name      string `mapstructure:"name"`
	APIKey    string `mapstructure:"api_key"`
	APISecret string `mapstructure:"api_secret"`
	Testnet   bool   `mapstructure:"testnet"`

	// HubURL is the WebSocket URL of the central WS hub (e.g. "localhost:9090").
	// All bots connect to the hub which maintains a single Binance WS connection.
	HubURL string `mapstructure:"hub_url"`

	// Multi-exchange credentials for cross-exchange arbitrage
	BybitAPIKey      string `mapstructure:"bybit_api_key"`
	BybitAPISecret   string `mapstructure:"bybit_api_secret"`
	BybitTestnet     bool   `mapstructure:"bybit_testnet"`
	OKXAPIKey        string `mapstructure:"okx_api_key"`
	OKXAPISecret     string `mapstructure:"okx_api_secret"`
	OKXPassphrase    string `mapstructure:"okx_passphrase"`
}

type SentimentConfig struct {
	URL                     string   `mapstructure:"url"`
	PollIntervalSeconds     int      `mapstructure:"poll_interval_seconds"`
	SentimentThresholdLong  float64  `mapstructure:"sentiment_threshold_long"`
	SentimentThresholdShort float64  `mapstructure:"sentiment_threshold_short"`
	Enabled                 bool     `mapstructure:"enabled"`
	ScheduleTimes           []string `mapstructure:"schedule_times"`
	UseDatabase             bool     `mapstructure:"use_database"`
	DatabasePath            string   `mapstructure:"database_path"`
}

type RiskConfig struct {
	MaxRiskPerTradePct float64 `mapstructure:"max_risk_per_trade_pct"`
	MaxDailyLossPct    float64 `mapstructure:"max_daily_loss_pct"`
	MaxOpenPositions   int     `mapstructure:"max_open_positions"`
	MaxLeverage        float64 `mapstructure:"max_leverage"`
	InitialEquityVal   float64 `mapstructure:"initial_equity"`
}

// PortfolioRiskConfig holds cross-strategy position limit settings.
type PortfolioRiskConfig struct {
	MaxTotalPerpSpotExposure float64 `mapstructure:"max_total_perp_spot_exposure"` // Max $ across all strategies (default $100k)
	MaxPerSymbolExposure     float64 `mapstructure:"max_per_symbol_exposure"`      // Max $ per symbol (default $50k)
	EnableCorrelatedCheck    bool    `mapstructure:"enable_correlated_check"`      // Block correlated strategies on same symbol
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
	UseLimitOrders           bool    `mapstructure:"use_limit_orders"`
	AggressiveLimitTimeoutMs int     `mapstructure:"aggressive_limit_timeout_ms"` // timeout before market fallback (0 = no fallback)
	SlippageBP               float64 `mapstructure:"slippage_bp"`
	FeePercentVal            float64 `mapstructure:"fee_percent"`
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
	TelegramBotToken       string `mapstructure:"telegram_bot_token"`
	TelegramChatID         int64  `mapstructure:"telegram_chat_id"`
	EnableTelegramCommands bool   `mapstructure:"enable_telegram_commands"` // only one bot should have this enabled when running multiple bots
}

// StrategyConfig holds strategy-specific settings.
type StrategyConfig struct {
	Type                  string              `mapstructure:"type"` // "ml", "trend_following"
	DonchianPeriod        int                 `mapstructure:"donchian_period"`
	EMAFast               int                 `mapstructure:"ema_fast"`
	EMASlow               int                 `mapstructure:"ema_slow"`
	EMAConfirmBars        int                 `mapstructure:"ema_confirm_bars"`
	EMATrend              int                 `mapstructure:"ema_trend"`
	VolumePeriod          int                 `mapstructure:"volume_period"`
	ATRPeriod             int                 `mapstructure:"atr_period"`
	ATRStopMult           float64             `mapstructure:"atr_stop_multiplier"`
	ADXPeriod             int                 `mapstructure:"adx_period"`
	ADXThreshold          float64             `mapstructure:"adx_threshold"`
	VolatilityLow         float64             `mapstructure:"volatility_low"`
	VolatilityHigh        float64             `mapstructure:"volatility_high"`
	FundingFilter         FundingFilterConfig `mapstructure:"funding_filter"`
	OIFilter              OIFilterConfig      `mapstructure:"oi_filter"`
	PartialExits          PartialExitsConfig  `mapstructure:"partial_exits"`
	ChandelierLookback    int                 `mapstructure:"chandelier_lookback"`
	MaxPositionsPerSector int                 `mapstructure:"max_positions_per_sector"` // Patch 3: Correlation Guard
	MLFilter              MLFilterConfig      `mapstructure:"ml_filter"`
	RegimeFilter          RegimeFilterConfig  `mapstructure:"regime_filter"`
	DynamicStop           DynamicStopConfig   `mapstructure:"dynamic_stop"`
	MarketMaking          MarketMakingConfig  `mapstructure:"market_making"`
	FundingArb            FundingArbConfig    `mapstructure:"funding_arb"`
	BasisTrade            BasisTradeConfig    `mapstructure:"basis_trade"`
	Variant               string              `mapstructure:"variant"`

	// Time-based exit parameters
	TimeStopBars int     `mapstructure:"time_stop_bars"`  // Exit if position hasn't moved MinR after N bars
	TimeStopMinR float64 `mapstructure:"time_stop_min_r"` // Minimum R required to avoid time stop

	// Cross-sectional momentum filter
	MomentumFilter MomentumFilterConfig `mapstructure:"momentum_filter"`
}

// MomentumFilterConfig holds cross-sectional momentum filter parameters.
type MomentumFilterConfig struct {
	Enabled      bool    `mapstructure:"enabled"`       // Enable momentum filter (default: false)
	LookbackDays int     `mapstructure:"lookback_days"` // Lookback period in days (default: 21 = 3 weeks)
	TopPct       float64 `mapstructure:"top_pct"`       // Trade only top N% by momentum (default: 0.5 = 50%)
}


// MLFilterConfig holds ML inference filter parameters.
type MLFilterConfig struct {
	Enabled       bool    `mapstructure:"enabled"`
	URL           string  `mapstructure:"url"`
	Threshold     float64 `mapstructure:"threshold"`
	TimeoutMs     int     `mapstructure:"timeout_ms"`
	FailOpen      bool    `mapstructure:"fail_open"`
	FallbackToADX bool    `mapstructure:"fallback_to_adx"`
}

// RegimeFilterConfig holds Regime Classifier (Traffic Light) parameters.
type RegimeFilterConfig struct {
	Enabled            bool              `mapstructure:"enabled"`
	URL                string            `mapstructure:"url"`
	Threshold          float64           `mapstructure:"threshold"` // min prob_safe to allow trade
	TimeoutMs          int               `mapstructure:"timeout_ms"`
	FailOpen           bool              `mapstructure:"fail_open"`
	FallbackToADX      bool              `mapstructure:"fallback_to_adx"`
	SymbolVersions     map[string]string `mapstructure:"symbol_versions"` // per-symbol model version ("v1" or "v2")
	Ensemble           EnsembleConfig    `mapstructure:"ensemble"`
	DirectionalSymbols []string          `mapstructure:"directional_symbols"` // symbols using LONG/SHORT models
	
	// HMM regime detection (probabilistic states)
	UseHMM            bool    `mapstructure:"use_hmm"`             // Use HMM instead of RandomForest (default: false)
	HMMTrendingProb   float64 `mapstructure:"hmm_trending_prob"`   // Min probability for "trending" state (default: 0.6)
}

// EnsembleConfig holds regime+vol ensemble filter parameters.
type EnsembleConfig struct {
	Enabled    bool     `mapstructure:"enabled"`
	MaxStopPct float64  `mapstructure:"max_stop_pct"` // max predicted stop % to allow entry
	Symbols    []string `mapstructure:"symbols"`      // symbols to apply ensemble to
}

// DynamicStopConfig holds Volatility Predictor (Dynamic Stop-Loss) parameters.
type DynamicStopConfig struct {
	Enabled    bool    `mapstructure:"enabled"`
	URL        string  `mapstructure:"url"`
	TimeoutMs  int     `mapstructure:"timeout_ms"`
	FailOpen   bool    `mapstructure:"fail_open"`
	K          float64 `mapstructure:"k"`            // multiplier for predicted range → stop %
	MinStopPct float64 `mapstructure:"min_stop_pct"` // floor (e.g., 0.01 = 1%)
	MaxStopPct float64 `mapstructure:"max_stop_pct"` // ceiling (e.g., 0.04 = 4%)
}

// FundingFilterConfig holds funding rate filter parameters.
type FundingFilterConfig struct {
	Enabled           bool    `mapstructure:"enabled"`
	ExtremeThreshold  float64 `mapstructure:"extreme_threshold"`
	ElevatedThreshold float64 `mapstructure:"elevated_threshold"`
	SizeReduction     float64 `mapstructure:"size_reduction"`
	PollIntervalSec   int     `mapstructure:"poll_interval_seconds"`
}

// PartialExitsConfig holds partial exit parameters.
type PartialExitsConfig struct {
	Enabled       bool    `mapstructure:"enabled"`
	FirstTargetR  float64 `mapstructure:"first_target_r"`
	FirstExitPct  float64 `mapstructure:"first_exit_pct"`
	SecondTargetR float64 `mapstructure:"second_target_r"`
	SecondExitPct float64 `mapstructure:"second_exit_pct"`
}

// OIFilterConfig holds parameters for the open interest regime filter.
type OIFilterConfig struct {
	Enabled      bool    `mapstructure:"enabled"`
	ZScoreThresh float64 `mapstructure:"zscore_thresh"` // Skip entry if OI z-score > this (default 2.0)
	Lookback     int     `mapstructure:"lookback"`      // Number of samples for z-score calculation (default 30)
}

// MarketMakingConfig holds parameters for the pure market making strategy.
type MarketMakingConfig struct {
	SpreadPct     float64 `mapstructure:"spread_pct"`      // Base spread from mid-price (e.g., 0.001 = 0.1%)
	OrderAmount   float64 `mapstructure:"order_amount"`    // Size of bid/ask orders in base asset
	RefreshTimeMs int     `mapstructure:"refresh_time_ms"` // How often to cancel & replace orders

	// Inventory risk management (Avellaneda-Stoikov skewing)
	Gamma        float64 `mapstructure:"gamma"`         // Risk aversion parameter (higher = more aggressive skew)
	MaxInventory float64 `mapstructure:"max_inventory"` // Max absolute inventory before halting one side

	// Dynamic spread (volatility-adjusted)
	MinSpreadPct float64 `mapstructure:"min_spread_pct"` // Floor for dynamic spread
	MaxSpreadPct float64 `mapstructure:"max_spread_pct"` // Ceiling for dynamic spread
	VolLookback  int     `mapstructure:"vol_lookback"`   // Rolling window for volatility calculation

	// Volatility regime filter (protects against adverse selection during volatility spikes)
	VolRegimeEnabled     bool    `mapstructure:"vol_regime_enabled"`      // Enable volatility regime detection (default: true)
	VolRegimeATRPeriod   int     `mapstructure:"vol_regime_atr_period"`   // ATR period for regime calculation (default: 14)
	VolCalmThreshold     float64 `mapstructure:"vol_calm_threshold"`      // ATR% threshold for calm regime (default: 0.02 = 2%)
	VolElevatedThreshold float64 `mapstructure:"vol_elevated_threshold"`  // ATR% threshold for elevated regime (default: 0.05 = 5%)
	VolExtremeThreshold  float64 `mapstructure:"vol_extreme_threshold"`   // ATR% threshold for extreme regime (default: 0.10 = 10%)
	VolSpreadMultiplier  float64 `mapstructure:"vol_spread_multiplier"`   // Spread multiplier in elevated volatility (default: 3.0 = 3x)

	// Order book imbalance (directional edge from order flow)
	ImbalanceEnabled   bool    `mapstructure:"imbalance_enabled"`    // Enable order book imbalance detection (default: false)
	ImbalanceDepth     int     `mapstructure:"imbalance_depth"`      // Order book depth to analyze (default: 20)
	ImbalanceSkewFactor float64 `mapstructure:"imbalance_skew_factor"` // How much imbalance affects spread (default: 0.5 = 50%)
}

// FundingArbConfig holds parameters for the funding rate arbitrage strategy.
type FundingArbConfig struct {
	MinFundingRate  float64 `mapstructure:"min_funding_rate"`  // Minimum abs funding rate to enter (e.g., 0.0005 = 0.05%)
	ExitThreshold   float64 `mapstructure:"exit_threshold"`    // Close when abs funding drops below this
	MaxPositions    int     `mapstructure:"max_positions"`     // Max concurrent funding arb positions
	PositionSizeUSD float64 `mapstructure:"position_size_usd"` // USD value per position
	ScanIntervalMs  int     `mapstructure:"scan_interval_ms"`  // How often to check funding rates
	MaxLossPct      float64 `mapstructure:"max_loss_pct"`      // Max loss per position before forced close (e.g., 0.03 = 3%)
	DBPath          string  `mapstructure:"db_path"`           // Path to SQLite database for position/rate persistence
	DeltaNeutral    bool    `mapstructure:"delta_neutral"`     // Enable delta-neutral spot hedge

	// Momentum strategy (improves returns by 30-40%)
	UseMomentum        bool    `mapstructure:"use_momentum"`         // Enable momentum-based entry (default: false)
	MomentumMultiplier float64 `mapstructure:"momentum_multiplier"`  // Current must exceed avg_24h * multiplier (default: 1.2)
	MomentumExitEnable bool    `mapstructure:"momentum_exit_enable"` // Exit on momentum reversal (default: false)

	// Cross-exchange arbitrage
	CrossExchange        bool     `mapstructure:"cross_exchange"`         // Enable cross-exchange arbitrage
	MinSpreadBps         float64  `mapstructure:"min_spread_bps"`         // Minimum spread in basis points to enter (e.g., 50 = 0.5%)
	Exchanges            []string `mapstructure:"exchanges"`              // List of exchanges to use ["binance", "bybit", "okx"]
	ExchangeTestnet      map[string]bool `mapstructure:"exchange_testnet"` // Per-exchange testnet settings
}

// BasisTradeConfig holds parameters for the basis trade (spot-futures arbitrage) strategy.
type BasisTradeConfig struct {
	MinBasisAnnualized float64  `mapstructure:"min_basis_annualized"` // Min annualized basis to enter (e.g., 0.15 = 15%)
	ExitBasis          float64  `mapstructure:"exit_basis"`           // Exit when annualized basis drops below this
	MaxPositions       int      `mapstructure:"max_positions"`
	PositionSizeUSD    float64  `mapstructure:"position_size_usd"`
	ScanIntervalMs     int      `mapstructure:"scan_interval_ms"`
	DBPath             string   `mapstructure:"db_path"`
	CrossExchange      bool     `mapstructure:"cross_exchange"`       // Enable cross-exchange basis trading
	Exchanges          []string `mapstructure:"exchanges"`            // Exchanges to scan (e.g., ["binance", "bybit", "okx"])
}

// StorageConfig holds data persistence configuration.
type StorageConfig struct {
	CandleDBPath string `mapstructure:"candle_db_path"` // Path to SQLite candle database
	MaxDBRows    int    `mapstructure:"max_db_rows"`    // Max candles per symbol in DB
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
	v.SetDefault("exchange.hub_url", "localhost:9090")

	v.SetDefault("sentiment.url", "http://localhost:8000")
	v.SetDefault("sentiment.poll_interval_seconds", 60)
	v.SetDefault("sentiment.sentiment_threshold_long", 0.3)
	v.SetDefault("sentiment.sentiment_threshold_short", -0.3)
	v.SetDefault("sentiment.enabled", false)
	v.SetDefault("sentiment.schedule_times", []string{"08:00", "16:00"})
	v.SetDefault("sentiment.use_database", true)
	v.SetDefault("sentiment.database_path", "sentiment.db")

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
	v.SetDefault("strategy.ml_filter.enabled", false)
	v.SetDefault("strategy.ml_filter.url", "http://localhost:9001")
	v.SetDefault("strategy.ml_filter.threshold", 0.65)
	v.SetDefault("strategy.ml_filter.timeout_ms", 200)
	v.SetDefault("strategy.ml_filter.fail_open", false)
	v.SetDefault("strategy.ml_filter.fallback_to_adx", true)
	v.SetDefault("strategy.regime_filter.enabled", false)
	v.SetDefault("strategy.regime_filter.url", "http://localhost:9001")
	v.SetDefault("strategy.regime_filter.threshold", 0.55)
	v.SetDefault("strategy.regime_filter.timeout_ms", 200)
	v.SetDefault("strategy.regime_filter.fail_open", false)
	v.SetDefault("strategy.regime_filter.fallback_to_adx", true)
	v.SetDefault("strategy.regime_filter.ensemble.enabled", false)
	v.SetDefault("strategy.regime_filter.ensemble.max_stop_pct", 0.025)
	v.SetDefault("strategy.dynamic_stop.enabled", false)
	v.SetDefault("strategy.dynamic_stop.url", "http://localhost:9001")
	v.SetDefault("strategy.dynamic_stop.timeout_ms", 200)
	v.SetDefault("strategy.dynamic_stop.fail_open", true)
	v.SetDefault("strategy.dynamic_stop.k", 1.0)
	v.SetDefault("strategy.dynamic_stop.min_stop_pct", 0.01)
	v.SetDefault("strategy.dynamic_stop.max_stop_pct", 0.04)
	v.SetDefault("strategy.variant", "")

	// Market Making defaults
	v.SetDefault("strategy.market_making.spread_pct", 0.005)      // 0.5%
	v.SetDefault("strategy.market_making.order_amount", 0.01)     // 0.01 BTC/ETH
	v.SetDefault("strategy.market_making.refresh_time_ms", 10000) // 10s
	v.SetDefault("strategy.market_making.gamma", 0.1)             // inventory skew intensity
	v.SetDefault("strategy.market_making.max_inventory", 1.0)     // max 1 unit net inventory
	v.SetDefault("strategy.market_making.min_spread_pct", 0.001)  // 0.1% floor
	v.SetDefault("strategy.market_making.max_spread_pct", 0.02)   // 2% ceiling
	v.SetDefault("strategy.market_making.vol_lookback", 20)       // 20-tick rolling window

	// Volatility regime filter defaults
	v.SetDefault("strategy.market_making.vol_regime_enabled", true)       // enabled by default
	v.SetDefault("strategy.market_making.vol_regime_atr_period", 14)      // 14-period ATR
	v.SetDefault("strategy.market_making.vol_calm_threshold", 0.02)       // 2% ATR
	v.SetDefault("strategy.market_making.vol_elevated_threshold", 0.05)   // 5% ATR
	v.SetDefault("strategy.market_making.vol_extreme_threshold", 0.10)    // 10% ATR
	v.SetDefault("strategy.market_making.vol_spread_multiplier", 3.0)     // 3x spread in elevated vol

	// Funding arb defaults
	v.SetDefault("strategy.funding_arb.min_funding_rate", 0.0005) // 0.05% per 8h
	v.SetDefault("strategy.funding_arb.exit_threshold", 0.0001)   // 0.01% per 8h
	v.SetDefault("strategy.funding_arb.max_positions", 3)
	v.SetDefault("strategy.funding_arb.position_size_usd", 1000.0) // $1000 per position
	v.SetDefault("strategy.funding_arb.scan_interval_ms", 300000)  // 5 minutes
	v.SetDefault("strategy.funding_arb.max_loss_pct", 0.03)        // 3% max loss per position
	v.SetDefault("strategy.funding_arb.db_path", "funding.db")    // SQLite DB for positions/rates
	v.SetDefault("strategy.funding_arb.delta_neutral", true)

	// Basis trade defaults
	v.SetDefault("strategy.basis_trade.min_basis_annualized", 0.15)
	v.SetDefault("strategy.basis_trade.exit_basis", 0.05)
	v.SetDefault("strategy.basis_trade.max_positions", 3)
	v.SetDefault("strategy.basis_trade.position_size_usd", 1000.0)
	v.SetDefault("strategy.basis_trade.scan_interval_ms", 300000)
	v.SetDefault("strategy.basis_trade.db_path", "basis.db")

	// Portfolio risk defaults
	v.SetDefault("portfolio_risk.max_total_perp_spot_exposure", 100000.0) // $100k default
	v.SetDefault("portfolio_risk.max_per_symbol_exposure", 50000.0)      // $50k default
	v.SetDefault("portfolio_risk.enable_correlated_check", true)         // Block funding_arb + basis_trade overlap

	// OI filter defaults
	v.SetDefault("strategy.oi_filter.enabled", false)
	v.SetDefault("strategy.oi_filter.zscore_thresh", 2.0)
	v.SetDefault("strategy.oi_filter.lookback", 30)

	// Momentum filter defaults
	v.SetDefault("strategy.momentum_filter.enabled", false)
	v.SetDefault("strategy.momentum_filter.lookback_days", 21)
	v.SetDefault("strategy.momentum_filter.top_pct", 0.5)

	// Storage defaults
	v.SetDefault("storage.candle_db_path", "candles.db")
	v.SetDefault("storage.max_db_rows", 2000) // ~333 days of 4h candles per symbol
}
