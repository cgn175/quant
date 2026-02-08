package main

import (
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/cgn175/quant-bot/internal/backtest"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/features"
	"github.com/cgn175/quant-bot/internal/model"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

func main() {
	dataFile := flag.String("data", "data_7days/BTC_USDT_1m_365d.csv", "CSV data file")
	modelPath := flag.String("model", "models/xgboost_model.onnx", "ONNX model path")
	numSamples := flag.Int("samples", 100, "Number of samples to test")
	flag.Parse()

	zerolog.SetGlobalLevel(zerolog.InfoLevel)
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stderr, TimeFormat: time.RFC3339})

	// Initialize model
	if err := model.Initialize(""); err != nil {
		log.Fatal().Err(err).Msg("Failed to init ONNX")
	}
	defer model.Shutdown()

	predictor, err := model.NewPredictor(*modelPath, len(features.FeatureNames()), 3)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to load model")
	}
	defer predictor.Close()

	// Load data
	symbol, bars, err := backtest.LoadCSV(*dataFile)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to load CSV")
	}

	log.Info().Str("symbol", symbol).Int("bars", len(bars)).Msg("Loaded data")

	// Build features for last N bars and check predictions
	builder := features.NewFeatureBuilder()
	minCandles := builder.MinCandles()

	fmt.Println("\n" + strings.Repeat("=", 100))
	fmt.Println("PREDICTION DISTRIBUTION ANALYSIS")
	fmt.Println(strings.Repeat("=", 100))

	upCount := 0
	downCount := 0
	neutralCount := 0

	upHighConf := 0   // p_up > 0.55
	downHighConf := 0 // p_down > 0.55

	maxProbUp := 0.0
	maxProbDown := 0.0

	samplesChecked := 0

	for i := len(bars) - *numSamples; i < len(bars); i++ {
		if i < minCandles {
			continue
		}

		// Convert bars to candles
		candles := make([]exchange.Candle, i+1)
		for j := 0; j <= i; j++ {
			candles[j] = exchange.Candle{
				Symbol:    bars[j].Symbol,
				OpenTime:  bars[j].Timestamp,
				CloseTime: bars[j].Timestamp.Add(time.Minute),
				Open:      bars[j].Open,
				High:      bars[j].High,
				Low:       bars[j].Low,
				Close:     bars[j].Close,
				Volume:    bars[j].Volume,
			}
		}

		fv := builder.Build(candles[:i+1], nil)
		if fv == nil {
			continue
		}

		pred, err := predictor.Predict(fv.ToArray())
		if err != nil {
			continue
		}

		samplesChecked++

		// Track distribution
		argmax := pred.ArgMax()
		switch argmax {
		case model.ClassUp:
			upCount++
		case model.ClassDown:
			downCount++
		case model.ClassNeutral:
			neutralCount++
		}

		if pred.ProbUp > 0.55 {
			upHighConf++
		}
		if pred.ProbDown > 0.55 {
			downHighConf++
		}

		if pred.ProbUp > maxProbUp {
			maxProbUp = pred.ProbUp
		}
		if pred.ProbDown > maxProbDown {
			maxProbDown = pred.ProbDown
		}

		// Print first 10 samples
		if samplesChecked <= 10 {
			fmt.Printf("Sample %d: P(DOWN)=%.3f, P(NEUTRAL)=%.3f, P(UP)=%.3f -> %s\n",
				samplesChecked, pred.ProbDown, pred.ProbNeutral, pred.ProbUp, classToString(argmax))
		}
	}

	fmt.Println("\n" + strings.Repeat("=", 100))
	fmt.Printf("Samples Analyzed: %d\n\n", samplesChecked)
	fmt.Printf("Prediction Distribution:\n")
	fmt.Printf("  UP:      %d (%.1f%%)\n", upCount, float64(upCount)/float64(samplesChecked)*100)
	fmt.Printf("  NEUTRAL: %d (%.1f%%)\n", neutralCount, float64(neutralCount)/float64(samplesChecked)*100)
	fmt.Printf("  DOWN:    %d (%.1f%%)\n\n", downCount, float64(downCount)/float64(samplesChecked)*100)

	fmt.Printf("High Confidence Predictions (p > 0.55):\n")
	fmt.Printf("  UP:   %d (%.1f%%)\n", upHighConf, float64(upHighConf)/float64(samplesChecked)*100)
	fmt.Printf("  DOWN: %d (%.1f%%)\n\n", downHighConf, float64(downHighConf)/float64(samplesChecked)*100)

	fmt.Printf("Max Probabilities:\n")
	fmt.Printf("  Max P(UP):   %.3f\n", maxProbUp)
	fmt.Printf("  Max P(DOWN): %.3f\n", maxProbDown)

	fmt.Println("\n" + strings.Repeat("=", 100))

	if upHighConf == 0 && downHighConf == 0 {
		fmt.Println("❌ PROBLEM: Model never produces high confidence predictions (>0.55)")
		fmt.Println("   This explains why no trades are generated!")
		fmt.Println("   SOLUTIONS:")
		fmt.Println("   1. Lower the threshold from 0.55 to 0.45-0.50")
		fmt.Println("   2. Retrain model with different parameters")
		fmt.Println("   3. Use different features or labeling strategy")
	} else {
		fmt.Printf("✓ Model produces some confident predictions\n")
	}

	fmt.Println(strings.Repeat("=", 100) + "\n")
}

func classToString(class int) string {
	switch class {
	case model.ClassDown:
		return "DOWN"
	case model.ClassNeutral:
		return "NEUTRAL"
	case model.ClassUp:
		return "UP"
	default:
		return "UNKNOWN"
	}
}
