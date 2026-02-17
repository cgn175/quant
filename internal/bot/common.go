// Package bot provides the core bot runner implementations for different trading strategies.
package bot

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/rs/zerolog/log"
	"github.com/spf13/cobra"

	"github.com/cgn175/quant-bot/internal/alerts"
	"github.com/cgn175/quant-bot/internal/config"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/execution"
	"github.com/cgn175/quant-bot/internal/metrics"
	"github.com/cgn175/quant-bot/internal/risk"
	"github.com/cgn175/quant-bot/internal/sentiment"
	"github.com/cgn175/quant-bot/internal/strategy"
)

// tickEvent is sent from the WebSocket candle handler to the per-symbol
// processing goroutine. This decouples the WS read loop from the
// (potentially slow) feature-building / model-inference / order-execution
// pipeline so we never block the WebSocket connection.
type tickEvent struct {
	symbol string
	candle exchange.Candle
}

// CommonDeps bundles common dependencies shared across strategy implementations.
type CommonDeps struct {
	Cfg            *config.Config
	RiskMgr        *risk.Manager
	ExecEngine     *execution.Engine
	Executor       execution.Executor
	Prom           *metrics.Metrics
	AlertMgr       *alerts.Manager
	ExchangeClient exchange.Client
}

// SetupContext creates a cancellable context with signal handling.
func SetupContext(cmd *cobra.Command) (context.Context, context.CancelFunc) {
	ctx, cancel := context.WithCancel(cmd.Context())

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		select {
		case sig := <-sigCh:
			log.Info().Str("signal", sig.String()).Msg("received shutdown signal")
			cancel()
		case <-ctx.Done():
		}
	}()

	return ctx, cancel
}

// SetupRiskManager creates a risk manager from config.
func SetupRiskManager(cfg *config.Config) *risk.Manager {
	feePercent := cfg.Execution.FeePercent()
	riskConfig := risk.Config{
		InitialEquity:      cfg.Risk.InitialEquity(),
		MaxRiskPerTradePct: cfg.Risk.MaxRiskPerTradePct,
		MaxDailyLossPct:    cfg.Risk.MaxDailyLossPct,
		MaxOpenPositions:   cfg.Risk.MaxOpenPositions,
		MaxLeverage:        cfg.Risk.MaxLeverage,
		FeePercent:         feePercent,
	}
	return risk.NewManager(riskConfig)
}

// SetupExecutor creates the appropriate executor based on mode.
func SetupExecutor(cfg *config.Config) execution.Executor {
	if cfg.Mode == "live" {
		log.Info().Msg("using live trading executor")
		return execution.NewLiveExecutor(cfg.Exchange.APIKey, cfg.Exchange.APISecret, cfg.Exchange.Testnet)
	}
	log.Info().Msg("using paper trading executor")
	return execution.NewPaperExecutor(cfg.Execution.SlippageBP, cfg.Execution.FeePercent())
}

// SetupExecutionEngine creates the execution engine.
func SetupExecutionEngine(cfg *config.Config, executor execution.Executor) *execution.Engine {
	execConfig := execution.Config{
		Mode:                     cfg.Mode,
		UseLimitOrders:           cfg.Execution.UseLimitOrders,
		AggressiveLimitTimeoutMs: cfg.Execution.AggressiveLimitTimeoutMs,
		SlippageBP:               cfg.Execution.SlippageBP,
		FeePercent:               cfg.Execution.FeePercent(),
	}
	return execution.NewEngine(execConfig, executor)
}

// SetupMetrics initializes Prometheus metrics.
func SetupMetrics(cfg *config.Config) *metrics.Metrics {
	prom := metrics.NewMetrics()
	prom.MaxOpenPositions.Set(float64(cfg.Risk.MaxOpenPositions))
	return prom
}

// SetupAlertManager creates the Telegram alert manager.
func SetupAlertManager(cfg *config.Config) *alerts.Manager {
	var alertMgr *alerts.Manager
	var err error

	if cfg.Alerts.TelegramBotToken != "" && cfg.Alerts.TelegramChatID != 0 {
		alertMgr, err = alerts.NewManager(alerts.Config{
			TelegramToken: cfg.Alerts.TelegramBotToken,
			ChatID:        cfg.Alerts.TelegramChatID,
			RateLimitMs:   5000,
			Enabled:       true,
		}, log.Logger)
		if err != nil {
			log.Warn().Err(err).Msg("failed to init telegram alerts, continuing without")
		}
	}
	if alertMgr == nil {
		alertMgr, _ = alerts.NewManager(alerts.Config{Enabled: false}, log.Logger)
	}
	return alertMgr
}

// SetupSentimentClient creates and starts the sentiment client if enabled.
func SetupSentimentClient(cfg *config.Config) *sentiment.Client {
	if !cfg.Sentiment.Enabled {
		return nil
	}
	client := sentiment.NewClient(
		cfg.Sentiment.URL,
		time.Duration(cfg.Sentiment.PollIntervalSeconds)*time.Second,
	)
	client.Start(cfg.Symbols)
	return client
}

// SetupExchangeClient creates the exchange client via WS hub.
func SetupExchangeClient(cfg *config.Config) exchange.Client {
	log.Info().Str("hub_url", cfg.Exchange.HubURL).Msg("using WS hub for market data")
	return exchange.NewHubClient(cfg.Exchange.HubURL, cfg.Exchange.Testnet)
}

// NewExchangeClient creates an exchange.Client that connects via the central WS hub.
// This is an alias for SetupExchangeClient for external use.
func NewExchangeClient(cfg *config.Config) exchange.Client {
	return SetupExchangeClient(cfg)
}

// CreateTickChannels creates per-symbol tick channels.
func CreateTickChannels(symbols []string) map[string]chan tickEvent {
	tickChans := make(map[string]chan tickEvent, len(symbols))
	for _, sym := range symbols {
		tickChans[sym] = make(chan tickEvent, 64)
	}
	return tickChans
}

// SubscribeToMarketData subscribes to candle data for all symbols.
func SubscribeToMarketData(client exchange.Client, symbols []string, barSize string, tickChans map[string]chan tickEvent) {
	for _, sym := range symbols {
		sym := sym
		ch := tickChans[sym]
		if err := client.SubscribeCandles(sym, barSize, func(c exchange.Candle) {
			select {
			case ch <- tickEvent{symbol: sym, candle: c}:
			default:
				log.Warn().Str("symbol", sym).Msg("tick channel full, dropping candle")
			}
		}); err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("failed to subscribe")
		}
	}
}

// CloseAllPositions closes all open positions during graceful shutdown.
func CloseAllPositions(riskMgr *risk.Manager, execEngine *execution.Engine, alertMgr *alerts.Manager) {
	positions := riskMgr.GetAllPositions()
	if len(positions) == 0 {
		return
	}

	log.Info().Int("count", len(positions)).Msg("closing all open positions on shutdown")

	for sym, pos := range positions {
		exitPrice := pos.EntryPrice
		if pos.UnrealizedPnL != 0 {
			if pos.Side == "LONG" {
				exitPrice = pos.EntryPrice + pos.UnrealizedPnL/pos.Size
			} else {
				exitPrice = pos.EntryPrice - pos.UnrealizedPnL/pos.Size
			}
		}

		_, err := execEngine.ClosePosition(sym, pos.Side, exitPrice, pos.Size, "shutdown", strategy.SignalNone, "shutdown", pos.EntryPrice, pos.EntryTime)
		if err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("failed to close position on shutdown")
			continue
		}

		pnl, err := riskMgr.ClosePosition(sym, exitPrice)
		if err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("risk manager close on shutdown failed")
			continue
		}

		log.Info().
			Str("symbol", sym).
			Float64("pnl", pnl).
			Msg("position closed on shutdown")

		alertMgr.TradeClosed(sym, pos.Side, pos.EntryPrice, exitPrice, pos.Size, pnl, "shutdown")
	}
}

// SendStartupAlert sends the bot started alert.
func SendStartupAlert(alertMgr *alerts.Manager, cfg *config.Config) {
	alertMgr.BotStarted(fmt.Sprintf(
		"Strategy: %s\nMode: %s\nSymbols: %v\nRisk/trade: %.1f%%\nDaily loss limit: %.1f%%",
		cfg.Strategy.Type, cfg.Mode, cfg.Symbols, cfg.Risk.MaxRiskPerTradePct, cfg.Risk.MaxDailyLossPct,
	))
}

// RunPeriodicTasks handles recurring maintenance: metric snapshots and daily PnL summary.
func RunPeriodicTasks(ctx context.Context, riskMgr *risk.Manager, execEngine *execution.Engine, prom *metrics.Metrics, alertMgr *alerts.Manager) {
	dailyTicker := time.NewTicker(24 * time.Hour)
	defer dailyTicker.Stop()

	statsTicker := time.NewTicker(30 * time.Second)
	defer statsTicker.Stop()

	for {
		select {
		case <-ctx.Done():
			return

		case <-statsTicker.C:
			stats := riskMgr.GetStats()
			prom.Equity.Set(stats.Equity)
			prom.DailyPnL.Set(stats.DailyPnL)
			prom.OpenPositions.Set(float64(stats.OpenPositions))

			if stats.DailyPnL < -stats.DailyLossLimit {
				alertMgr.DailyLossLimit(stats.DailyPnL, stats.DailyLossLimit)
			}

		case <-dailyTicker.C:
			stats := riskMgr.GetStats()
			tradeStats := execEngine.GetTradeStats()
			alertMgr.DailyPnLSummary(
				stats.DailyPnL,
				stats.Equity,
				tradeStats.WinRate,
				tradeStats.TotalTrades,
			)
		}
	}
}
