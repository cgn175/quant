package main

import (
	"flag"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/cgn175/quant-bot/internal/backtest"
	"github.com/cgn175/quant-bot/internal/features"
	"github.com/cgn175/quant-bot/internal/model"
	"github.com/cgn175/quant-bot/internal/risk"
	"github.com/cgn175/quant-bot/internal/strategy"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

func main() {
	// CLI flags
	dataDir := flag.String("data", "data_5m", "Directory with CSV data files")
	modelDir := flag.String("model-dir", "models", "Directory with per-symbol model subdirs (btc_5m/, eth_5m/, ...)")
	modelPath := flag.String("model", "", "Path to single ONNX model (overrides --model-dir)")
	outputPath := flag.String("output", "backtest_results.txt", "Output file for results")
	thresholdUp := flag.Float64("threshold-up", 0.50, "Probability threshold for LONG entry")
	thresholdDown := flag.Float64("threshold-down", 0.50, "Probability threshold for SHORT entry")
	stopLoss := flag.Float64("stop-loss", 1.0, "Stop loss percent")
	takeProfit := flag.Float64("take-profit", 2.0, "Take profit percent")
	minVolRatio := flag.Float64("min-vol-ratio", 0.5, "Minimum volume ratio filter")
	allowShort := flag.Bool("allow-short", false, "Allow short trades")
	timeframe := flag.String("timeframe", "5m", "Timeframe: 5m or 4h")
	startDateStr := flag.String("start-date", "", "Only backtest bars on or after this date (YYYY-MM-DD)")
	verbose := flag.Bool("v", false, "Verbose logging")
	flag.Parse()

	is4H := *timeframe == "4h"

	// Setup logging
	zerolog.TimeFieldFormat = zerolog.TimeFormatUnix
	if *verbose {
		zerolog.SetGlobalLevel(zerolog.DebugLevel)
		log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stderr, TimeFormat: time.RFC3339})
	} else {
		zerolog.SetGlobalLevel(zerolog.InfoLevel)
		log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stderr, TimeFormat: time.RFC3339})
	}

	log.Info().Str("timeframe", *timeframe).Msg("=== Backtest Runner ===")

	// Initialize ONNX runtime
	log.Info().Msg("Initializing ONNX runtime...")
	if err := model.Initialize(""); err != nil {
		log.Fatal().Err(err).Msg("Failed to initialize ONNX runtime")
	}
	defer model.Shutdown()

	// Load historical data
	log.Info().Str("dir", *dataDir).Msg("Loading historical data...")
	bars, err := loadHistoricalData(*dataDir)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to load historical data")
	}

	// Filter bars by start date if specified
	if *startDateStr != "" {
		startDate, err := time.Parse("2006-01-02", *startDateStr)
		if err != nil {
			log.Fatal().Err(err).Str("start-date", *startDateStr).Msg("Invalid start-date format (expected YYYY-MM-DD)")
		}
		log.Info().Str("start_date", startDate.Format("2006-01-02")).Msg("Filtering bars by start date")
		for symbol, barList := range bars {
			filtered := make([]*backtest.Bar, 0, len(barList))
			for _, b := range barList {
				if !b.Timestamp.Before(startDate) {
					filtered = append(filtered, b)
				}
			}
			bars[symbol] = filtered
			log.Info().Str("symbol", symbol).Int("before", len(barList)).Int("after", len(filtered)).Msg("Filtered bars")
		}
	}

	totalBars := 0
	for symbol, barList := range bars {
		totalBars += len(barList)
		log.Info().Str("symbol", symbol).Int("bars", len(barList)).Msg("Loaded data")
	}
	log.Info().Int("total_bars", totalBars).Msg("Data loaded")

	var numFeatures int
	var numClasses int
	if is4H {
		numFeatures = len(features.FeatureNames4H())
		numClasses = 2
	} else {
		numFeatures = len(features.FeatureNames())
		numClasses = 3
	}
	log.Info().Int("num_features", numFeatures).Int("num_classes", numClasses).Msg("Feature/class count")

	// Load models: either single model or per-symbol models
	predictors := make(map[string]*model.Predictor)

	if *modelPath != "" {
		// Single model for all symbols
		log.Info().Str("path", *modelPath).Msg("Loading single model...")
		pred, err := model.NewPredictor(*modelPath, numFeatures, numClasses)
		if err != nil {
			log.Fatal().Err(err).Msg("Failed to load model")
		}
		defer pred.Close()
		for symbol := range bars {
			predictors[symbol] = pred
		}
	} else {
		// Per-symbol models from model-dir
		var symbolModelMap map[string]string
		if is4H {
			symbolModelMap = map[string]string{
				"BTC/USDT": "btcusdt_4h_binary",
				"ETH/USDT": "ethusdt_4h_binary",
				"SOL/USDT": "solusdt_4h_binary",
				"BNB/USDT": "bnbusdt_4h_binary",
			}
		} else {
			symbolModelMap = map[string]string{
				"BTC/USDT": "btc_5m",
				"ETH/USDT": "eth_5m",
				"SOL/USDT": "sol_5m",
				"BNB/USDT": "bnb_5m",
			}
		}

		for symbol := range bars {
			subdir, ok := symbolModelMap[symbol]
			if !ok {
				log.Warn().Str("symbol", symbol).Msg("No model mapping, skipping")
				continue
			}
			onnxPath := filepath.Join(*modelDir, subdir, "xgboost_model.onnx")
			if _, err := os.Stat(onnxPath); os.IsNotExist(err) {
				log.Warn().Str("path", onnxPath).Str("symbol", symbol).Msg("Model not found, skipping")
				continue
			}
			log.Info().Str("symbol", symbol).Str("path", onnxPath).Msg("Loading model...")
			pred, err := model.NewPredictor(onnxPath, numFeatures, numClasses)
			if err != nil {
				log.Fatal().Err(err).Str("symbol", symbol).Msg("Failed to load model")
			}
			defer pred.Close()
			predictors[symbol] = pred
		}
	}

	if len(predictors) == 0 {
		log.Fatal().Msg("No models loaded - check model paths")
	}

	// Create backtest engine components
	log.Info().
		Float64("threshold_up", *thresholdUp).
		Float64("threshold_down", *thresholdDown).
		Float64("stop_loss_pct", *stopLoss).
		Float64("take_profit_pct", *takeProfit).
		Float64("min_vol_ratio", *minVolRatio).
		Bool("allow_short", *allowShort).
		Msg("Strategy config")

	featureBuilder := features.NewFeatureBuilder()
	var featureBuilder4H *features.Builder4H
	if is4H {
		featureBuilder4H = features.NewFeatureBuilder4H()
	}

	strategyEngine := strategy.NewStrategy(strategy.Config{
		ThresholdUp:             *thresholdUp,
		ThresholdDown:           *thresholdDown,
		SentimentThresholdLong:  -1.0, // Disabled: sentiment features are zeros
		SentimentThresholdShort: 2.0,  // Disabled: sentiment features are zeros
		SentimentExtremeLimit:   0.8,
		MinVolumeRatio:          *minVolRatio,
		StopLossPercent:         *stopLoss,
		TakeProfitPercent:       *takeProfit,
		AllowLong:               true,
		AllowShort:              *allowShort,
	})

	// We need a "multi-predictor" engine, so we'll run per-symbol backtests
	// and aggregate results.
	allTrades := make([]*backtest.Trade, 0)
	var totalStats backtest.BacktestStats
	totalStats.InitialEquity = 10000.0
	totalStats.FinalEquity = 10000.0

	for symbol, pred := range predictors {
		symbolBars, ok := bars[symbol]
		if !ok || len(symbolBars) == 0 {
			continue
		}

		log.Info().Str("symbol", symbol).Int("bars", len(symbolBars)).Msg("Running backtest...")

		symbolRiskMgr := risk.NewManager(risk.Config{
			InitialEquity:      10000.0,
			MaxRiskPerTradePct: 1.0,
			MaxDailyLossPct:    5.0,
			MaxOpenPositions:   1, // 1 position per symbol
			MaxLeverage:        2.0,
		})

		engine := backtest.NewEngine(
			strategyEngine,
			symbolRiskMgr,
			pred,
			featureBuilder,
			backtest.ExecutionConfig{
				FeePercent: 0.025,
				SlippageBP: 5.0,
				Mode:       "paper",
			},
		)
		if is4H {
			engine = backtest.NewEngine4H(
				strategyEngine,
				symbolRiskMgr,
				pred,
				featureBuilder4H,
				backtest.ExecutionConfig{
					FeePercent: 0.025,
					SlippageBP: 5.0,
					Mode:       "paper",
				},
			)
		}

		if err := engine.AddBars(symbol, symbolBars); err != nil {
			log.Error().Err(err).Str("symbol", symbol).Msg("Failed to add bars")
			continue
		}

		start := time.Now()
		stats, err := engine.Run()
		if err != nil {
			log.Error().Err(err).Str("symbol", symbol).Msg("Backtest failed")
			continue
		}
		elapsed := time.Since(start)

		trades := engine.GetTrades()
		allTrades = append(allTrades, trades...)

		log.Info().
			Str("symbol", symbol).
			Dur("duration", elapsed).
			Int("trades", len(trades)).
			Float64("pnl", stats.NetPnL).
			Float64("win_rate", stats.WinRate*100).
			Msg("Symbol backtest complete")
	}

	// Generate aggregated report
	log.Info().Int("total_trades", len(allTrades)).Msg("All symbol backtests complete")

	// Compute aggregated stats
	aggregateStats := computeAggregateStats(allTrades, 10000.0)

	reporter := backtest.NewReporter(&aggregateStats, allTrades)

	// Print to console
	fmt.Println(reporter.Summary())
	fmt.Println(reporter.SymbolStats())
	fmt.Println(reporter.MonthlyReturns())

	// Save detailed report to file
	if err := saveReport(reporter, &aggregateStats, *outputPath); err != nil {
		log.Error().Err(err).Msg("Failed to save report")
	} else {
		log.Info().Str("path", *outputPath).Msg("Report saved")
	}

	// Print verdict
	printVerdict(&aggregateStats)
}

func computeAggregateStats(trades []*backtest.Trade, initialEquity float64) backtest.BacktestStats {
	stats := backtest.BacktestStats{
		InitialEquity: initialEquity,
		TotalTrades:   len(trades),
	}

	if len(trades) == 0 {
		stats.FinalEquity = initialEquity
		return stats
	}

	equity := initialEquity
	peakEquity := equity
	maxDD := 0.0
	totalWins := 0.0
	totalLosses := 0.0

	minTime := trades[0].EntryTime
	maxTime := trades[0].ExitTime

	for _, t := range trades {
		stats.GrossPnL += t.GrossPnL
		stats.NetPnL += t.NetPnL
		equity += t.NetPnL

		if t.NetPnL > 0 {
			stats.WinningTrades++
			totalWins += t.NetPnL
		} else if t.NetPnL < 0 {
			stats.LosingTrades++
			totalLosses -= t.NetPnL
		}

		if equity > peakEquity {
			peakEquity = equity
		}
		if peakEquity > 0 {
			dd := (peakEquity - equity) / peakEquity
			if dd > maxDD {
				maxDD = dd
			}
		}

		if t.EntryTime.Before(minTime) {
			minTime = t.EntryTime
		}
		if t.ExitTime.After(maxTime) {
			maxTime = t.ExitTime
		}
	}

	stats.FinalEquity = equity
	stats.MaxDrawdown = maxDD
	stats.StartTime = minTime
	stats.EndTime = maxTime

	if stats.TotalTrades > 0 {
		stats.WinRate = float64(stats.WinningTrades) / float64(stats.TotalTrades)
		stats.AvgPnL = stats.NetPnL / float64(stats.TotalTrades)
	}

	if totalLosses > 0 {
		stats.ProfitFactor = totalWins / totalLosses
	}

	days := maxTime.Sub(minTime).Hours() / 24
	if days > 0 {
		stats.TotalDaysTraded = int(days)
	}

	// Compute Sharpe
	if len(trades) >= 2 && stats.TotalDaysTraded > 0 {
		returns := make([]float64, len(trades))
		for i, t := range trades {
			returns[i] = t.NetPnL / initialEquity
		}
		sum := 0.0
		for _, r := range returns {
			sum += r
		}
		mean := sum / float64(len(returns))

		sqSum := 0.0
		for _, r := range returns {
			d := r - mean
			sqSum += d * d
		}
		stddev := math.Sqrt(sqSum / float64(len(returns)))
		if stddev > 0 {
			tradesPerDay := float64(len(trades)) / float64(stats.TotalDaysTraded)
			tradesPerYear := tradesPerDay * 365.0
			stats.SharpeRatio = (mean / stddev) * math.Sqrt(tradesPerYear)
		}
	}

	return stats
}

func loadHistoricalData(dataDir string) (map[string][]*backtest.Bar, error) {
	files, err := filepath.Glob(filepath.Join(dataDir, "*.csv"))
	if err != nil {
		return nil, err
	}

	if len(files) == 0 {
		return nil, fmt.Errorf("no CSV files found in %s", dataDir)
	}

	bars := make(map[string][]*backtest.Bar)
	for _, file := range files {
		symbol, barList, err := backtest.LoadCSV(file)
		if err != nil {
			return nil, fmt.Errorf("failed to load %s: %w", file, err)
		}
		bars[symbol] = barList
	}

	return bars, nil
}

func saveReport(reporter *backtest.Reporter, stats *backtest.BacktestStats, path string) error {
	var sb strings.Builder

	sb.WriteString(reporter.Summary())
	sb.WriteString("\n")
	sb.WriteString(reporter.SymbolStats())
	sb.WriteString("\n")
	sb.WriteString(reporter.MonthlyReturns())
	sb.WriteString("\n")
	sb.WriteString(reporter.DrawdownAnalysis())
	sb.WriteString("\n")
	sb.WriteString(reporter.TradeLog())

	return os.WriteFile(path, []byte(sb.String()), 0644)
}

func printVerdict(stats *backtest.BacktestStats) {
	fmt.Println("\n" + strings.Repeat("=", 80))
	fmt.Println("                              VERDICT")
	fmt.Println(strings.Repeat("=", 80))

	totalReturn := 0.0
	annualizedReturn := 0.0
	if stats.InitialEquity > 0 {
		totalReturn = ((stats.FinalEquity - stats.InitialEquity) / stats.InitialEquity) * 100
	}
	if stats.TotalDaysTraded > 0 {
		annualizedReturn = totalReturn / float64(stats.TotalDaysTraded) * 365
	}

	if totalReturn > 10 && stats.SharpeRatio > 1.0 && stats.WinRate > 0.45 {
		fmt.Println("EXCELLENT: Model shows strong profitable potential")
		fmt.Printf("   - Total Return: %.2f%% (Annualized: %.2f%%)\n", totalReturn, annualizedReturn)
		fmt.Printf("   - Sharpe Ratio: %.2f (Good risk-adjusted returns)\n", stats.SharpeRatio)
		fmt.Printf("   - Win Rate: %.1f%% (Acceptable)\n", stats.WinRate*100)
		fmt.Println("   -> RECOMMENDATION: Proceed to paper trading with confidence")
	} else if totalReturn > 0 && stats.SharpeRatio > 0.5 {
		fmt.Println("MARGINAL: Model is profitable but needs improvement")
		fmt.Printf("   - Total Return: %.2f%% (Annualized: %.2f%%)\n", totalReturn, annualizedReturn)
		fmt.Printf("   - Sharpe Ratio: %.2f\n", stats.SharpeRatio)
		fmt.Printf("   - Win Rate: %.1f%%\n", stats.WinRate*100)
		fmt.Println("   -> RECOMMENDATION: Paper trade cautiously or retrain with better features")
	} else if stats.TotalTrades == 0 {
		fmt.Println("NO TRADES: Model did not generate any trades")
		fmt.Println("   -> RECOMMENDATION: Lower thresholds or check model predictions")
	} else {
		fmt.Println("UNPROFITABLE: Model is not ready for trading")
		fmt.Printf("   - Total Return: %.2f%% (Annualized: %.2f%%)\n", totalReturn, annualizedReturn)
		fmt.Printf("   - Sharpe Ratio: %.2f\n", stats.SharpeRatio)
		fmt.Printf("   - Win Rate: %.1f%%\n", stats.WinRate*100)
		fmt.Printf("   - Max Drawdown: %.2f%%\n", stats.MaxDrawdown*100)
		fmt.Println("   -> RECOMMENDATION: DO NOT trade live - retrain model or revise strategy")
	}

	fmt.Println(strings.Repeat("=", 80) + "\n")
}
