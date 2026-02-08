package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"math/rand"
	"os"
	"time"

	"github.com/cgn175/quant-bot/internal/features"
	"github.com/cgn175/quant-bot/internal/model"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

func main() {
	// CLI flags
	modelPath := flag.String("model", "models/xgboost_model.onnx", "Path to ONNX model")
	featuresPath := flag.String("features", "models/features.json", "Path to features.json")
	verbose := flag.Bool("v", false, "Verbose output")
	flag.Parse()

	// Setup logging
	zerolog.TimeFieldFormat = zerolog.TimeFormatUnix
	if *verbose {
		zerolog.SetGlobalLevel(zerolog.DebugLevel)
		log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stderr, TimeFormat: time.RFC3339})
	} else {
		zerolog.SetGlobalLevel(zerolog.InfoLevel)
	}

	log.Info().Msg("=== ONNX Model Integration Test ===")

	// Step 1: Verify feature alignment
	if err := verifyFeatureAlignment(*featuresPath); err != nil {
		log.Fatal().Err(err).Msg("Feature alignment check failed")
	}

	// Step 2: Initialize ONNX runtime
	log.Info().Msg("Initializing ONNX runtime...")
	if err := model.Initialize(""); err != nil {
		log.Fatal().Err(err).Msg("Failed to initialize ONNX runtime")
	}
	defer model.Shutdown()

	// Step 3: Load model
	numFeatures := len(features.FeatureNames())
	log.Info().Int("num_features", numFeatures).Str("path", *modelPath).Msg("Loading model...")
	predictor, err := model.NewPredictor(*modelPath, numFeatures, 3)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to load model")
	}
	defer predictor.Close()

	log.Info().Msg("✓ Model loaded successfully")

	// Step 4: Test inference with random features
	log.Info().Msg("Testing inference with random features...")
	if err := testRandomInference(predictor, numFeatures); err != nil {
		log.Fatal().Err(err).Msg("Random inference test failed")
	}

	// Step 5: Test inference with realistic features
	log.Info().Msg("Testing inference with realistic features...")
	if err := testRealisticInference(predictor); err != nil {
		log.Fatal().Err(err).Msg("Realistic inference test failed")
	}

	// Step 6: Benchmark inference speed
	log.Info().Msg("Benchmarking inference speed...")
	if err := benchmarkInference(predictor, numFeatures); err != nil {
		log.Fatal().Err(err).Msg("Benchmark failed")
	}

	log.Info().Msg("=== All Tests Passed ✓ ===")
}

// verifyFeatureAlignment checks that Go feature order matches features.json from Python training
func verifyFeatureAlignment(featuresPath string) error {
	log.Info().Str("path", featuresPath).Msg("Verifying feature alignment...")

	// Read Python features.json
	data, err := os.ReadFile(featuresPath)
	if err != nil {
		return fmt.Errorf("failed to read features.json: %w", err)
	}

	var pythonFeatures []string
	if err := json.Unmarshal(data, &pythonFeatures); err != nil {
		return fmt.Errorf("failed to parse features.json: %w", err)
	}

	// Get Go features
	goFeatures := features.FeatureNames()

	// Compare
	if len(goFeatures) != len(pythonFeatures) {
		return fmt.Errorf("feature count mismatch: Go=%d, Python=%d", len(goFeatures), len(pythonFeatures))
	}

	mismatches := []string{}
	for i, goFeat := range goFeatures {
		if goFeat != pythonFeatures[i] {
			mismatches = append(mismatches, fmt.Sprintf("  Index %d: Go='%s' != Python='%s'", i, goFeat, pythonFeatures[i]))
		}
	}

	if len(mismatches) > 0 {
		return fmt.Errorf("feature order mismatch:\n%v", mismatches)
	}

	log.Info().Int("count", len(goFeatures)).Msg("✓ Feature alignment verified")
	for i, feat := range goFeatures {
		log.Debug().Int("index", i).Str("feature", feat).Msg("Feature")
	}

	return nil
}

// testRandomInference runs inference with random features to ensure basic functionality
func testRandomInference(predictor *model.Predictor, numFeatures int) error {
	log.Info().Msg("Running 10 random inference tests...")

	for i := 0; i < 10; i++ {
		// Generate random features
		features := make([]float64, numFeatures)
		for j := range features {
			features[j] = rand.Float64()*100 - 50 // Random values between -50 and 50
		}

		// Run inference
		pred, err := predictor.Predict(features)
		if err != nil {
			return fmt.Errorf("inference %d failed: %w", i, err)
		}

		// Validate probabilities
		if err := validatePrediction(pred); err != nil {
			return fmt.Errorf("invalid prediction %d: %w", i, err)
		}

		log.Debug().
			Int("test", i).
			Float64("p_down", pred.ProbDown).
			Float64("p_neutral", pred.ProbNeutral).
			Float64("p_up", pred.ProbUp).
			Int("argmax", pred.ArgMax()).
			Msg("Prediction")
	}

	log.Info().Msg("✓ Random inference tests passed")
	return nil
}

// testRealisticInference tests with realistic crypto market features
func testRealisticInference(predictor *model.Predictor) error {
	log.Info().Msg("Running realistic inference test (simulated BTC features)...")

	// Simulate realistic BTC/USDT features
	realisticFeatures := []float64{
		45000.0, // close
		0.0005,  // log_ret_1m
		0.002,   // log_ret_5m
		44950.0, // ema_5
		44900.0, // ema_9
		44800.0, // ema_21
		44600.0, // ema_50
		55.5,    // rsi_7
		58.3,    // rsi_14
		45200.0, // bb_upper
		45000.0, // bb_middle
		44800.0, // bb_lower
		0.0089,  // bb_width
		50.0,    // macd
		45.0,    // macd_signal
		5.0,     // macd_histogram
		1.15,    // volume_ratio
		0.25,    // sentiment_1h
		0.18,    // sentiment_24h
		0.5,     // mentions_zscore
		0.1,     // sentiment_velocity
		0.707,   // hour_sin (roughly 9am)
		0.707,   // hour_cos
	}

	pred, err := predictor.Predict(realisticFeatures)
	if err != nil {
		return fmt.Errorf("realistic inference failed: %w", err)
	}

	if err := validatePrediction(pred); err != nil {
		return fmt.Errorf("invalid realistic prediction: %w", err)
	}

	log.Info().
		Float64("p_down", pred.ProbDown).
		Float64("p_neutral", pred.ProbNeutral).
		Float64("p_up", pred.ProbUp).
		Int("predicted_class", pred.ArgMax()).
		Str("class_name", classToString(pred.ArgMax())).
		Msg("✓ Realistic prediction")

	return nil
}

// benchmarkInference measures inference latency
func benchmarkInference(predictor *model.Predictor, numFeatures int) error {
	numRuns := 1000
	features := make([]float64, numFeatures)
	for j := range features {
		features[j] = rand.Float64() * 100
	}

	log.Info().Int("iterations", numRuns).Msg("Running benchmark...")

	start := time.Now()
	for i := 0; i < numRuns; i++ {
		_, err := predictor.Predict(features)
		if err != nil {
			return fmt.Errorf("benchmark inference %d failed: %w", i, err)
		}
	}
	elapsed := time.Since(start)

	avgLatency := elapsed / time.Duration(numRuns)
	throughput := float64(numRuns) / elapsed.Seconds()

	log.Info().
		Dur("total_time", elapsed).
		Dur("avg_latency", avgLatency).
		Float64("throughput_per_sec", throughput).
		Msg("✓ Benchmark results")

	// Check if latency is acceptable (target < 10ms for real-time trading)
	if avgLatency > 10*time.Millisecond {
		log.Warn().
			Dur("latency", avgLatency).
			Msg("⚠ Average latency exceeds 10ms target (may impact high-frequency trading)")
	} else {
		log.Info().
			Dur("latency", avgLatency).
			Msg("✓ Latency within acceptable range for real-time trading")
	}

	return nil
}

// validatePrediction checks that probabilities are valid
func validatePrediction(pred *model.Prediction) error {
	// Check range [0, 1]
	if pred.ProbDown < 0 || pred.ProbDown > 1 {
		return fmt.Errorf("ProbDown out of range: %f", pred.ProbDown)
	}
	if pred.ProbNeutral < 0 || pred.ProbNeutral > 1 {
		return fmt.Errorf("ProbNeutral out of range: %f", pred.ProbNeutral)
	}
	if pred.ProbUp < 0 || pred.ProbUp > 1 {
		return fmt.Errorf("ProbUp out of range: %f", pred.ProbUp)
	}

	// Check sum ≈ 1.0 (allow small floating point error)
	sum := pred.ProbDown + pred.ProbNeutral + pred.ProbUp
	if sum < 0.99 || sum > 1.01 {
		return fmt.Errorf("probabilities don't sum to 1.0: %f", sum)
	}

	// Check argmax is valid
	argmax := pred.ArgMax()
	if argmax < 0 || argmax > 2 {
		return fmt.Errorf("invalid argmax: %d", argmax)
	}

	return nil
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
