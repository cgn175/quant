package bot

import (
	"context"
	"fmt"
	"net/http"
	"os"
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
	"github.com/cgn175/quant-bot/internal/features"
	"github.com/cgn175/quant-bot/internal/metrics"
	"github.com/cgn175/quant-bot/internal/model"
	"github.com/cgn175/quant-bot/internal/risk"
	"github.com/cgn175/quant-bot/internal/sentiment"
	"github.com/cgn175/quant-bot/internal/strategy"
)

// ProcessSymbolDeps bundles the dependencies for processSymbol.
type ProcessSymbolDeps struct {
	Store            *data.CandleStore
	FeatureBuilder   *features.Builder
	FeatureBuilder4H *features.Builder4H // nil when using 5m
	SentimentClient  *sentiment.Client
	Predictor        *model.Predictor
	Strat            *strategy.Strategy
	RiskMgr          *risk.Manager
	ExecEngine       *execution.Engine
	Executor         execution.Executor
	Prom             *metrics.Metrics
	AlertMgr         *alerts.Manager
	Cfg              *config.Config
	Is4H             bool
}

// RunMLStrategy contains the original ML-based strategy logic.
func RunMLStrategy(cmd *cobra.Command, cfg *config.Config) error {
	ctx, cancel := SetupContext(cmd)
	defer cancel()

	log.Info().
		Str("mode", cfg.Mode).
		Strs("symbols", cfg.Symbols).
		Str("exchange", cfg.Exchange.Name).
		Bool("testnet", cfg.Exchange.Testnet).
		Str("strategy", cfg.Strategy.Type).
		Msg("starting ML strategy bot")

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
				numClasses = 3
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

	// Core components
	var storeSize int
	if is4H {
		storeSize = 100
	} else {
		storeSize = 500
	}
	store := data.NewCandleStore(storeSize)
	featureBuilder := features.NewFeatureBuilder()
	var featureBuilder4H *features.Builder4H
	if is4H {
		featureBuilder4H = features.NewFeatureBuilder4H()
	}

	sentimentClient := SetupSentimentClient(cfg)
	defer sentimentClient.Stop()

	strategyConfig := buildMLStrategyConfig(cfg, is4H)
	strat := strategy.NewStrategy(strategyConfig)

	riskMgr := SetupRiskManager(cfg)
	executor := SetupExecutor(cfg)
	execEngine := SetupExecutionEngine(cfg, executor)

	// Prometheus metrics
	prom := SetupMetrics(cfg)

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

	// Exchange client
	exchangeClient := SetupExchangeClient(cfg)
	defer exchangeClient.Close()

	// Per-symbol tick channels + processing goroutines
	tickChans := CreateTickChannels(cfg.Symbols)
	var wg sync.WaitGroup

	for _, sym := range cfg.Symbols {
		ch := tickChans[sym]
		wg.Add(1)
		go func(symbol string, tickCh <-chan tickEvent) {
			defer wg.Done()
			processSymbol(ctx, symbol, tickCh, ProcessSymbolDeps{
				Store:            store,
				FeatureBuilder:   featureBuilder,
				FeatureBuilder4H: featureBuilder4H,
				SentimentClient:  sentimentClient,
				Predictor:        predictor,
				Strat:            strat,
				RiskMgr:          riskMgr,
				ExecEngine:       execEngine,
				Executor:         executor,
				Prom:             prom,
				AlertMgr:         alertMgr,
				Cfg:              cfg,
				Is4H:             is4H,
			})
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

	// Wait for shutdown
	<-ctx.Done()
	log.Info().Msg("shutting down — closing channels and waiting for goroutines")

	for _, ch := range tickChans {
		close(ch)
	}
	wg.Wait()

	CloseAllPositions(riskMgr, execEngine, alertMgr)
	saveStats(execEngine, "trend_following")

	alertMgr.BotStopped("graceful shutdown complete")
	log.Info().Msg("shutdown complete")
	return nil
}

// buildMLStrategyConfig builds the strategy config for ML strategy.
func buildMLStrategyConfig(cfg *config.Config, is4H bool) strategy.Config {
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
		AllowShort:              cfg.Mode != "live",
	}
	if is4H {
		strategyConfig.StopLossPercent = 2.0
		strategyConfig.TakeProfitPercent = 4.0
		strategyConfig.SentimentThresholdLong = -10.0
		strategyConfig.SentimentThresholdShort = 10.0
	}
	return strategyConfig
}

// processSymbol is the main per-symbol goroutine.
func processSymbol(ctx context.Context, symbol string, tickCh <-chan tickEvent, d ProcessSymbolDeps) {
	for {
		select {
		case <-ctx.Done():
			return
		case tick, ok := <-tickCh:
			if !ok {
				return
			}
			handleTick(ctx, tick, d)
		}
	}
}

func handleTick(ctx context.Context, tick tickEvent, d ProcessSymbolDeps) {
	sym := tick.symbol

	d.Store.Add(tick.candle)
	candles := d.Store.GetAll(sym)

	if d.Is4H {
		handleTick4H(ctx, sym, candles, d)
	} else {
		handleTick5m(ctx, sym, candles, d)
	}
}

// handleTick5m processes a tick for 5m timeframe.
func handleTick5m(ctx context.Context, sym string, candles []exchange.Candle, d ProcessSymbolDeps) {
	sent := d.SentimentClient.Get(sym)
	fv := d.FeatureBuilder.Build(candles, sent)

	if fv == nil {
		log.Debug().
			Str("symbol", sym).
			Int("candles", len(candles)).
			Int("required", d.FeatureBuilder.MinCandles()).
			Msg("waiting for more candles")
		return
	}

	if sent != nil {
		d.Prom.SentimentScore.WithLabelValues(sym).Set(sent.Score1h)
	}

	handleExitCheck(sym, fv, d)

	if d.Predictor == nil {
		logTick(sym, fv, nil, d)
		return
	}

	start := time.Now()
	pred, err := d.Predictor.Predict(fv.ToSlice())
	d.Prom.ModelInferenceTime.Observe(time.Since(start).Seconds())

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("prediction failed")
		return
	}

	sig := d.Strat.Evaluate(fv, pred)

	if sig != nil {
		handleSignal(sym, sig, fv, d)
	}

	logTick(sym, fv, pred, d)
}

// handleTick4H processes a tick for 4h timeframe.
func handleTick4H(ctx context.Context, sym string, candles []exchange.Candle, d ProcessSymbolDeps) {
	fv4h := d.FeatureBuilder4H.Build(candles)

	if fv4h == nil {
		log.Debug().
			Str("symbol", sym).
			Int("candles", len(candles)).
			Int("required", d.FeatureBuilder4H.MinCandles()).
			Msg("waiting for more candles (4h)")
		return
	}

	handleExitCheck4H(sym, fv4h, d)

	if d.Predictor == nil {
		logTick4H(sym, fv4h, nil, d)
		return
	}

	start := time.Now()
	pred, err := d.Predictor.Predict(fv4h.ToArray())
	d.Prom.ModelInferenceTime.Observe(time.Since(start).Seconds())

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("prediction failed (4h)")
		return
	}

	sig := d.Strat.Evaluate4H(fv4h, pred)

	if sig != nil {
		handleSignal4H(sym, sig, fv4h, d)
	}

	logTick4H(sym, fv4h, pred, d)
}

// handleExitCheck checks whether an existing position should be closed.
func handleExitCheck(sym string, fv *features.FeatureVector, d ProcessSymbolDeps) {
	pos, exists := d.RiskMgr.GetPosition(sym)
	if !exists {
		return
	}

	d.RiskMgr.UpdatePositionPnL(sym, fv.Close)
	d.Prom.UnrealizedPnLPerSymbol.WithLabelValues(sym).Set(pos.UnrealizedPnL)
	d.Prom.PositionSize.WithLabelValues(sym).Set(pos.Size)

	shouldClose, reason := d.RiskMgr.ShouldClosePosition(sym, fv.Close)
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
	order, err := d.ExecEngine.ClosePosition(sym, pos.Side, fv.Close, pos.Size, reason, strategy.SignalNone, "ml", pos.EntryPrice, pos.EntryTime)
	d.Prom.OrderExecutionTime.Observe(time.Since(start).Seconds())

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to close position")
		d.AlertMgr.Error("Close Position Failed", err)
		return
	}

	if paperExec, ok := d.Executor.(*execution.PaperExecutor); ok {
		paperExec.SimulateFill(order, fv.Close)
	}

	netPnL, err := d.RiskMgr.ClosePosition(sym, order.FilledPrice)
	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("risk manager close failed")
		return
	}

	d.Prom.PositionSize.WithLabelValues(sym).Set(0)
	d.Prom.UnrealizedPnLPerSymbol.WithLabelValues(sym).Set(0)

	log.Info().
		Str("symbol", sym).
		Str("reason", reason).
		Float64("pnl", netPnL).
		Float64("equity", d.RiskMgr.GetEquity()).
		Msg("position closed")

	d.AlertMgr.TradeClosed(sym, pos.Side, pos.EntryPrice, order.FilledPrice, pos.Size, netPnL, reason)
}

// handleSignal attempts to open a new position.
func handleSignal(sym string, sig *strategy.Signal, fv *features.FeatureVector, d ProcessSymbolDeps) {
	if err := d.RiskMgr.CanOpenPosition(sym); err != nil {
		log.Debug().Err(err).Str("symbol", sym).Msg("cannot open position")
		return
	}

	sizeMultiplier := d.Strat.ShouldReduceSize(fv)
	size, err := d.RiskMgr.CalculatePositionSize(sym, sig.Price, sig.StopLoss, sizeMultiplier)
	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to calculate position size")
		return
	}
	if size <= 0 {
		return
	}

	start := time.Now()
	order, err := d.ExecEngine.OpenPosition(sig, size)
	d.Prom.OrderExecutionTime.Observe(time.Since(start).Seconds())

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to open position")
		return
	}

	if paperExec, ok := d.Executor.(*execution.PaperExecutor); ok {
		paperExec.SimulateFill(order, fv.Close)
	}

	if order.FilledPrice <= 0 {
		log.Error().Str("symbol", sym).Float64("filled_price", order.FilledPrice).Msg("order filled at zero price, skipping position registration")
		return
	}

	var side string
	if sig.Type == strategy.SignalLong {
		side = "LONG"
	} else {
		side = "SHORT"
	}

	riskAmount := d.RiskMgr.GetEquity() * (d.Cfg.Risk.MaxRiskPerTradePct / 100.0) * sizeMultiplier
	if err := d.RiskMgr.OpenPosition(sym, side, order.FilledPrice, size, sig.StopLoss, sig.TakeProfit, riskAmount); err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to register position — attempting to cancel order")
		if cancelErr := d.Executor.CancelOrder(sym, order.ID); cancelErr != nil {
			log.Error().Err(cancelErr).Str("symbol", sym).Str("order_id", order.ID).Msg("CRITICAL: order placed but cannot cancel or register")
			d.AlertMgr.Error("Orphaned Order", fmt.Errorf("symbol=%s order=%s: placed but could not register or cancel", sym, order.ID))
		}
		return
	}

	d.Prom.PositionSize.WithLabelValues(sym).Set(size)

	log.Info().
		Str("symbol", sym).
		Str("side", side).
		Float64("price", order.FilledPrice).
		Float64("size", size).
		Float64("stop_loss", sig.StopLoss).
		Float64("take_profit", sig.TakeProfit).
		Float64("risk", riskAmount).
		Msg("position opened")

	d.AlertMgr.TradeOpened(sym, side, order.FilledPrice, size)
}

// handleExitCheck4H checks whether an existing position should be closed (4h).
func handleExitCheck4H(sym string, fv *features.FeatureVector4H, d ProcessSymbolDeps) {
	pos, exists := d.RiskMgr.GetPosition(sym)
	if !exists {
		return
	}

	d.RiskMgr.UpdatePositionPnL(sym, fv.Close)
	d.Prom.UnrealizedPnLPerSymbol.WithLabelValues(sym).Set(pos.UnrealizedPnL)
	d.Prom.PositionSize.WithLabelValues(sym).Set(pos.Size)

	shouldClose, reason := d.RiskMgr.ShouldClosePosition(sym, fv.Close)
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
	order, err := d.ExecEngine.ClosePosition(sym, pos.Side, fv.Close, pos.Size, reason, strategy.SignalNone, "ml", pos.EntryPrice, pos.EntryTime)
	d.Prom.OrderExecutionTime.Observe(time.Since(start).Seconds())

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to close position")
		d.AlertMgr.Error("Close Position Failed", err)
		return
	}

	if paperExec, ok := d.Executor.(*execution.PaperExecutor); ok {
		paperExec.SimulateFill(order, fv.Close)
	}

	netPnL, err := d.RiskMgr.ClosePosition(sym, order.FilledPrice)
	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("risk manager close failed")
		return
	}

	d.Prom.TotalTrades.Inc()
	if netPnL > 0 {
		d.Prom.WinningTrades.Inc()
	} else if netPnL < 0 {
		d.Prom.LosingTrades.Inc()
	}
	d.Prom.PositionSize.WithLabelValues(sym).Set(0)
	d.Prom.UnrealizedPnLPerSymbol.WithLabelValues(sym).Set(0)

	log.Info().
		Str("symbol", sym).
		Str("reason", reason).
		Float64("pnl", netPnL).
		Float64("equity", d.RiskMgr.GetEquity()).
		Msg("position closed (4h)")

	d.AlertMgr.TradeClosed(sym, pos.Side, pos.EntryPrice, order.FilledPrice, pos.Size, netPnL, reason)
}

// handleSignal4H attempts to open a new position for 4h timeframe.
func handleSignal4H(sym string, sig *strategy.Signal, fv *features.FeatureVector4H, d ProcessSymbolDeps) {
	if err := d.RiskMgr.CanOpenPosition(sym); err != nil {
		log.Debug().Err(err).Str("symbol", sym).Msg("cannot open position (4h)")
		return
	}

	sizeMultiplier := 1.0
	size, err := d.RiskMgr.CalculatePositionSize(sym, sig.Price, sig.StopLoss, sizeMultiplier)
	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to calculate position size")
		return
	}
	if size <= 0 {
		return
	}

	start := time.Now()
	order, err := d.ExecEngine.OpenPosition(sig, size)
	d.Prom.OrderExecutionTime.Observe(time.Since(start).Seconds())

	if err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to open position (4h)")
		return
	}

	if paperExec, ok := d.Executor.(*execution.PaperExecutor); ok {
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

	riskAmount := d.RiskMgr.GetEquity() * (d.Cfg.Risk.MaxRiskPerTradePct / 100.0) * sizeMultiplier
	if err := d.RiskMgr.OpenPosition(sym, side, order.FilledPrice, size, sig.StopLoss, sig.TakeProfit, riskAmount); err != nil {
		log.Error().Err(err).Str("symbol", sym).Msg("failed to register position — attempting to cancel order")
		if cancelErr := d.Executor.CancelOrder(sym, order.ID); cancelErr != nil {
			log.Error().Err(cancelErr).Str("symbol", sym).Str("order_id", order.ID).Msg("CRITICAL: order placed but cannot cancel or register")
			d.AlertMgr.Error("Orphaned Order", fmt.Errorf("symbol=%s order=%s: placed but could not register or cancel", sym, order.ID))
		}
		return
	}

	d.Prom.PositionSize.WithLabelValues(sym).Set(size)

	log.Info().
		Str("symbol", sym).
		Str("side", side).
		Float64("price", order.FilledPrice).
		Float64("size", size).
		Float64("stop_loss", sig.StopLoss).
		Float64("take_profit", sig.TakeProfit).
		Float64("risk", riskAmount).
		Msg("position opened (4h)")

	d.AlertMgr.TradeOpened(sym, side, order.FilledPrice, size)
}

// logTick4H emits a structured log line for 4h candles.
func logTick4H(sym string, fv *features.FeatureVector4H, pred *model.Prediction, d ProcessSymbolDeps) {
	stats := d.RiskMgr.GetStats()
	tradeStats := d.ExecEngine.GetTradeStats()

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

// logTick emits a structured log line for each processed candle.
func logTick(sym string, fv *features.FeatureVector, pred *model.Prediction, d ProcessSymbolDeps) {
	stats := d.RiskMgr.GetStats()
	tradeStats := d.ExecEngine.GetTradeStats()

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
