package metrics

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

// Metrics holds all prometheus metrics
type Metrics struct {
	// Equity metrics
	Equity        prometheus.Gauge
	RealizedPnL   prometheus.Gauge
	UnrealizedPnL prometheus.Gauge
	DailyPnL      prometheus.Gauge
	MaxDrawdown   prometheus.Gauge

	// Market Making metrics
	MMVolatilityRegime  *prometheus.GaugeVec // label: regime (calm, normal, elevated, extreme)
	MMQuotesHaltedTotal prometheus.Counter   // total times quoting halted due to extreme vol
	MMOrderBookImbalance *prometheus.GaugeVec // label: symbol - order book imbalance [-1, 1]

	// Position metrics
	OpenPositions    prometheus.Gauge
	MaxOpenPositions prometheus.Gauge

	// Trade metrics
	TotalTrades   prometheus.Counter
	WinningTrades prometheus.Counter
	LosingTrades  prometheus.Counter
	WinRate       prometheus.Gauge
	ProfitFactor  prometheus.Gauge

	// Per-symbol metrics
	PositionSize           prometheus.GaugeVec
	UnrealizedPnLPerSymbol prometheus.GaugeVec
	SentimentScore         prometheus.GaugeVec
	Sentiment1h            prometheus.GaugeVec
	Sentiment24h           prometheus.GaugeVec
	SentimentVelocity      prometheus.GaugeVec
	MentionsZScore         prometheus.GaugeVec

	// Data ingestion metrics
	CandlesReceived     prometheus.CounterVec // per symbol
	CandlesClosed       prometheus.CounterVec // per symbol (only closed candles)
	WebSocketReconnects prometheus.Counter

	// System metrics
	ModelInferenceTime   prometheus.Histogram
	OrderExecutionTime   prometheus.Histogram
	SentimentAPILatency  prometheus.Histogram
	SignalGenerationTime prometheus.Histogram

	// ML Filter metrics
	MLFilterProb          prometheus.GaugeVec
	MLFilterErrorsTotal   prometheus.Counter
	MLFilterBlockedTotal  prometheus.CounterVec
	ADXFilterBlockedTotal prometheus.CounterVec
	MLFilterLatency       prometheus.Histogram
	MLFilterFallbackTotal prometheus.Counter

	// Momentum Filter metrics
	MomentumFilterBlockedTotal prometheus.CounterVec // blocked by momentum filter

	// Portfolio Monitor metrics
	PortfolioSymbolExposure prometheus.GaugeVec // exposure per symbol
	PortfolioTotalExposure  prometheus.Gauge   // total exposure across all symbols
	PortfolioEntriesBlocked prometheus.CounterVec // entries blocked by reason
}

// NewMetrics creates and registers prometheus metrics
func NewMetrics() *Metrics {
	return &Metrics{
		// Equity metrics
		Equity: promauto.NewGauge(prometheus.GaugeOpts{
			Name: "trading_equity",
			Help: "Current trading account equity",
		}),
		RealizedPnL: promauto.NewGauge(prometheus.GaugeOpts{
			Name: "trading_realized_pnl",
			Help: "Cumulative realized PnL",
		}),
		UnrealizedPnL: promauto.NewGauge(prometheus.GaugeOpts{
			Name: "trading_unrealized_pnl",
			Help: "Current unrealized PnL from open positions",
		}),
		DailyPnL: promauto.NewGauge(prometheus.GaugeOpts{
			Name: "trading_daily_pnl",
			Help: "PnL for the current trading day",
		}),
		MaxDrawdown: promauto.NewGauge(prometheus.GaugeOpts{
			Name: "trading_max_drawdown",
			Help: "Maximum drawdown from peak equity",
		}),

		// Position metrics
		OpenPositions: promauto.NewGauge(prometheus.GaugeOpts{
			Name: "trading_open_positions",
			Help: "Number of currently open positions",
		}),
		MaxOpenPositions: promauto.NewGauge(prometheus.GaugeOpts{
			Name: "trading_max_open_positions",
			Help: "Maximum allowed open positions",
		}),

		// Trade metrics
		TotalTrades: promauto.NewCounter(prometheus.CounterOpts{
			Name: "trading_total_trades",
			Help: "Total number of trades executed",
		}),
		WinningTrades: promauto.NewCounter(prometheus.CounterOpts{
			Name: "trading_winning_trades",
			Help: "Total number of winning trades",
		}),
		LosingTrades: promauto.NewCounter(prometheus.CounterOpts{
			Name: "trading_losing_trades",
			Help: "Total number of losing trades",
		}),
		WinRate: promauto.NewGauge(prometheus.GaugeOpts{
			Name: "trading_win_rate",
			Help: "Win rate (0-1)",
		}),
		ProfitFactor: promauto.NewGauge(prometheus.GaugeOpts{
			Name: "trading_profit_factor",
			Help: "Profit factor (gross wins / abs losses)",
		}),

		// Per-symbol metrics
		PositionSize: *promauto.NewGaugeVec(prometheus.GaugeOpts{
			Name: "trading_position_size",
			Help: "Current position size by symbol",
		}, []string{"symbol"}),
		UnrealizedPnLPerSymbol: *promauto.NewGaugeVec(prometheus.GaugeOpts{
			Name: "trading_unrealized_pnl_per_symbol",
			Help: "Unrealized PnL by symbol",
		}, []string{"symbol"}),
		SentimentScore: *promauto.NewGaugeVec(prometheus.GaugeOpts{
			Name: "sentiment_score",
			Help: "Current sentiment score by symbol (legacy - use sentiment_1h)",
		}, []string{"symbol"}),
		Sentiment1h: *promauto.NewGaugeVec(prometheus.GaugeOpts{
			Name: "sentiment_1h",
			Help: "1-hour sentiment score by symbol (-1 to +1)",
		}, []string{"symbol"}),
		Sentiment24h: *promauto.NewGaugeVec(prometheus.GaugeOpts{
			Name: "sentiment_24h",
			Help: "24-hour sentiment score by symbol (-1 to +1)",
		}, []string{"symbol"}),
		SentimentVelocity: *promauto.NewGaugeVec(prometheus.GaugeOpts{
			Name: "sentiment_velocity",
			Help: "Sentiment velocity (rate of change) by symbol",
		}, []string{"symbol"}),
		MentionsZScore: *promauto.NewGaugeVec(prometheus.GaugeOpts{
			Name: "mentions_zscore",
			Help: "Mentions z-score (anomaly detection) by symbol",
		}, []string{"symbol"}),

		// Data ingestion metrics
		CandlesReceived: *promauto.NewCounterVec(prometheus.CounterOpts{
			Name: "binance_candles_received_total",
			Help: "Total number of candle updates received from Binance WebSocket",
		}, []string{"symbol"}),
		CandlesClosed: *promauto.NewCounterVec(prometheus.CounterOpts{
			Name: "binance_candles_closed_total",
			Help: "Total number of closed candles received from Binance WebSocket",
		}, []string{"symbol"}),
		WebSocketReconnects: promauto.NewCounter(prometheus.CounterOpts{
			Name: "binance_websocket_reconnects_total",
			Help: "Total number of WebSocket reconnection attempts",
		}),

		// System metrics
		ModelInferenceTime: promauto.NewHistogram(prometheus.HistogramOpts{
			Name:    "model_inference_duration_seconds",
			Help:    "Model inference latency",
			Buckets: []float64{.001, .01, .05, .1, .5, 1},
		}),
		OrderExecutionTime: promauto.NewHistogram(prometheus.HistogramOpts{
			Name:    "order_execution_duration_seconds",
			Help:    "Order execution latency",
			Buckets: []float64{.01, .05, .1, .5, 1, 5},
		}),
		SentimentAPILatency: promauto.NewHistogram(prometheus.HistogramOpts{
			Name:    "sentiment_api_duration_seconds",
			Help:    "Sentiment API latency",
			Buckets: []float64{.1, .5, 1, 5, 10},
		}),
		SignalGenerationTime: promauto.NewHistogram(prometheus.HistogramOpts{
			Name:    "signal_generation_duration_seconds",
			Help:    "Signal generation latency",
			Buckets: []float64{.001, .01, .05, .1},
		}),

		// ML Filter metrics
		MLFilterProb: *promauto.NewGaugeVec(prometheus.GaugeOpts{
			Name: "ml_filter_probability",
			Help: "Last ML probability per symbol",
		}, []string{"symbol"}),
		MLFilterErrorsTotal: promauto.NewCounter(prometheus.CounterOpts{
			Name: "ml_filter_errors_total",
			Help: "Total ML service errors",
		}),
		MLFilterBlockedTotal: *promauto.NewCounterVec(prometheus.CounterOpts{
			Name: "ml_filter_blocked_total",
			Help: "Entries blocked by ML filter per symbol",
		}, []string{"symbol"}),
		ADXFilterBlockedTotal: *promauto.NewCounterVec(prometheus.CounterOpts{
			Name: "adx_filter_blocked_total",
			Help: "Entries blocked by ADX filter per symbol",
		}, []string{"symbol"}),
		MLFilterLatency: promauto.NewHistogram(prometheus.HistogramOpts{
			Name:    "ml_filter_latency_seconds",
			Help:    "ML service call latency",
			Buckets: []float64{.005, .01, .025, .05, .1, .2, .5},
		}),
		MLFilterFallbackTotal: promauto.NewCounter(prometheus.CounterOpts{
			Name: "ml_filter_fallback_total",
			Help: "Times ML filter fell back to ADX",
		}),

		// Momentum Filter metrics
		MomentumFilterBlockedTotal: *promauto.NewCounterVec(prometheus.CounterOpts{
			Name: "momentum_filter_blocked_total",
			Help: "Entries blocked by momentum filter per symbol",
		}, []string{"symbol"}),

		// Portfolio Monitor metrics
		PortfolioSymbolExposure: *promauto.NewGaugeVec(prometheus.GaugeOpts{
			Name: "portfolio_symbol_exposure_usd",
			Help: "Current USD exposure per symbol across all strategies",
		}, []string{"symbol"}),
		PortfolioTotalExposure: promauto.NewGauge(prometheus.GaugeOpts{
			Name: "portfolio_total_exposure_usd",
			Help: "Total USD exposure across all symbols and strategies",
		}),
		PortfolioEntriesBlocked: *promauto.NewCounterVec(prometheus.CounterOpts{
			Name: "portfolio_entries_blocked_total",
			Help: "Entries blocked by portfolio monitor per symbol and reason",
		}, []string{"symbol", "reason"}),

		// Market Making metrics
		MMVolatilityRegime: promauto.NewGaugeVec(prometheus.GaugeOpts{
			Name: "mm_volatility_regime",
			Help: "Current volatility regime for market making (1 = active, 0 = inactive)",
		}, []string{"regime"}),
		MMQuotesHaltedTotal: promauto.NewCounter(prometheus.CounterOpts{
			Name: "mm_quotes_halted_total",
			Help: "Total times market making quotes were halted due to extreme volatility",
		}),
		MMOrderBookImbalance: promauto.NewGaugeVec(prometheus.GaugeOpts{
			Name: "mm_order_book_imbalance",
			Help: "Order book imbalance [-1, 1] where +1 = all bids, -1 = all asks",
		}, []string{"symbol"}),
	}
}
