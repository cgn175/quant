package bot

import (
	"context"
	"fmt"
	"net/http"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/rs/zerolog/log"
	"github.com/spf13/cobra"

	"github.com/cgn175/quant-bot/internal/alerts"
	"github.com/cgn175/quant-bot/internal/config"
	"github.com/cgn175/quant-bot/internal/data"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/execution"
	"github.com/cgn175/quant-bot/internal/metrics"
	"github.com/cgn175/quant-bot/internal/mlfilter"
	"github.com/cgn175/quant-bot/internal/risk"
	"github.com/cgn175/quant-bot/internal/sentiment"
	"github.com/cgn175/quant-bot/internal/strategy"
)

// TrendDeps bundles dependencies for the trend strategy processing loop.
type TrendDeps struct {
	Store        data.CandleStoreInterface
	TrendStrat   *strategy.TrendStrategy
	FundingCache *data.FundingCache
	RiskMgr      *risk.Manager
	ExecEngine   *execution.Engine
	Executor     execution.Executor
	Prom         *metrics.Metrics
	AlertMgr     *alerts.Manager
	Cfg          *config.Config
}

// BotStatusProvider implements alerts.StatusProvider for the /status command.
type BotStatusProvider struct {
	Cfg        *config.Config
	RiskMgr    *risk.Manager
	TrendStrat *strategy.TrendStrategy
	Prom       *metrics.Metrics
	Store      data.CandleStoreInterface
}

// GetStatusInfo returns the current bot status.
func (p *BotStatusProvider) GetStatusInfo() alerts.StatusInfo {
	info := alerts.StatusInfo{
		Mode:             p.Cfg.Mode,
		CandlesPerSymbol: make(map[string]int64),
		LastCandleTime:   make(map[string]time.Time),
		WebSocketStatus:  "connected",
	}

	if p.RiskMgr != nil {
		info.Equity = p.RiskMgr.GetEquity()
		positions := p.RiskMgr.GetAllPositions()
		info.OpenPositions = len(positions)
	}

	if p.TrendStrat != nil {
		info.DailyPnL = p.TrendStrat.GetDailyPnL()
	}

	if p.Store != nil {
		for _, sym := range p.Cfg.Symbols {
			info.CandlesPerSymbol[sym] = int64(p.Store.Len(sym))
			info.LastCandleTime[sym] = p.Store.LastCandleTime(sym)
		}
	}

	return info
}

// RunTrendFollowing implements the Plan D pure trend-following bot loop.
func RunTrendFollowing(cmd *cobra.Command, cfg *config.Config) error {
	ctx, cancel := SetupContext(cmd)
	defer cancel()

	log.Info().
		Str("mode", cfg.Mode).
		Strs("symbols", cfg.Symbols).
		Str("exchange", cfg.Exchange.Name).
		Bool("testnet", cfg.Exchange.Testnet).
		Str("strategy", cfg.Strategy.Type).
		Msg("starting trend following bot")

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

	// Funding rate cache
	var fundingCache *data.FundingCache
	if cfg.Strategy.FundingFilter.Enabled {
		fundingCache = data.NewFundingCache(100)
	}

	// Sentiment Client (init early for strategy injection)
	sentimentClient := SetupSentimentClient(cfg)

	// Build TrendStrategy config from config.yaml
	trendCfg := buildTrendConfig(cfg)

	// Prometheus metrics (initialized early so strategy can reference them)
	prom := SetupMetrics(cfg)

	// ML Filter / Regime Filter / Dynamic Stop clients
	mlClient := setupMLClients(cfg, &trendCfg)

	var opts []strategy.TrendStrategyOption
	if mlClient != nil {
		opts = append(opts, strategy.WithMLClient(mlClient))
	}
	if sentimentClient != nil {
		opts = append(opts, strategy.WithSentimentClient(sentimentClient))
	}
	opts = append(opts, strategy.WithMetrics(prom))
	trendStrat := strategy.NewTrendStrategyWithOpts(trendCfg, opts...)

	// Risk manager, executor, execution engine
	riskMgr := SetupRiskManager(cfg)
	executor := SetupExecutor(cfg)
	execEngine := SetupExecutionEngine(cfg, executor)

	// Metrics server
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
	alertMgr := SetupAlertManager(cfg)
	SendStartupAlert(alertMgr, cfg)

	// Sentiment scheduler (optional)
	var sentimentScheduler *sentiment.Scheduler
	if cfg.Sentiment.Enabled && sentimentClient != nil {
		defer sentimentClient.Stop()

		sentimentScheduler = sentiment.NewScheduler(
			sentimentClient,
			alertMgr,
			cfg.Sentiment.ScheduleTimes,
			cfg.Symbols,
		)
		sentimentScheduler.Start()
		defer sentimentScheduler.Stop()

		sentimentWrapper := sentiment.NewSentimentDataWrapper(sentimentClient, cfg.Symbols)
		alertMgr.SetSentimentProvider(sentimentWrapper)

		log.Info().
			Strs("times", cfg.Sentiment.ScheduleTimes).
			Str("url", cfg.Sentiment.URL).
			Msg("sentiment scheduler enabled")
	}

	// Exchange client
	exchangeClient := SetupExchangeClient(cfg)
	defer exchangeClient.Close()

	// Funding rate polling goroutine
	if cfg.Strategy.FundingFilter.Enabled && fundingCache != nil {
		startFundingPolling(ctx, exchangeClient, cfg.Symbols, fundingCache, cfg.Strategy.FundingFilter.PollIntervalSec)
	}

	// Per-symbol tick channels + processing goroutines
	tickChans := CreateTickChannels(cfg.Symbols)
	var wg sync.WaitGroup

	trendDeps := TrendDeps{
		Store:        sqliteStore,
		TrendStrat:   trendStrat,
		FundingCache: fundingCache,
		RiskMgr:      riskMgr,
		ExecEngine:   execEngine,
		Executor:     executor,
		Prom:         prom,
		AlertMgr:     alertMgr,
		Cfg:          cfg,
	}

	for _, sym := range cfg.Symbols {
		ch := tickChans[sym]
		wg.Add(1)
		go func(symbol string, tickCh <-chan tickEvent) {
			defer wg.Done()
			trendSymbolLoop(ctx, symbol, tickCh, trendDeps)
		}(sym, ch)
	}

	// Subscribe to market data via WS hub
	SubscribeToMarketData(exchangeClient, cfg.Symbols, cfg.BarSize, tickChans)

	// Periodic tasks
	wg.Add(1)
	go func() {
		defer wg.Done()
		RunPeriodicTasks(ctx, riskMgr, execEngine, prom, alertMgr)
	}()

	// Set up status provider and start Telegram command listener
	statusProvider := &BotStatusProvider{
		Cfg:        cfg,
		RiskMgr:    riskMgr,
		TrendStrat: trendStrat,
		Prom:       prom,
		Store:      sqliteStore,
	}
	alertMgr.SetStatusProvider(statusProvider)
	alertMgr.SetStatsCompareFunc(func() (string, error) {
		return CompareStrategiesStats(execEngine, cfg.Strategy.Type)
	})

	// Only start command listener if explicitly enabled
	if cfg.Alerts.EnableTelegramCommands {
		alertMgr.StartCommandListener(ctx)
		defer alertMgr.Stop()
		log.Info().Msg("telegram command listener enabled")
	} else {
		log.Info().Msg("telegram command listener disabled - only alerts will be sent")
	}

	// Wait for shutdown
	<-ctx.Done()
	log.Info().Msg("shutting down — closing channels and waiting for goroutines")

	for _, ch := range tickChans {
		close(ch)
	}
	wg.Wait()

	CloseAllPositions(riskMgr, execEngine, alertMgr)
	alertMgr.BotStopped("graceful shutdown complete")
	log.Info().Msg("shutdown complete")
	return nil
}

// buildTrendConfig builds the TrendStrategy config from config.yaml.
func buildTrendConfig(cfg *config.Config) strategy.TrendConfig {
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
		// OI filter
		OIFilterEnabled:      cfg.Strategy.OIFilter.Enabled,
		OIFilterZScoreThresh: cfg.Strategy.OIFilter.ZScoreThresh,
		OIFilterLookback:     cfg.Strategy.OIFilter.Lookback,
		// Time stop
		TimeStopBars: cfg.Strategy.TimeStopBars,
		TimeStopMinR: cfg.Strategy.TimeStopMinR,
	}
	return trendCfg
}

// setupMLClients sets up ML filter, regime filter, and dynamic stop clients.
func setupMLClients(cfg *config.Config, trendCfg *strategy.TrendConfig) *mlfilter.Client {
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

	// Wire Regime Classifier (Traffic Light) config
	if cfg.Strategy.RegimeFilter.Enabled {
		trendCfg.RegimeFilterEnabled = true
		trendCfg.RegimeThreshold = cfg.Strategy.RegimeFilter.Threshold
		trendCfg.RegimeFallbackToADX = cfg.Strategy.RegimeFilter.FallbackToADX
		trendCfg.RegimeFailOpen = cfg.Strategy.RegimeFilter.FailOpen
		log.Info().Float64("threshold", cfg.Strategy.RegimeFilter.Threshold).Msg("Regime filter (Traffic Light) enabled")

		trendCfg.RegimeSymbolVersions = cfg.Strategy.RegimeFilter.SymbolVersions
		if len(trendCfg.RegimeSymbolVersions) > 0 {
			log.Info().Interface("versions", trendCfg.RegimeSymbolVersions).Msg("Per-symbol regime model versions")
		}

		if cfg.Strategy.RegimeFilter.Ensemble.Enabled {
			trendCfg.EnsembleEnabled = true
			trendCfg.EnsembleMaxStopPct = cfg.Strategy.RegimeFilter.Ensemble.MaxStopPct
			trendCfg.EnsembleSymbols = make(map[string]bool)
			for _, s := range cfg.Strategy.RegimeFilter.Ensemble.Symbols {
				trendCfg.EnsembleSymbols[s] = true
			}
			log.Info().Float64("max_stop_pct", trendCfg.EnsembleMaxStopPct).Strs("symbols", cfg.Strategy.RegimeFilter.Ensemble.Symbols).Msg("Ensemble filter (regime+vol) enabled")
		}

		if len(cfg.Strategy.RegimeFilter.DirectionalSymbols) > 0 {
			trendCfg.DirectionalRegimeEnabled = true
			trendCfg.DirectionalRegimeSymbols = make(map[string]bool)
			for _, s := range cfg.Strategy.RegimeFilter.DirectionalSymbols {
				trendCfg.DirectionalRegimeSymbols[s] = true
			}
			log.Info().Strs("symbols", cfg.Strategy.RegimeFilter.DirectionalSymbols).Msg("Directional regime models enabled")
		}

		if mlClient == nil {
			mlClient = mlfilter.NewClient(mlfilter.Config{
				Enabled:       true,
				URL:           cfg.Strategy.RegimeFilter.URL,
				TimeoutMs:     cfg.Strategy.RegimeFilter.TimeoutMs,
				FailOpen:      cfg.Strategy.RegimeFilter.FailOpen,
				FallbackToADX: cfg.Strategy.RegimeFilter.FallbackToADX,
			})
		}
	}

	// Wire Dynamic Stop-Loss (Volatility Reader) config
	if cfg.Strategy.DynamicStop.Enabled {
		trendCfg.DynamicStopEnabled = true
		trendCfg.DynamicStopK = cfg.Strategy.DynamicStop.K
		trendCfg.DynamicStopMinPct = cfg.Strategy.DynamicStop.MinStopPct
		trendCfg.DynamicStopMaxPct = cfg.Strategy.DynamicStop.MaxStopPct
		log.Info().Float64("k", cfg.Strategy.DynamicStop.K).Float64("min", cfg.Strategy.DynamicStop.MinStopPct).Float64("max", cfg.Strategy.DynamicStop.MaxStopPct).Msg("Dynamic stop-loss (Volatility Reader) enabled")

		if mlClient == nil {
			mlClient = mlfilter.NewClient(mlfilter.Config{
				Enabled:   true,
				URL:       cfg.Strategy.DynamicStop.URL,
				TimeoutMs: cfg.Strategy.DynamicStop.TimeoutMs,
				FailOpen:  cfg.Strategy.DynamicStop.FailOpen,
			})
		}
	}

	return mlClient
}

// startFundingPolling starts the funding rate polling goroutine.
func startFundingPolling(ctx context.Context, client exchange.Client, symbols []string, cache *data.FundingCache, pollIntervalSec int) {
	pollInterval := time.Duration(pollIntervalSec) * time.Second
	if pollInterval < 30*time.Second {
		pollInterval = 5 * time.Minute
	}

	go func() {
		fetchAndUpdateFunding(client, symbols, cache)

		ticker := time.NewTicker(pollInterval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				fetchAndUpdateFunding(client, symbols, cache)
			}
		}
	}()
	log.Info().Dur("interval", pollInterval).Msg("funding rate polling started")
}

// fetchAndUpdateFunding fetches funding rates via a single bulk API call
// and updates the cache for the configured symbols.
func fetchAndUpdateFunding(client exchange.Client, symbols []string, cache *data.FundingCache) {
	allRates, err := client.FetchAllFundingRates()
	if err != nil {
		log.Warn().Err(err).Msg("failed to fetch bulk funding rates")
		return
	}

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

// trendSymbolLoop is the per-symbol goroutine for the trend-following strategy.
func trendSymbolLoop(ctx context.Context, symbol string, tickCh <-chan tickEvent, d TrendDeps) {
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
func handleTrendTick(ctx context.Context, tick tickEvent, d TrendDeps) {
	sym := tick.symbol

	// Track candle metrics
	d.Prom.CandlesReceived.WithLabelValues(sym).Inc()
	if tick.candle.IsClosed {
		d.Prom.CandlesClosed.WithLabelValues(sym).Inc()
	}

	// 1. Store candle
	d.Store.Add(tick.candle)
	candles := d.Store.GetAll(sym)

	equity := d.RiskMgr.GetEquity()

	// 2. Update trailing stops on existing positions
	exitSig := d.TrendStrat.UpdateTrailingStop(sym, candles)
	if exitSig != nil {
		closeTrendPosition(sym, exitSig.Price, exitSig.Reason, d)
	}

	// 3. Check partial exits
	if d.TrendStrat.HasPosition(sym) {
		currentPrice := tick.candle.Close
		partialSig := d.TrendStrat.CheckPartialExit(sym, currentPrice)
		if partialSig != nil {
			handleTrendPartialExit(sym, currentPrice, partialSig, d)
		}
	}

	// 4. Daily loss cap check
	d.TrendStrat.CheckDailyLossCap(equity)

	// 5. Generate new entry signals
	sig := d.TrendStrat.OnBar(sym, candles, d.FundingCache, equity)
	if sig != nil {
		handleTrendEntry(sym, sig, d)
	}

	// 6. Log tick
	//logTrendTick(sym, candles, d)
}

// calculateMarketVolScalar computes the market volatility scalar for position sizing.
func calculateMarketVolScalar(store data.CandleStoreInterface) float64 {
	btcCandles := store.GetAll("BTCUSDT")
	ethCandles := store.GetAll("ETHUSDT")

	btcATRPct := strategy.CalculateATRPercent(btcCandles, 14)
	ethATRPct := strategy.CalculateATRPercent(ethCandles, 14)

	return strategy.MarketVolatilityScalar(btcATRPct, ethATRPct)
}

// handleTrendEntry opens a new position from a trend signal.
func handleTrendEntry(sym string, sig *strategy.Signal, d TrendDeps) {
	if err := d.RiskMgr.CanOpenPosition(sym); err != nil {
		log.Debug().Err(err).Str("symbol", sym).Msg("risk manager blocked trend entry")
		return
	}

	sizeMultiplier := sig.SizeMultiplier
	if sizeMultiplier <= 0 {
		sizeMultiplier = 1.0
	}

	var side string
	if sig.Type == strategy.SignalLong {
		side = "LONG"
	} else {
		side = "SHORT"
	}

	ok, reason := d.TrendStrat.TryReserveEntry(sym, side)
	if !ok {
		log.Debug().Str("symbol", sym).Str("reason", reason).Msg("reservation blocked trend entry")
		return
	}

	equity := d.RiskMgr.GetEquity()
	marketVolScalar := calculateMarketVolScalar(d.Store)

	size := d.TrendStrat.CalculatePositionSize(equity, sig.Price, sig.StopLoss, sizeMultiplier, marketVolScalar)
	if size <= 0 {
		d.TrendStrat.CancelReservation(sym)
		return
	}

	log.Debug().
		Str("symbol", sym).
		Float64("market_vol_scalar", marketVolScalar).
		Float64("size_mult", sizeMultiplier).
		Float64("size", size).
		Msg("calculated position size with market vol scalar")

	start := time.Now()
	order, err := d.ExecEngine.OpenPosition(sig, size)
	d.Prom.OrderExecutionTime.Observe(time.Since(start).Seconds())

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to open trend position")
		d.TrendStrat.CancelReservation(sym)
		return
	}

	if paperExec, ok := d.Executor.(*execution.PaperExecutor); ok {
		paperExec.SimulateFill(order, sig.Price)
	}

	if order.FilledPrice <= 0 {
		log.Error().Str("symbol", sym).Msg("trend order filled at zero price, skipping")
		d.TrendStrat.CancelReservation(sym)
		return
	}

	riskAmount := equity * (d.Cfg.Risk.MaxRiskPerTradePct / 100.0) * sizeMultiplier * marketVolScalar

	if err := d.RiskMgr.OpenPosition(sym, side, order.FilledPrice, size, sig.StopLoss, 0, riskAmount); err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to register trend position")
		d.TrendStrat.CancelReservation(sym)
		if cancelErr := d.Executor.CancelOrder(sym, order.ID); cancelErr != nil {
			log.Error().Err(cancelErr).Str("symbol", sym).Str("order_id", order.ID).Msg("CRITICAL: order placed but cannot cancel or register")
			d.AlertMgr.Error("Orphaned Order", fmt.Errorf("symbol=%s order=%s: placed but could not register or cancel", sym, order.ID))
		}
		return
	}

	d.TrendStrat.ConfirmReservation(sym, side, order.FilledPrice, size, sig.StopLoss, sizeMultiplier)
	d.Prom.PositionSize.WithLabelValues(sym).Set(size)

	log.Info().
		Str("symbol", sym).
		Str("side", side).
		Float64("price", order.FilledPrice).
		Float64("size", size).
		Float64("stop_loss", sig.StopLoss).
		Float64("risk", riskAmount).
		Float64("size_mult", sizeMultiplier).
		Msg("trend position opened")

	d.AlertMgr.TradeOpened(sym, side, order.FilledPrice, size)
}

// closeTrendPosition fully closes a trend position (trailing stop hit).
func closeTrendPosition(sym string, exitPrice float64, reason string, d TrendDeps) {
	pos, exists := d.RiskMgr.GetPosition(sym)
	if !exists {
		return
	}

	start := time.Now()
	order, err := d.ExecEngine.ClosePosition(sym, pos.Side, exitPrice, pos.Size, reason, strategy.SignalNone, "trend_following", pos.EntryPrice, pos.EntryTime)
	d.Prom.OrderExecutionTime.Observe(time.Since(start).Seconds())

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to close trend position")
		d.AlertMgr.Error("Close Position Failed", err)
		return
	}

	if paperExec, ok := d.Executor.(*execution.PaperExecutor); ok {
		paperExec.SimulateFill(order, exitPrice)
	}

	netPnL, err := d.RiskMgr.ClosePosition(sym, order.FilledPrice)
	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("CRITICAL: risk manager close failed after order fill — syncing trend strategy anyway")
		d.AlertMgr.Error("Close Position State Desync", fmt.Errorf("symbol=%s: order filled but ClosePosition failed: %w", sym, err))
		d.TrendStrat.RecordPnL(0)
		d.TrendStrat.RemovePosition(sym)
		d.Prom.PositionSize.WithLabelValues(sym).Set(0)
		d.Prom.UnrealizedPnLPerSymbol.WithLabelValues(sym).Set(0)
		return
	}

	d.TrendStrat.RecordPnL(netPnL)
	d.TrendStrat.RemovePosition(sym)
	d.Prom.PositionSize.WithLabelValues(sym).Set(0)
	d.Prom.UnrealizedPnLPerSymbol.WithLabelValues(sym).Set(0)

	log.Info().
		Str("symbol", sym).
		Str("reason", reason).
		Float64("pnl", netPnL).
		Float64("equity", d.RiskMgr.GetEquity()).
		Msg("trend position closed")

	d.AlertMgr.TradeClosed(sym, pos.Side, pos.EntryPrice, order.FilledPrice, pos.Size, netPnL, reason)
}

// handleTrendPartialExit executes a partial position close at an R-target.
func handleTrendPartialExit(sym string, currentPrice float64, partial *strategy.PartialExitSignal, d TrendDeps) {
	pos, exists := d.RiskMgr.GetPosition(sym)
	if !exists {
		return
	}

	exitSize := partial.ExitSize
	if exitSize <= 0 || exitSize > pos.Size {
		return
	}

	start := time.Now()
	order, err := d.ExecEngine.ClosePosition(sym, pos.Side, currentPrice, exitSize, partial.Reason, strategy.SignalNone, "trend_following", pos.EntryPrice, pos.EntryTime)
	d.Prom.OrderExecutionTime.Observe(time.Since(start).Seconds())

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Str("reason", partial.Reason).Msg("failed to execute partial exit")
		return
	}

	if paperExec, ok := d.Executor.(*execution.PaperExecutor); ok {
		paperExec.SimulateFill(order, currentPrice)
	}

	newStop := 0.0
	if partial.MoveStopBE {
		newStop = partial.NewStop
	}
	netPnL, err := d.RiskMgr.ReducePosition(sym, order.FilledPrice, exitSize, newStop)
	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("CRITICAL: risk manager partial close failed after order fill — syncing trend strategy anyway")
		d.AlertMgr.Error("Partial Exit State Desync", fmt.Errorf("symbol=%s: order filled but ReducePosition failed: %w", sym, err))
		d.TrendStrat.ApplyPartialExit(sym, exitSize, partial.MoveStopBE, partial.NewStop, partial.Reason)
		d.TrendStrat.RecordPnL(0)
		return
	}

	d.TrendStrat.RecordPnL(netPnL)
	d.TrendStrat.ApplyPartialExit(sym, exitSize, partial.MoveStopBE, partial.NewStop, partial.Reason)

	remainingSize := pos.Size - exitSize
	log.Info().
		Str("symbol", sym).
		Str("reason", partial.Reason).
		Float64("exit_size", exitSize).
		Float64("remaining", remainingSize).
		Float64("pnl", netPnL).
		Bool("stop_to_be", partial.MoveStopBE).
		Msg("trend partial exit executed")

	d.AlertMgr.PartialExit(sym, pos.Side, pos.EntryPrice, order.FilledPrice, exitSize, remainingSize, netPnL, partial.Reason, partial.MoveStopBE)
}

// logTrendTick emits a structured log line for each processed trend candle.
func logTrendTick(sym string, candles []exchange.Candle, d TrendDeps) {
	if len(candles) == 0 {
		return
	}
	last := candles[len(candles)-1]
	stats := d.RiskMgr.GetStats()
	tradeStats := d.ExecEngine.GetTradeStats()

	event := log.Info().
		Str("symbol", sym).
		Float64("close", last.Close).
		Float64("high", last.High).
		Float64("low", last.Low).
		Float64("volume", last.Volume)

	if tPos := d.TrendStrat.GetPosition(sym); tPos != nil {
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

	d.Prom.Equity.Set(stats.Equity)
	d.Prom.DailyPnL.Set(stats.DailyPnL)
	d.Prom.RealizedPnL.Set(stats.RealizedPnL)
	d.Prom.UnrealizedPnL.Set(stats.UnrealizedPnL)
	d.Prom.OpenPositions.Set(float64(stats.OpenPositions))
	d.Prom.WinRate.Set(tradeStats.WinRate)
	if tradeStats.ProfitFactor > 0 {
		d.Prom.ProfitFactor.Set(tradeStats.ProfitFactor)
	}
}
