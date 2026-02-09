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
	"github.com/cgn175/quant-bot/internal/mlfilter"
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
		Str("strategy", cfg.Strategy.Type).
		Msg("starting bot")

	// Branch: trend_following strategy bypasses ONNX / ML entirely.
	if cfg.IsTrendFollowing() {
		return runTrendFollowing(cmd, cfg)
	}

	return runMLStrategy(cmd, cfg)
}

// runTrendFollowing implements the Plan D pure trend-following bot loop.
func runTrendFollowing(cmd *cobra.Command, cfg *config.Config) error {
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
	//  Core components (no ONNX, no sentiment, no feature builder)        //
	// ------------------------------------------------------------------ //

	// Candle store — trend following needs EMA-50 + Donchian-20 + ATR warm-up
	storeSize := 120 // generous for all indicators
	sqliteStore, err := data.NewSQLiteStore(data.SQLiteConfig{
		DBPath:     cfg.Storage.CandleDBPath,
		MaxCandles: storeSize,
		MaxDBRows:  cfg.Storage.MaxDBRows,
	})
	if err != nil {
		return fmt.Errorf("create sqlite store: %w", err)
	}
	defer sqliteStore.Close()

	// Load historical candles from SQLite
	if err := sqliteStore.LoadHistory(cfg.Symbols); err != nil {
		log.Warn().Err(err).Msg("failed to load historical candles, starting fresh")
	}

	// Use SQLiteStore as the store (it wraps CandleStore)
	store := sqliteStore

	// Funding rate cache
	var fundingCache *data.FundingCache
	if cfg.Strategy.FundingFilter.Enabled {
		fundingCache = data.NewFundingCache(100)
	}

	// Build TrendStrategy config from config.yaml
	trendCfg := strategy.TrendConfig{
		DonchianPeriod:     cfg.Strategy.DonchianPeriod,
		EMAFast:            cfg.Strategy.EMAFast,
		EMASlow:            cfg.Strategy.EMASlow,
		EMAConfirmBars:     cfg.Strategy.EMAConfirmBars,
		EMATrend:           cfg.Strategy.EMATrend,
		VolumePeriod:       cfg.Strategy.VolumePeriod,
		ATRPeriod:          cfg.Strategy.ATRPeriod,
		ATRStopMult:        cfg.Strategy.ATRStopMult,
		ADXPeriod:          cfg.Strategy.ADXPeriod,
		ADXThreshold:       cfg.Strategy.ADXThreshold,
		VolatilityLow:      cfg.Strategy.VolatilityLow,
		VolatilityHigh:     cfg.Strategy.VolatilityHigh,
		FundingExtreme:     cfg.Strategy.FundingFilter.ExtremeThreshold,
		FundingElevated:    cfg.Strategy.FundingFilter.ElevatedThreshold,
		RiskPerTrade:       cfg.Risk.MaxRiskPerTradePct / 100.0,
		MaxLeverage:        cfg.Risk.MaxLeverage,
		ChandelierLookback: cfg.Strategy.ChandelierLookback,
		DailyLossCapPct:    cfg.Risk.MaxDailyLossPct / 100.0,
		MaxOpenPositions:   cfg.Risk.MaxOpenPositions,
		MaxCorrelatedSame:  2,
		PartialExitEnabled: cfg.Strategy.PartialExits.Enabled,
		FirstTargetR:       cfg.Strategy.PartialExits.FirstTargetR,
		FirstExitPct:       cfg.Strategy.PartialExits.FirstExitPct,
		SecondTargetR:      cfg.Strategy.PartialExits.SecondTargetR,
		SecondExitPct:      cfg.Strategy.PartialExits.SecondExitPct,
	}

	// Prometheus metrics (initialized early so strategy can reference them)
	prom := metrics.NewMetrics()
	prom.MaxOpenPositions.Set(float64(cfg.Risk.MaxOpenPositions))

	var mlClient *mlfilter.Client
	if cfg.Strategy.MLFilter.Enabled {
		mlClient = mlfilter.NewClient(mlfilter.Config{
			Enabled:       true,
			URL:           cfg.Strategy.MLFilter.URL,
			Threshold:     cfg.Strategy.MLFilter.Threshold,
			TimeoutMs:     cfg.Strategy.MLFilter.TimeoutMs,
			FailOpen:      cfg.Strategy.MLFilter.FailOpen,
			FallbackToADX: cfg.Strategy.MLFilter.FallbackToADX,
		})
		trendCfg.MLFilterEnabled = true
		trendCfg.MLThreshold = cfg.Strategy.MLFilter.Threshold
		trendCfg.FallbackToADX = cfg.Strategy.MLFilter.FallbackToADX
		trendCfg.FailOpen = cfg.Strategy.MLFilter.FailOpen
		log.Info().Str("url", cfg.Strategy.MLFilter.URL).Float64("threshold", cfg.Strategy.MLFilter.Threshold).Msg("ML filter enabled")
	}
	var opts []strategy.TrendStrategyOption
	if mlClient != nil {
		opts = append(opts, strategy.WithMLClient(mlClient))
	}
	opts = append(opts, strategy.WithMetrics(prom))
	trendStrat := strategy.NewTrendStrategyWithOpts(trendCfg, opts...)

	// Risk manager (reuse existing)
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

	// Executor
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

	// Telegram alerts
	var alertMgr *alerts.Manager
	if cfg.Alerts.TelegramBotToken != "" && cfg.Alerts.TelegramChatID != 0 {
		var alertErr error
		alertMgr, alertErr = alerts.NewManager(alerts.Config{
			TelegramToken: cfg.Alerts.TelegramBotToken,
			ChatID:        cfg.Alerts.TelegramChatID,
			RateLimitMs:   5000,
			Enabled:       true,
		}, log.Logger)
		if alertErr != nil {
			log.Warn().Err(alertErr).Msg("failed to init telegram alerts, continuing without")
		}
	}
	if alertMgr == nil {
		alertMgr, _ = alerts.NewManager(alerts.Config{Enabled: false}, log.Logger)
	}

	alertMgr.BotStarted(fmt.Sprintf(
		"Strategy: trend_following\nMode: %s\nSymbols: %v\nRisk/trade: %.1f%%\nDaily loss limit: %.1f%%",
		cfg.Mode, cfg.Symbols, cfg.Risk.MaxRiskPerTradePct, cfg.Risk.MaxDailyLossPct,
	))

	// ------------------------------------------------------------------ //
	//  Exchange client                                                    //
	// ------------------------------------------------------------------ //
	exchangeClient := exchange.NewBinanceClient(cfg.Exchange.Testnet)
	defer exchangeClient.Close()

	// ------------------------------------------------------------------ //
	//  Funding rate polling goroutine                                     //
	// ------------------------------------------------------------------ //
	if cfg.Strategy.FundingFilter.Enabled && fundingCache != nil {
		pollInterval := time.Duration(cfg.Strategy.FundingFilter.PollIntervalSec) * time.Second
		if pollInterval < 30*time.Second {
			pollInterval = 5 * time.Minute
		}

		go func() {
			// Initial fetch
			fetchAndUpdateFunding(exchangeClient, cfg.Symbols, fundingCache)

			ticker := time.NewTicker(pollInterval)
			defer ticker.Stop()
			for {
				select {
				case <-ctx.Done():
					return
				case <-ticker.C:
					fetchAndUpdateFunding(exchangeClient, cfg.Symbols, fundingCache)
				}
			}
		}()
		log.Info().Dur("interval", pollInterval).Msg("funding rate polling started")
	}

	// ------------------------------------------------------------------ //
	//  Per-symbol tick channels + processing goroutines                    //
	// ------------------------------------------------------------------ //
	tickChans := make(map[string]chan tickEvent, len(cfg.Symbols))
	var wg sync.WaitGroup

	trendDeps := trendDepsBundle{
		store:        store,
		trendStrat:   trendStrat,
		fundingCache: fundingCache,
		riskMgr:      riskMgr,
		execEngine:   execEngine,
		executor:     executor,
		prom:         prom,
		alertMgr:     alertMgr,
		cfg:          cfg,
	}

	for _, sym := range cfg.Symbols {
		ch := make(chan tickEvent, 64)
		tickChans[sym] = ch

		wg.Add(1)
		go func(symbol string, tickCh <-chan tickEvent) {
			defer wg.Done()
			trendSymbolLoop(ctx, symbol, tickCh, trendDeps)
		}(sym, ch)
	}

	// Subscribe to WebSocket candles
	for _, sym := range cfg.Symbols {
		sym := sym
		ch := tickChans[sym]
		if err := exchangeClient.SubscribeCandles(sym, cfg.BarSize, func(c exchange.Candle) {
			select {
			case ch <- tickEvent{symbol: sym, candle: c}:
			default:
				log.Warn().Str("symbol", sym).Msg("tick channel full, dropping candle")
			}
		}); err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("failed to subscribe")
		}
	}

	// Periodic tasks
	wg.Add(1)
	go func() {
		defer wg.Done()
		runPeriodicTasks(ctx, riskMgr, execEngine, prom, alertMgr)
	}()

	// Set up status provider and start Telegram command listener
	statusProvider := &botStatusProvider{
		cfg:        cfg,
		riskMgr:    riskMgr,
		trendStrat: trendStrat,
		prom:       prom,
		store:      store,
	}
	alertMgr.SetStatusProvider(statusProvider)
	alertMgr.StartCommandListener(ctx)
	defer alertMgr.Stop()

	// Wait for shutdown
	<-ctx.Done()
	log.Info().Msg("shutting down — closing channels and waiting for goroutines")

	for _, ch := range tickChans {
		close(ch)
	}
	wg.Wait()

	closeAllPositions(riskMgr, execEngine, alertMgr)
	alertMgr.BotStopped("graceful shutdown complete")
	log.Info().Msg("shutdown complete")
	return nil
}

// trendDepsBundle bundles dependencies for the trend strategy processing loop.
type trendDepsBundle struct {
	store        data.CandleStoreInterface
	trendStrat   *strategy.TrendStrategy
	fundingCache *data.FundingCache
	riskMgr      *risk.Manager
	execEngine   *execution.Engine
	executor     execution.Executor
	prom         *metrics.Metrics
	alertMgr     *alerts.Manager
	cfg          *config.Config
}

// botStatusProvider implements alerts.StatusProvider for the /status command.
type botStatusProvider struct {
	cfg          *config.Config
	riskMgr      *risk.Manager
	trendStrat   *strategy.TrendStrategy
	prom         *metrics.Metrics
	store        data.CandleStoreInterface
}

// GetStatusInfo returns the current bot status.
func (p *botStatusProvider) GetStatusInfo() alerts.StatusInfo {
	info := alerts.StatusInfo{
		Mode:             p.cfg.Mode,
		CandlesPerSymbol: make(map[string]int64),
		LastCandleTime:   make(map[string]time.Time),
		WebSocketStatus:  "connected",
	}

	// Get equity and positions from risk manager
	if p.riskMgr != nil {
		info.Equity = p.riskMgr.GetEquity()
		positions := p.riskMgr.GetAllPositions()
		info.OpenPositions = len(positions)
	}

	// Get daily PnL from trend strategy
	if p.trendStrat != nil {
		info.DailyPnL = p.trendStrat.GetDailyPnL()
	}

	// Get candle counts and last candle times from store
	if p.store != nil {
		for _, sym := range p.cfg.Symbols {
			info.CandlesPerSymbol[sym] = int64(p.store.Len(sym))
			info.LastCandleTime[sym] = p.store.LastCandleTime(sym)
		}
	}

	return info
}

// trendSymbolLoop is the per-symbol goroutine for the trend-following strategy.
func trendSymbolLoop(ctx context.Context, symbol string, tickCh <-chan tickEvent, d trendDepsBundle) {
	for {
		select {
		case <-ctx.Done():
			return
		case tick, ok := <-tickCh:
			if !ok {
				return
			}
			handleTrendTick(ctx, tick, d)
		}
	}
}

// handleTrendTick processes a single candle for the trend-following strategy.
func handleTrendTick(ctx context.Context, tick tickEvent, d trendDepsBundle) {
	sym := tick.symbol

	// Track candle metrics
	d.prom.CandlesReceived.WithLabelValues(sym).Inc()
	if tick.candle.IsClosed {
		d.prom.CandlesClosed.WithLabelValues(sym).Inc()
	}

	// 1. Store candle
	d.store.Add(tick.candle)
	candles := d.store.GetAll(sym)

	equity := d.riskMgr.GetEquity()

	// 2. Update trailing stops on existing positions
	exitSig := d.trendStrat.UpdateTrailingStop(sym, candles)
	if exitSig != nil {
		closeTrendPosition(sym, exitSig.Price, exitSig.Reason, d)
	}

	// 3. Check partial exits
	if d.trendStrat.HasPosition(sym) {
		currentPrice := tick.candle.Close
		partialSig := d.trendStrat.CheckPartialExit(sym, currentPrice)
		if partialSig != nil {
			handleTrendPartialExit(sym, currentPrice, partialSig, d)
		}
	}

	// 4. Daily loss cap check
	d.trendStrat.CheckDailyLossCap(equity)

	// 5. Generate new entry signals
	sig := d.trendStrat.OnBar(sym, candles, d.fundingCache, equity)
	if sig != nil {
		handleTrendEntry(sym, sig, d)
	}

	// 6. Log tick
	logTrendTick(sym, candles, d)
}

// calculateMarketVolScalar computes the market volatility scalar for position sizing.
// Uses average ATR% of BTC and ETH as a proxy for overall market volatility.
// (Patch 4: Volatility Scalar)
func calculateMarketVolScalar(store data.CandleStoreInterface) float64 {
	btcCandles := store.GetAll("BTCUSDT")
	ethCandles := store.GetAll("ETHUSDT")

	btcATRPct := strategy.CalculateATRPercent(btcCandles, 14)
	ethATRPct := strategy.CalculateATRPercent(ethCandles, 14)

	return strategy.MarketVolatilityScalar(btcATRPct, ethATRPct)
}

// handleTrendEntry opens a new position from a trend signal.
// Uses reservation pattern to prevent TOCTOU race between per-symbol goroutines.
func handleTrendEntry(sym string, sig *strategy.Signal, d trendDepsBundle) {
	// Risk check via risk manager
	if err := d.riskMgr.CanOpenPosition(sym); err != nil {
		log.Debug().Err(err).Str("symbol", sym).Msg("risk manager blocked trend entry")
		return
	}

	// Position sizing: Confidence is repurposed as sizeMultiplier in trend strategy
	sizeMultiplier := sig.Confidence
	if sizeMultiplier <= 0 {
		sizeMultiplier = 1.0
	}

	var side string
	if sig.Type == strategy.SignalLong {
		side = "LONG"
	} else {
		side = "SHORT"
	}

	// Atomically check and reserve the entry slot BEFORE placing order
	ok, reason := d.trendStrat.TryReserveEntry(sym, side)
	if !ok {
		log.Debug().Str("symbol", sym).Str("reason", reason).Msg("reservation blocked trend entry")
		return
	}

	// From here, we MUST either ConfirmReservation or CancelReservation
	equity := d.riskMgr.GetEquity()

	// Calculate market volatility scalar (Patch 4: Volatility Scalar)
	marketVolScalar := calculateMarketVolScalar(d.store)

	size := d.trendStrat.CalculatePositionSize(equity, sig.Price, sig.StopLoss, sizeMultiplier, marketVolScalar)
	if size <= 0 {
		d.trendStrat.CancelReservation(sym)
		return
	}

	log.Debug().
		Str("symbol", sym).
		Float64("market_vol_scalar", marketVolScalar).
		Float64("size_mult", sizeMultiplier).
		Float64("size", size).
		Msg("calculated position size with market vol scalar")

	// Execute order
	start := time.Now()
	order, err := d.execEngine.OpenPosition(sig, size)
	d.prom.OrderExecutionTime.Observe(time.Since(start).Seconds())

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to open trend position")
		d.trendStrat.CancelReservation(sym)
		return
	}

	// Paper trading fill simulation
	if paperExec, ok := d.executor.(*execution.PaperExecutor); ok {
		paperExec.SimulateFill(order, sig.Price)
	}

	if order.FilledPrice <= 0 {
		log.Error().Str("symbol", sym).Msg("trend order filled at zero price, skipping")
		d.trendStrat.CancelReservation(sym)
		return
	}

	riskAmount := equity * (d.cfg.Risk.MaxRiskPerTradePct / 100.0) * sizeMultiplier * marketVolScalar

	// Register in risk manager
	if err := d.riskMgr.OpenPosition(sym, side, order.FilledPrice, size, sig.StopLoss, 0, riskAmount); err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to register trend position")
		d.trendStrat.CancelReservation(sym)
		if cancelErr := d.executor.CancelOrder(sym, order.ID); cancelErr != nil {
			log.Error().Err(cancelErr).Str("symbol", sym).Str("order_id", order.ID).Msg("CRITICAL: order placed but cannot cancel or register")
			d.alertMgr.Error("Orphaned Order", fmt.Errorf("symbol=%s order=%s: placed but could not register or cancel", sym, order.ID))
		}
		return
	}

	// Confirm the reservation (converts pending -> real position)
	d.trendStrat.ConfirmReservation(sym, side, order.FilledPrice, size, sig.StopLoss, sizeMultiplier)

	d.prom.PositionSize.WithLabelValues(sym).Set(size)

	log.Info().
		Str("symbol", sym).
		Str("side", side).
		Float64("price", order.FilledPrice).
		Float64("size", size).
		Float64("stop_loss", sig.StopLoss).
		Float64("risk", riskAmount).
		Float64("size_mult", sizeMultiplier).
		Msg("trend position opened")

	d.alertMgr.TradeOpened(sym, side, order.FilledPrice, size)
}

// closeTrendPosition fully closes a trend position (trailing stop hit).
func closeTrendPosition(sym string, exitPrice float64, reason string, d trendDepsBundle) {
	pos, exists := d.riskMgr.GetPosition(sym)
	if !exists {
		return
	}

	start := time.Now()
	order, err := d.execEngine.ClosePosition(sym, pos.Side, exitPrice, pos.Size, reason, strategy.SignalNone, pos.EntryPrice, pos.EntryTime)
	d.prom.OrderExecutionTime.Observe(time.Since(start).Seconds())

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to close trend position")
		d.alertMgr.Error("Close Position Failed", err)
		return
	}

	if paperExec, ok := d.executor.(*execution.PaperExecutor); ok {
		paperExec.SimulateFill(order, exitPrice)
	}

	netPnL, err := d.riskMgr.ClosePosition(sym, order.FilledPrice)
	if err != nil {
		// Order was already filled on the exchange, but risk manager state update failed.
		// Still remove from TrendStrategy to avoid stale position tracking.
		log.Error().Err(err).Str("symbol", sym).Msg("CRITICAL: risk manager close failed after order fill — syncing trend strategy anyway")
		d.alertMgr.Error("Close Position State Desync", fmt.Errorf("symbol=%s: order filled but ClosePosition failed: %w", sym, err))
		d.trendStrat.RecordPnL(0) // unknown PnL
		d.trendStrat.RemovePosition(sym)
		d.prom.TotalTrades.Inc()
		d.prom.PositionSize.WithLabelValues(sym).Set(0)
		d.prom.UnrealizedPnLPerSymbol.WithLabelValues(sym).Set(0)
		return
	}

	// Record PnL in trend strategy for daily loss cap
	d.trendStrat.RecordPnL(netPnL)
	d.trendStrat.RemovePosition(sym)

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
		Msg("trend position closed")

	d.alertMgr.TradeClosed(sym, pos.Side, pos.EntryPrice, order.FilledPrice, pos.Size, netPnL, reason)
}

// handleTrendPartialExit executes a partial position close at an R-target.
func handleTrendPartialExit(sym string, currentPrice float64, partial *strategy.PartialExitSignal, d trendDepsBundle) {
	pos, exists := d.riskMgr.GetPosition(sym)
	if !exists {
		return
	}

	exitSize := partial.ExitSize
	if exitSize <= 0 || exitSize > pos.Size {
		return
	}

	// Close partial size
	start := time.Now()
	order, err := d.execEngine.ClosePosition(sym, pos.Side, currentPrice, exitSize, partial.Reason, strategy.SignalNone, pos.EntryPrice, pos.EntryTime)
	d.prom.OrderExecutionTime.Observe(time.Since(start).Seconds())

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Str("reason", partial.Reason).Msg("failed to execute partial exit")
		return
	}

	if paperExec, ok := d.executor.(*execution.PaperExecutor); ok {
		paperExec.SimulateFill(order, currentPrice)
	}

	// Partial close — reduce position size atomically
	newStop := 0.0
	if partial.MoveStopBE {
		newStop = partial.NewStop
	}
	netPnL, err := d.riskMgr.ReducePosition(sym, order.FilledPrice, exitSize, newStop)
	if err != nil {
		// CRITICAL: Order was already filled on the exchange, but risk manager
		// state update failed. We must still update TrendStrategy state to avoid
		// desynchronization (strategy thinking it holds more than it does).
		log.Error().Err(err).Str("symbol", sym).Msg("CRITICAL: risk manager partial close failed after order fill — syncing trend strategy anyway")
		d.alertMgr.Error("Partial Exit State Desync", fmt.Errorf("symbol=%s: order filled but ReducePosition failed: %w", sym, err))
		d.trendStrat.ApplyPartialExit(sym, exitSize, partial.MoveStopBE, partial.NewStop, partial.Reason)
		d.trendStrat.RecordPnL(0) // unknown PnL, record 0
		return
	}

	d.trendStrat.RecordPnL(netPnL)

	// Update trend strategy position
	d.trendStrat.ApplyPartialExit(sym, exitSize, partial.MoveStopBE, partial.NewStop, partial.Reason)

	remainingSize := pos.Size - exitSize
	log.Info().
		Str("symbol", sym).
		Str("reason", partial.Reason).
		Float64("exit_size", exitSize).
		Float64("remaining", remainingSize).
		Float64("pnl", netPnL).
		Bool("stop_to_be", partial.MoveStopBE).
		Msg("trend partial exit executed")

	d.alertMgr.PartialExit(sym, pos.Side, pos.EntryPrice, order.FilledPrice, exitSize, remainingSize, netPnL, partial.Reason, partial.MoveStopBE)
}

// logTrendTick emits a structured log line for each processed trend candle.
func logTrendTick(sym string, candles []exchange.Candle, d trendDepsBundle) {
	if len(candles) == 0 {
		return
	}
	last := candles[len(candles)-1]
	stats := d.riskMgr.GetStats()
	tradeStats := d.execEngine.GetTradeStats()

	event := log.Info().
		Str("symbol", sym).
		Float64("close", last.Close).
		Float64("high", last.High).
		Float64("low", last.Low).
		Float64("volume", last.Volume)

	// Add trailing stop info if position exists
	if tPos := d.trendStrat.GetPosition(sym); tPos != nil {
		event = event.
			Str("pos_side", tPos.Side).
			Float64("trailing_stop", tPos.TrailingStop).
			Float64("entry", tPos.EntryPrice).
			Float64("current_r", tPos.CurrentR(last.Close))
	}

	event.
		Float64("equity", stats.Equity).
		Float64("daily_pnl", stats.DailyPnL).
		Int("positions", stats.OpenPositions).
		Int("total_trades", tradeStats.TotalTrades).
		Float64("win_rate", tradeStats.WinRate).
		Msg("tick (trend)")

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

// fetchAndUpdateFunding fetches funding rates via a single bulk API call
// and updates the cache for the configured symbols.
func fetchAndUpdateFunding(client *exchange.BinanceClient, symbols []string, cache *data.FundingCache) {
	allRates, err := client.FetchAllFundingRates()
	if err != nil {
		log.Warn().Err(err).Msg("failed to fetch bulk funding rates")
		return
	}

	// Build a set for O(1) lookup
	wanted := make(map[string]struct{}, len(symbols))
	for _, s := range symbols {
		wanted[s] = struct{}{}
	}

	for sym, info := range allRates {
		if _, ok := wanted[sym]; !ok {
			continue
		}
		cache.Add(sym, data.FundingRate{
			Symbol:    sym,
			Rate:      info.FundingRate,
			Timestamp: info.FundingTime,
		})
		log.Debug().
			Str("symbol", sym).
			Float64("rate", info.FundingRate).
			Msg("funding rate updated")
	}
}

// runMLStrategy contains the original ML-based strategy logic.
func runMLStrategy(cmd *cobra.Command, cfg *config.Config) error {
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

	// ONNX runtime
	if err := model.Initialize(cfg.Model.RuntimeLibPath); err != nil {
		return fmt.Errorf("onnxruntime init: %w", err)
	}
	defer model.Shutdown()

	var predictor *model.Predictor
	var err error
	is4H := cfg.Model.Timeframe == "4h"
	if cfg.Model.Path != "" {
		if _, statErr := os.Stat(cfg.Model.Path); statErr == nil {
			numClasses := cfg.Model.NumClasses
			if numClasses == 0 {
				numClasses = 3 // default to 3-class for backward compatibility
			}
			numFeatures := len(features.FeatureNames())
			if is4H {
				numFeatures = len(features.FeatureNames4H())
			}
			predictor, err = model.NewPredictor(cfg.Model.Path, numFeatures, numClasses)
			if err != nil {
				log.Warn().Err(err).Msg("failed to load model, running without predictions")
			} else {
				defer predictor.Close()
				log.Info().Str("path", cfg.Model.Path).Int("features", numFeatures).Int("classes", numClasses).Str("timeframe", cfg.Model.Timeframe).Msg("model loaded")
			}
		} else {
			log.Warn().Str("path", cfg.Model.Path).Msg("model file not found, running without predictions")
		}
	}

	// ------------------------------------------------------------------ //
	//  4. Core components                                                 //
	// ------------------------------------------------------------------ //
	var storeSize int
	if is4H {
		storeSize = 100 // 4h bars: EMA-50 + margin
	} else {
		storeSize = 500 // 5m bars: multi-timeframe EMAs
	}
	store := data.NewCandleStore(storeSize)
	featureBuilder := features.NewFeatureBuilder()
	var featureBuilder4H *features.Builder4H
	if is4H {
		featureBuilder4H = features.NewFeatureBuilder4H()
	}

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
	if is4H {
		// Wider SL/TP for 4h timeframe
		strategyConfig.StopLossPercent = 2.0
		strategyConfig.TakeProfitPercent = 4.0
		// Disable sentiment filters for 4h (model doesn't use sentiment)
		strategyConfig.SentimentThresholdLong = -10.0
		strategyConfig.SentimentThresholdShort = 10.0
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
				store:            store,
				featureBuilder:   featureBuilder,
				featureBuilder4H: featureBuilder4H,
				sentimentClient:  sentimentClient,
				predictor:        predictor,
				strat:            strat,
				riskMgr:          riskMgr,
				execEngine:       execEngine,
				executor:         executor,
				prom:             prom,
				alertMgr:         alertMgr,
				cfg:              cfg,
				is4H:             is4H,
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
	store            *data.CandleStore
	featureBuilder   *features.Builder
	featureBuilder4H *features.Builder4H // nil when using 5m
	sentimentClient  *sentiment.Client
	predictor        *model.Predictor
	strat            *strategy.Strategy
	riskMgr          *risk.Manager
	execEngine       *execution.Engine
	executor         execution.Executor
	prom             *metrics.Metrics
	alertMgr         *alerts.Manager
	cfg              *config.Config
	is4H             bool
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

	if d.is4H {
		handleTick4H(ctx, sym, candles, d)
	} else {
		handleTick5m(ctx, sym, candles, d)
	}
}

// handleTick5m processes a tick for 5m timeframe (original logic).
func handleTick5m(ctx context.Context, sym string, candles []exchange.Candle, d processSymbolDeps) {
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

// handleTick4H processes a tick for 4h timeframe.
func handleTick4H(ctx context.Context, sym string, candles []exchange.Candle, d processSymbolDeps) {
	// Build 4H features (no sentiment)
	fv4h := d.featureBuilder4H.Build(candles)

	if fv4h == nil {
		log.Debug().
			Str("symbol", sym).
			Int("candles", len(candles)).
			Int("required", d.featureBuilder4H.MinCandles()).
			Msg("waiting for more candles (4h)")
		return
	}

	// Check exit conditions for existing positions
	handleExitCheck4H(sym, fv4h, d)

	// Model prediction
	if d.predictor == nil {
		logTick4H(sym, fv4h, nil, d)
		return
	}

	start := time.Now()
	pred, err := d.predictor.Predict(fv4h.ToArray())
	d.prom.ModelInferenceTime.Observe(time.Since(start).Seconds())

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("prediction failed (4h)")
		return
	}

	// Evaluate strategy signal
	sig := d.strat.Evaluate4H(fv4h, pred)

	// Execute signal
	if sig != nil {
		handleSignal4H(sym, sig, fv4h, d)
	}

	logTick4H(sym, fv4h, pred, d)
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

// handleExitCheck4H checks whether an existing position should be closed (4h).
func handleExitCheck4H(sym string, fv *features.FeatureVector4H, d processSymbolDeps) {
	pos, exists := d.riskMgr.GetPosition(sym)
	if !exists {
		return
	}

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
		Msg("closing position (4h)")

	start := time.Now()
	order, err := d.execEngine.ClosePosition(sym, pos.Side, fv.Close, pos.Size, reason, strategy.SignalNone, pos.EntryPrice, pos.EntryTime)
	d.prom.OrderExecutionTime.Observe(time.Since(start).Seconds())

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to close position")
		d.alertMgr.Error("Close Position Failed", err)
		return
	}

	if paperExec, ok := d.executor.(*execution.PaperExecutor); ok {
		paperExec.SimulateFill(order, fv.Close)
	}

	netPnL, err := d.riskMgr.ClosePosition(sym, order.FilledPrice)
	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("risk manager close failed")
		return
	}

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
		Msg("position closed (4h)")

	d.alertMgr.TradeClosed(sym, pos.Side, pos.EntryPrice, order.FilledPrice, pos.Size, netPnL, reason)
}

// handleSignal4H attempts to open a new position for 4h timeframe.
func handleSignal4H(sym string, sig *strategy.Signal, fv *features.FeatureVector4H, d processSymbolDeps) {
	if err := d.riskMgr.CanOpenPosition(sym); err != nil {
		log.Debug().Err(err).Str("symbol", sym).Msg("cannot open position (4h)")
		return
	}

	sizeMultiplier := 1.0 // no sentiment-based reduction for 4h
	size, err := d.riskMgr.CalculatePositionSize(sym, sig.Price, sig.StopLoss, sizeMultiplier)
	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to calculate position size")
		return
	}
	if size <= 0 {
		return
	}

	start := time.Now()
	order, err := d.execEngine.OpenPosition(sig, size)
	d.prom.OrderExecutionTime.Observe(time.Since(start).Seconds())

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to open position (4h)")
		return
	}

	if paperExec, ok := d.executor.(*execution.PaperExecutor); ok {
		paperExec.SimulateFill(order, fv.Close)
	}

	if order.FilledPrice <= 0 {
		log.Error().Str("symbol", sym).Float64("filled_price", order.FilledPrice).Msg("order filled at zero price, skipping")
		return
	}

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

	d.prom.PositionSize.WithLabelValues(sym).Set(size)

	log.Info().
		Str("symbol", sym).
		Str("side", side).
		Float64("price", order.FilledPrice).
		Float64("size", size).
		Float64("stop_loss", sig.StopLoss).
		Float64("take_profit", sig.TakeProfit).
		Float64("risk", riskAmount).
		Msg("position opened (4h)")

	d.alertMgr.TradeOpened(sym, side, order.FilledPrice, size)
}

// logTick4H emits a structured log line for 4h candles.
func logTick4H(sym string, fv *features.FeatureVector4H, pred *model.Prediction, d processSymbolDeps) {
	stats := d.riskMgr.GetStats()
	tradeStats := d.execEngine.GetTradeStats()

	event := log.Info().
		Str("symbol", sym).
		Float64("close", fv.Close).
		Float64("rsi14", fv.RSI14).
		Float64("ema21", fv.EMA21).
		Float64("atr14", fv.ATR14).
		Float64("roc6", fv.ROC6)

	if pred != nil {
		event = event.
			Float64("p_down", pred.ProbDown).
			Float64("p_up", pred.ProbUp)
	}

	event.
		Float64("equity", stats.Equity).
		Float64("daily_pnl", stats.DailyPnL).
		Int("positions", stats.OpenPositions).
		Int("total_trades", tradeStats.TotalTrades).
		Float64("win_rate", tradeStats.WinRate).
		Msg("tick (4h)")

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
