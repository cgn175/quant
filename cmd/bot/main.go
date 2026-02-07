package main

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"github.com/spf13/cobra"

	"github.com/cgn175/quant-bot/internal/alerts"
	"github.com/cgn175/quant-bot/internal/config"
	"github.com/cgn175/quant-bot/internal/data"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/execution"
	"github.com/cgn175/quant-bot/internal/features"
	"github.com/cgn175/quant-bot/internal/metrics"
	"github.com/cgn175/quant-bot/internal/model"
	"github.com/cgn175/quant-bot/internal/risk"
	"github.com/cgn175/quant-bot/internal/sentiment"
	"github.com/cgn175/quant-bot/internal/strategy"
)

var (
	configPath string
	rootCmd    = &cobra.Command{
		Use:   "bot",
		Short: "Crypto scalping bot",
		RunE:  run,
	}
)

func init() {
	rootCmd.PersistentFlags().StringVarP(&configPath, "config", "c", "config.yaml", "config file path")
}

func main() {
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stderr, TimeFormat: "15:04:05"})
	zerolog.SetGlobalLevel(zerolog.InfoLevel)

	if err := rootCmd.Execute(); err != nil {
		log.Fatal().Err(err).Msg("failed to execute command")
	}
}

// tickEvent is sent from the WebSocket candle handler to the per-symbol
// processing goroutine.  This decouples the WS read loop from the
// (potentially slow) feature-building / model-inference / order-execution
// pipeline so we never block the WebSocket connection.
type tickEvent struct {
	symbol string
	candle exchange.Candle
}

func run(cmd *cobra.Command, args []string) error {
	// ------------------------------------------------------------------ //
	//  1. Load configuration                                              //
	// ------------------------------------------------------------------ //
	cfg, err := config.Load(configPath)
	if err != nil {
		return fmt.Errorf("config load: %w", err)
	}

	log.Info().
		Str("mode", cfg.Mode).
		Strs("symbols", cfg.Symbols).
		Str("exchange", cfg.Exchange.Name).
		Bool("testnet", cfg.Exchange.Testnet).
		Msg("starting bot")

	// ------------------------------------------------------------------ //
	//  2. Root context — cancelled on SIGINT / SIGTERM                     //
	// ------------------------------------------------------------------ //
	ctx, cancel := context.WithCancel(cmd.Context())
	defer cancel()

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

	// ------------------------------------------------------------------ //
	//  3. ONNX runtime                                                    //
	// ------------------------------------------------------------------ //
	if err := model.Initialize(cfg.Model.RuntimeLibPath); err != nil {
		return fmt.Errorf("onnxruntime init: %w", err)
	}
	defer model.Shutdown()

	var predictor *model.Predictor
	if cfg.Model.Path != "" {
		if _, statErr := os.Stat(cfg.Model.Path); statErr == nil {
			predictor, err = model.NewPredictor(cfg.Model.Path, len(features.FeatureNames()))
			if err != nil {
				log.Warn().Err(err).Msg("failed to load model, running without predictions")
			} else {
				defer predictor.Close()
				log.Info().Str("path", cfg.Model.Path).Int("features", len(features.FeatureNames())).Msg("model loaded")
			}
		} else {
			log.Warn().Str("path", cfg.Model.Path).Msg("model file not found, running without predictions")
		}
	}

	// ------------------------------------------------------------------ //
	//  4. Core components                                                 //
	// ------------------------------------------------------------------ //
	store := data.NewCandleStore(500)
	featureBuilder := features.NewFeatureBuilder()

	sentimentClient := sentiment.NewClient(
		cfg.Sentiment.URL,
		time.Duration(cfg.Sentiment.PollIntervalSeconds)*time.Second,
	)
	sentimentClient.Start(cfg.Symbols)
	defer sentimentClient.Stop()

	strategyConfig := strategy.Config{
		ThresholdUp:             cfg.Model.ThresholdUp,
		ThresholdDown:           cfg.Model.ThresholdDown,
		SentimentThresholdLong:  cfg.Sentiment.SentimentThresholdLong,
		SentimentThresholdShort: cfg.Sentiment.SentimentThresholdShort,
		SentimentExtremeLimit:   0.8,
		MinVolumeRatio:          0.5,
		StopLossPercent:         1.0,
		TakeProfitPercent:       2.0,
		AllowLong:               true,
		AllowShort:              cfg.Mode != "live", // disable shorts in live initially
	}
	strat := strategy.NewStrategy(strategyConfig)

	feePercent := cfg.Execution.FeePercent()
	riskConfig := risk.Config{
		InitialEquity:      cfg.Risk.InitialEquity(),
		MaxRiskPerTradePct: cfg.Risk.MaxRiskPerTradePct,
		MaxDailyLossPct:    cfg.Risk.MaxDailyLossPct,
		MaxOpenPositions:   cfg.Risk.MaxOpenPositions,
		MaxLeverage:        cfg.Risk.MaxLeverage,
		FeePercent:         feePercent,
	}
	riskMgr := risk.NewManager(riskConfig)

	var executor execution.Executor
	if cfg.Mode == "live" {
		executor = execution.NewLiveExecutor(cfg.Exchange.APIKey, cfg.Exchange.APISecret, cfg.Exchange.Testnet)
		log.Info().Msg("using live trading executor")
	} else {
		executor = execution.NewPaperExecutor(cfg.Execution.SlippageBP, feePercent)
		log.Info().Msg("using paper trading executor")
	}

	execConfig := execution.Config{
		Mode:           cfg.Mode,
		UseLimitOrders: cfg.Execution.UseLimitOrders,
		SlippageBP:     cfg.Execution.SlippageBP,
		FeePercent:     feePercent,
	}
	execEngine := execution.NewEngine(execConfig, executor)

	// ------------------------------------------------------------------ //
	//  5. Monitoring — Prometheus metrics                                 //
	// ------------------------------------------------------------------ //
	prom := metrics.NewMetrics()
	prom.MaxOpenPositions.Set(float64(cfg.Risk.MaxOpenPositions))

	metricsPort := cfg.Monitoring.PrometheusPort
	if metricsPort == 0 {
		metricsPort = 9090
	}
	metricsMux := http.NewServeMux()
	metricsMux.Handle("/metrics", promhttp.Handler())
	metricsSrv := &http.Server{
		Addr:    fmt.Sprintf(":%d", metricsPort),
		Handler: metricsMux,
	}
	go func() {
		log.Info().Int("port", metricsPort).Msg("prometheus metrics server starting")
		if err := metricsSrv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Error().Err(err).Msg("metrics server error")
		}
	}()
	defer func() {
		shutCtx, shutCancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer shutCancel()
		metricsSrv.Shutdown(shutCtx)
	}()

	// ------------------------------------------------------------------ //
	//  6. Alerts — Telegram                                               //
	// ------------------------------------------------------------------ //
	var alertMgr *alerts.Manager
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
		// Create a disabled manager so nil-checks are unnecessary everywhere.
		alertMgr, _ = alerts.NewManager(alerts.Config{Enabled: false}, log.Logger)
	}

	alertMgr.BotStarted(fmt.Sprintf(
		"Mode: %s\nSymbols: %v\nRisk/trade: %.1f%%\nDaily loss limit: %.1f%%",
		cfg.Mode, cfg.Symbols, cfg.Risk.MaxRiskPerTradePct, cfg.Risk.MaxDailyLossPct,
	))

	// ------------------------------------------------------------------ //
	//  7. Exchange client                                                 //
	// ------------------------------------------------------------------ //
	exchangeClient := exchange.NewBinanceClient(cfg.Exchange.Testnet)
	defer exchangeClient.Close()

	// ------------------------------------------------------------------ //
	//  8. Per-symbol tick channels + processing goroutines                 //
	// ------------------------------------------------------------------ //
	//
	// Architecture:
	//   WS read loop  ──▶  tickCh (buffered)  ──▶  processTick goroutine
	//
	// This means:
	//   • WS handler is non-blocking (just pushes to channel)
	//   • Model inference / order execution can take time without stalling WS
	//   • Each symbol has its own goroutine — no cross-symbol contention

	tickChans := make(map[string]chan tickEvent, len(cfg.Symbols))
	var wg sync.WaitGroup

	for _, sym := range cfg.Symbols {
		ch := make(chan tickEvent, 64)
		tickChans[sym] = ch

		wg.Add(1)
		go func(symbol string, tickCh <-chan tickEvent) {
			defer wg.Done()
			processSymbol(ctx, symbol, tickCh, processSymbolDeps{
				store:           store,
				featureBuilder:  featureBuilder,
				sentimentClient: sentimentClient,
				predictor:       predictor,
				strat:           strat,
				riskMgr:         riskMgr,
				execEngine:      execEngine,
				executor:        executor,
				prom:            prom,
				alertMgr:        alertMgr,
				cfg:             cfg,
			})
		}(sym, ch)
	}

	// ------------------------------------------------------------------ //
	//  9. Subscribe to WebSocket candles — handlers just push to channels  //
	// ------------------------------------------------------------------ //
	for _, sym := range cfg.Symbols {
		sym := sym
		ch := tickChans[sym]
		if err := exchangeClient.SubscribeCandles(sym, cfg.BarSize, func(c exchange.Candle) {
			select {
			case ch <- tickEvent{symbol: sym, candle: c}:
			default:
				// Channel full — drop tick (better than blocking the WS).
				log.Warn().Str("symbol", sym).Msg("tick channel full, dropping candle")
			}
		}); err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("failed to subscribe")
			// Non-fatal: other symbols may still work.
		}
	}

	// ------------------------------------------------------------------ //
	//  10. Periodic tasks (metrics update, daily summary)                  //
	// ------------------------------------------------------------------ //
	wg.Add(1)
	go func() {
		defer wg.Done()
		runPeriodicTasks(ctx, riskMgr, execEngine, prom, alertMgr)
	}()

	// ------------------------------------------------------------------ //
	//  11. Wait for shutdown                                              //
	// ------------------------------------------------------------------ //
	<-ctx.Done()
	log.Info().Msg("shutting down — closing channels and waiting for goroutines")

	// Close tick channels so processSymbol goroutines drain and exit.
	for _, ch := range tickChans {
		close(ch)
	}

	// Wait for all goroutines to finish.
	wg.Wait()

	// Close any remaining open positions gracefully.
	closeAllPositions(riskMgr, execEngine, alertMgr)

	alertMgr.BotStopped("graceful shutdown complete")
	log.Info().Msg("shutdown complete")
	return nil
}

// processSymbolDeps bundles the dependencies for processSymbol to keep the
// function signature manageable.
type processSymbolDeps struct {
	store           *data.CandleStore
	featureBuilder  *features.Builder
	sentimentClient *sentiment.Client
	predictor       *model.Predictor
	strat           *strategy.Strategy
	riskMgr         *risk.Manager
	execEngine      *execution.Engine
	executor        execution.Executor
	prom            *metrics.Metrics
	alertMgr        *alerts.Manager
	cfg             *config.Config
}

// processSymbol is the main per-symbol goroutine.  It reads tick events from
// the channel, builds features, runs model inference, and executes trades.
func processSymbol(ctx context.Context, symbol string, tickCh <-chan tickEvent, d processSymbolDeps) {
	for {
		select {
		case <-ctx.Done():
			return
		case tick, ok := <-tickCh:
			if !ok {
				return // channel closed
			}
			handleTick(ctx, tick, d)
		}
	}
}

func handleTick(ctx context.Context, tick tickEvent, d processSymbolDeps) {
	sym := tick.symbol

	// 1. Store candle
	d.store.Add(tick.candle)
	candles := d.store.GetAll(sym)

	// 2. Build features
	sent := d.sentimentClient.Get(sym)
	fv := d.featureBuilder.Build(candles, sent)

	if fv == nil {
		log.Debug().
			Str("symbol", sym).
			Int("candles", len(candles)).
			Int("required", d.featureBuilder.MinCandles()).
			Msg("waiting for more candles")
		return
	}

	// Update per-symbol sentiment metric
	if sent != nil {
		d.prom.SentimentScore.WithLabelValues(sym).Set(sent.Score1h)
	}

	// 3. Check exit conditions for existing positions
	handleExitCheck(sym, fv, d)

	// 4. Model prediction
	if d.predictor == nil {
		logTick(sym, fv, nil, d)
		return
	}

	start := time.Now()
	pred, err := d.predictor.Predict(fv.ToSlice())
	d.prom.ModelInferenceTime.Observe(time.Since(start).Seconds())

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("prediction failed")
		return
	}

	// 5. Evaluate strategy signal
	sig := d.strat.Evaluate(fv, pred)

	// 6. Execute signal (atomic position open)
	if sig != nil {
		handleSignal(sym, sig, fv, d)
	}

	logTick(sym, fv, pred, d)
}

// handleExitCheck checks whether an existing position should be closed
// (stop-loss / take-profit hit).
func handleExitCheck(sym string, fv *features.FeatureVector, d processSymbolDeps) {
	pos, exists := d.riskMgr.GetPosition(sym)
	if !exists {
		return
	}

	// Update unrealized PnL
	d.riskMgr.UpdatePositionPnL(sym, fv.Close)
	d.prom.UnrealizedPnLPerSymbol.WithLabelValues(sym).Set(pos.UnrealizedPnL)
	d.prom.PositionSize.WithLabelValues(sym).Set(pos.Size)

	shouldClose, reason := d.riskMgr.ShouldClosePosition(sym, fv.Close)
	if !shouldClose {
		return
	}

	log.Info().
		Str("symbol", sym).
		Str("reason", reason).
		Float64("price", fv.Close).
		Float64("unrealized_pnl", pos.UnrealizedPnL).
		Msg("closing position")

	start := time.Now()
	order, err := d.execEngine.ClosePosition(sym, pos.Side, fv.Close, pos.Size, reason, strategy.SignalNone, pos.EntryPrice, pos.EntryTime)
	d.prom.OrderExecutionTime.Observe(time.Since(start).Seconds())

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to close position")
		d.alertMgr.Error("Close Position Failed", err)
		return
	}

	// For paper market orders, simulate the fill
	if paperExec, ok := d.executor.(*execution.PaperExecutor); ok {
		paperExec.SimulateFill(order, fv.Close)
	}

	netPnL, err := d.riskMgr.ClosePosition(sym, order.FilledPrice)
	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("risk manager close failed")
		return
	}

	// Update metrics
	d.prom.TotalTrades.Inc()
	if netPnL > 0 {
		d.prom.WinningTrades.Inc()
	} else if netPnL < 0 {
		d.prom.LosingTrades.Inc()
	}
	d.prom.PositionSize.WithLabelValues(sym).Set(0)
	d.prom.UnrealizedPnLPerSymbol.WithLabelValues(sym).Set(0)

	log.Info().
		Str("symbol", sym).
		Str("reason", reason).
		Float64("pnl", netPnL).
		Float64("equity", d.riskMgr.GetEquity()).
		Msg("position closed")

	d.alertMgr.TradeClosed(sym, pos.Side, pos.EntryPrice, order.FilledPrice, pos.Size, netPnL, reason)
}

// handleSignal attempts to open a new position.  The flow is:
//  1. Risk check (CanOpenPosition)
//  2. Calculate position size
//  3. Execute order
//  4. Simulate fill (paper mode)
//  5. Register position in risk manager
//
// If step 5 fails after step 3 succeeded, we attempt to cancel the order.
func handleSignal(sym string, sig *strategy.Signal, fv *features.FeatureVector, d processSymbolDeps) {
	// 1. Risk check
	if err := d.riskMgr.CanOpenPosition(sym); err != nil {
		log.Debug().Err(err).Str("symbol", sym).Msg("cannot open position")
		return
	}

	// 2. Position size
	sizeMultiplier := d.strat.ShouldReduceSize(fv)
	size, err := d.riskMgr.CalculatePositionSize(sym, sig.Price, sig.StopLoss, sizeMultiplier)
	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to calculate position size")
		return
	}
	if size <= 0 {
		return
	}

	// 3. Execute order
	start := time.Now()
	order, err := d.execEngine.OpenPosition(sig, size)
	d.prom.OrderExecutionTime.Observe(time.Since(start).Seconds())

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to open position")
		return
	}

	// 4. Simulate fill for paper trading market orders
	if paperExec, ok := d.executor.(*execution.PaperExecutor); ok {
		paperExec.SimulateFill(order, fv.Close)
	}

	// If FilledPrice is still zero something went wrong — don't register.
	if order.FilledPrice <= 0 {
		log.Error().Str("symbol", sym).Float64("filled_price", order.FilledPrice).Msg("order filled at zero price, skipping position registration")
		return
	}

	// 5. Register in risk manager (atomic with the order)
	var side string
	if sig.Type == strategy.SignalLong {
		side = "LONG"
	} else {
		side = "SHORT"
	}

	riskAmount := d.riskMgr.GetEquity() * (d.cfg.Risk.MaxRiskPerTradePct / 100.0) * sizeMultiplier
	if err := d.riskMgr.OpenPosition(sym, side, order.FilledPrice, size, sig.StopLoss, sig.TakeProfit, riskAmount); err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to register position — attempting to cancel order")
		if cancelErr := d.executor.CancelOrder(sym, order.ID); cancelErr != nil {
			log.Error().Err(cancelErr).Str("symbol", sym).Str("order_id", order.ID).Msg("CRITICAL: order placed but cannot cancel or register")
			d.alertMgr.Error("Orphaned Order", fmt.Errorf("symbol=%s order=%s: placed but could not register or cancel", sym, order.ID))
		}
		return
	}

	// Update metrics
	d.prom.PositionSize.WithLabelValues(sym).Set(size)

	log.Info().
		Str("symbol", sym).
		Str("side", side).
		Float64("price", order.FilledPrice).
		Float64("size", size).
		Float64("stop_loss", sig.StopLoss).
		Float64("take_profit", sig.TakeProfit).
		Float64("risk", riskAmount).
		Msg("position opened")

	d.alertMgr.TradeOpened(sym, side, order.FilledPrice, size)
}

// logTick emits a structured log line for each processed candle.
func logTick(sym string, fv *features.FeatureVector, pred *model.Prediction, d processSymbolDeps) {
	stats := d.riskMgr.GetStats()
	tradeStats := d.execEngine.GetTradeStats()

	event := log.Info().
		Str("symbol", sym).
		Float64("close", fv.Close).
		Float64("rsi14", fv.RSI14).
		Float64("ema21", fv.EMA21).
		Float64("bb_width", fv.BBWidth).
		Float64("sent_1h", fv.SentimentScore1h)

	if pred != nil {
		event = event.
			Float64("p_down", pred.ProbDown).
			Float64("p_neutral", pred.ProbNeutral).
			Float64("p_up", pred.ProbUp)
	}

	event.
		Float64("equity", stats.Equity).
		Float64("daily_pnl", stats.DailyPnL).
		Int("positions", stats.OpenPositions).
		Int("total_trades", tradeStats.TotalTrades).
		Float64("win_rate", tradeStats.WinRate).
		Msg("tick")

	// Push key values to Prometheus
	d.prom.Equity.Set(stats.Equity)
	d.prom.DailyPnL.Set(stats.DailyPnL)
	d.prom.RealizedPnL.Set(stats.RealizedPnL)
	d.prom.UnrealizedPnL.Set(stats.UnrealizedPnL)
	d.prom.OpenPositions.Set(float64(stats.OpenPositions))
	d.prom.WinRate.Set(tradeStats.WinRate)
	if tradeStats.ProfitFactor > 0 {
		d.prom.ProfitFactor.Set(tradeStats.ProfitFactor)
	}
}

// runPeriodicTasks handles recurring maintenance: metric snapshots and the
// daily Telegram PnL summary.
func runPeriodicTasks(ctx context.Context, riskMgr *risk.Manager, execEngine *execution.Engine, prom *metrics.Metrics, alertMgr *alerts.Manager) {
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

			// Check daily loss limit and alert
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

// closeAllPositions is called during graceful shutdown.  It closes every open
// position at whatever the last known price is.  In paper mode this is fine;
// in live mode the exchange handles the actual fill.
func closeAllPositions(riskMgr *risk.Manager, execEngine *execution.Engine, alertMgr *alerts.Manager) {
	positions := riskMgr.GetAllPositions()
	if len(positions) == 0 {
		return
	}

	log.Info().Int("count", len(positions)).Msg("closing all open positions on shutdown")

	for sym, pos := range positions {
		// Use the entry price as a fallback — in production we would query
		// the exchange for the current market price.
		exitPrice := pos.EntryPrice
		if pos.UnrealizedPnL != 0 {
			// Derive approximate current price from unrealized PnL.
			if pos.Side == "LONG" {
				exitPrice = pos.EntryPrice + pos.UnrealizedPnL/pos.Size
			} else {
				exitPrice = pos.EntryPrice - pos.UnrealizedPnL/pos.Size
			}
		}

		_, err := execEngine.ClosePosition(sym, pos.Side, exitPrice, pos.Size, "shutdown", strategy.SignalNone, pos.EntryPrice, pos.EntryTime)
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
