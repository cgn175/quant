package metrics

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

// Metrics holds all prometheus metrics
type Metrics struct {
	// Equity metrics
	Equity               prometheus.Gauge
	RealizedPnL          prometheus.Gauge
	UnrealizedPnL        prometheus.Gauge
	DailyPnL             prometheus.Gauge
	MaxDrawdown          prometheus.Gauge

	// Position metrics
	OpenPositions        prometheus.Gauge
	MaxOpenPositions     prometheus.Gauge
	
	// Trade metrics
	TotalTrades          prometheus.Counter
	WinningTrades        prometheus.Counter
	LosingTrades         prometheus.Counter
	WinRate              prometheus.Gauge
	ProfitFactor         prometheus.Gauge

	// Per-symbol metrics
	PositionSize         prometheus.GaugeVec
	UnrealizedPnLPerSymbol prometheus.GaugeVec
	SentimentScore       prometheus.GaugeVec

	// System metrics
	ModelInferenceTime   prometheus.Histogram
	OrderExecutionTime   prometheus.Histogram
	SentimentAPILatency  prometheus.Histogram
	SignalGenerationTime prometheus.Histogram
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
			Help: "Current sentiment score by symbol",
		}, []string{"symbol"}),

		// System metrics
		ModelInferenceTime: promauto.NewHistogram(prometheus.HistogramOpts{
			Name: "model_inference_duration_seconds",
			Help: "Model inference latency",
			Buckets: []float64{.001, .01, .05, .1, .5, 1},
		}),
		OrderExecutionTime: promauto.NewHistogram(prometheus.HistogramOpts{
			Name: "order_execution_duration_seconds",
			Help: "Order execution latency",
			Buckets: []float64{.01, .05, .1, .5, 1, 5},
		}),
		SentimentAPILatency: promauto.NewHistogram(prometheus.HistogramOpts{
			Name: "sentiment_api_duration_seconds",
			Help: "Sentiment API latency",
			Buckets: []float64{.1, .5, 1, 5, 10},
		}),
		SignalGenerationTime: promauto.NewHistogram(prometheus.HistogramOpts{
			Name: "signal_generation_duration_seconds",
			Help: "Signal generation latency",
			Buckets: []float64{.001, .01, .05, .1},
		}),
	}
}
