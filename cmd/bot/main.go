package main

import (
	"os"
	"os/signal"
	"syscall"
	"time"

	"golang.org/x/sync/errgroup"

	"github.com/cgn175/quant-bot/internal/config"
	"github.com/cgn175/quant-bot/internal/data"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/execution"
	"github.com/cgn175/quant-bot/internal/features"
	"github.com/cgn175/quant-bot/internal/model"
	"github.com/cgn175/quant-bot/internal/risk"
	"github.com/cgn175/quant-bot/internal/sentiment"
	"github.com/cgn175/quant-bot/internal/strategy"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"github.com/spf13/cobra"
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

func run(cmd *cobra.Command, args []string) error {
	cfg, err := config.Load(configPath)
	if err != nil {
		return err
	}

	log.Info().
		Str("mode", cfg.Mode).
		Strs("symbols", cfg.Symbols).
		Str("exchange", cfg.Exchange.Name).
		Bool("testnet", cfg.Exchange.Testnet).
		Msg("starting bot")

	if err := model.Initialize(cfg.Model.RuntimeLibPath); err != nil {
		return err
	}
	defer model.Shutdown()

	var predictor *model.Predictor
	if cfg.Model.Path != "" {
		if _, err := os.Stat(cfg.Model.Path); err == nil {
			predictor, err = model.NewPredictor(cfg.Model.Path, len(features.FeatureNames()))
			if err != nil {
				log.Warn().Err(err).Msg("failed to load model, running without predictions")
			} else {
				defer predictor.Close()
				log.Info().Str("path", cfg.Model.Path).Msg("model loaded")
			}
		} else {
			log.Warn().Str("path", cfg.Model.Path).Msg("model file not found, running without predictions")
		}
	}

	store := data.NewCandleStore(500)
	featureBuilder := features.NewFeatureBuilder()

	sentimentClient := sentiment.NewClient(
		cfg.Sentiment.URL,
		time.Duration(cfg.Sentiment.PollIntervalSeconds)*time.Second,
	)
	sentimentClient.Start(cfg.Symbols)
	defer sentimentClient.Stop()

	// Initialize strategy
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
		AllowShort:              cfg.Mode != "live", // Disable shorts in live mode initially
	}
	strat := strategy.NewStrategy(strategyConfig)

	// Initialize risk manager
	riskConfig := risk.Config{
		InitialEquity:      10000.0, // TODO: Get from config or account balance
		MaxRiskPerTradePct: cfg.Risk.MaxRiskPerTradePct,
		MaxDailyLossPct:    cfg.Risk.MaxDailyLossPct,
		MaxOpenPositions:   cfg.Risk.MaxOpenPositions,
		MaxLeverage:        cfg.Risk.MaxLeverage,
	}
	riskMgr := risk.NewManager(riskConfig)

	// Initialize execution engine
	var executor execution.Executor
	if cfg.Mode == "paper" || cfg.Mode == "" {
		executor = execution.NewPaperExecutor(cfg.Execution.SlippageBP, 0.1)
		log.Info().Msg("using paper trading executor")
	} else {
		executor = execution.NewLiveExecutor(cfg.Exchange.APIKey, cfg.Exchange.APISecret, cfg.Exchange.Testnet)
		log.Info().Msg("using live trading executor")
	}

	execConfig := execution.Config{
		Mode:           cfg.Mode,
		UseLimitOrders: cfg.Execution.UseLimitOrders,
		SlippageBP:     cfg.Execution.SlippageBP,
		FeePercent:     0.1,
	}
	execEngine := execution.NewEngine(execConfig, executor)

	exchangeClient := exchange.NewBinanceClient(cfg.Exchange.Testnet)
	defer exchangeClient.Close()

	g, _ := errgroup.WithContext(cmd.Context())
	for _, symbol := range cfg.Symbols {
		sym := symbol
		g.Go(func() error {
			return exchangeClient.SubscribeCandles(sym, cfg.BarSize, func(c exchange.Candle) {
				store.Add(c)

				candles := store.GetAll(sym)
				sent := sentimentClient.Get(sym)
				fv := featureBuilder.Build(candles, sent)

				if fv == nil {
					log.Debug().
						Str("symbol", sym).
						Int("candles", len(candles)).
						Int("required", featureBuilder.MinCandles()).
						Msg("waiting for more candles")
					return
				}

				// Update position PnL
				if pos, exists := riskMgr.GetPosition(sym); exists {
					riskMgr.UpdatePositionPnL(sym, fv.Close)

					// Check if we should close the position
					if shouldClose, reason := riskMgr.ShouldClosePosition(sym, fv.Close); shouldClose {
						log.Info().
							Str("symbol", sym).
							Str("reason", reason).
							Float64("price", fv.Close).
							Float64("pnl", pos.UnrealizedPnL).
							Msg("closing position")

						order, err := execEngine.ClosePosition(sym, pos.Side, fv.Close, pos.Size, reason, strategy.SignalNone, pos.EntryPrice, pos.EntryTime)
						if err != nil {
							log.Error().Err(err).Str("symbol", sym).Msg("failed to close position")
						} else {
							pnl, _ := riskMgr.ClosePosition(sym, order.FilledPrice)
							log.Info().
								Str("symbol", sym).
								Float64("pnl", pnl).
								Float64("equity", riskMgr.GetEquity()).
								Msg("position closed")
						}
					}
				}

				logEvent := log.Info().
					Str("symbol", sym).
					Float64("close", fv.Close).
					Float64("rsi14", fv.RSI14).
					Float64("ema21", fv.EMA21).
					Float64("bb_width", fv.BBWidth).
					Float64("sent_1h", fv.SentimentScore1h).
					Int("candles", len(candles))

				if predictor != nil {
					pred, err := predictor.Predict(fv.ToSlice())
					if err != nil {
						log.Error().Err(err).Str("symbol", sym).Msg("prediction failed")
					} else {
						logEvent = logEvent.
							Float64("p_down", pred.ProbDown).
							Float64("p_neutral", pred.ProbNeutral).
							Float64("p_up", pred.ProbUp)

						// Evaluate strategy signal
						sig := strat.Evaluate(fv, pred)
						if sig != nil {
							logEvent = logEvent.Str("signal", sig.Type.String())

							// Check if we can open a position
							if err := riskMgr.CanOpenPosition(sym); err == nil {
								// Calculate position size
								sizeMultiplier := strat.ShouldReduceSize(fv)
								size, err := riskMgr.CalculatePositionSize(sym, sig.Price, sig.StopLoss, sizeMultiplier)
								if err != nil {
									log.Error().Err(err).Str("symbol", sym).Msg("failed to calculate position size")
								} else {
									// Execute the trade
									order, err := execEngine.OpenPosition(sig, size)
									if err != nil {
										log.Error().Err(err).Str("symbol", sym).Msg("failed to open position")
									} else {
										// Simulate fill for paper trading
										if paperExec, ok := executor.(*execution.PaperExecutor); ok {
											paperExec.SimulateFill(order, fv.Close)
										}

										// Track in risk manager
										var side string
										if sig.Type == strategy.SignalLong {
											side = "LONG"
										} else {
											side = "SHORT"
										}

										riskAmount := riskMgr.GetEquity() * (cfg.Risk.MaxRiskPerTradePct / 100.0) * sizeMultiplier
										err = riskMgr.OpenPosition(sym, side, order.FilledPrice, size, sig.StopLoss, sig.TakeProfit, riskAmount)
										if err != nil {
											log.Error().Err(err).Str("symbol", sym).Msg("failed to track position")
										} else {
											log.Info().
												Str("symbol", sym).
												Str("side", side).
												Float64("price", order.FilledPrice).
												Float64("size", size).
												Float64("stop_loss", sig.StopLoss).
												Float64("take_profit", sig.TakeProfit).
												Float64("risk", riskAmount).
												Msg("position opened")
										}
									}
								}
							} else {
								log.Debug().Err(err).Str("symbol", sym).Msg("cannot open position")
							}
						}
					}
				}

				// Log stats
				stats := riskMgr.GetStats()
				tradeStats := execEngine.GetTradeStats()
				logEvent.
					Float64("equity", stats.Equity).
					Float64("daily_pnl", stats.DailyPnL).
					Int("positions", stats.OpenPositions).
					Int("total_trades", tradeStats.TotalTrades).
					Float64("win_rate", tradeStats.WinRate).
					Msg("tick")
			})
		})
	}
	if err := g.Wait(); err != nil {
		return err
	}

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	<-sigCh

	log.Info().Msg("shutting down")
	return nil
}
