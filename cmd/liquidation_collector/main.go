package main

import (
	"context"
	"flag"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/cgn175/quant-bot/internal/data"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

func main() {
	var (
		dbPath = flag.String("db", "liquidations.db", "SQLite database path")
		debug  = flag.Bool("debug", false, "Enable debug logging")
	)
	flag.Parse()

	// Setup logging
	zerolog.TimeFieldFormat = time.RFC3339
	if *debug {
		zerolog.SetGlobalLevel(zerolog.DebugLevel)
		log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stderr})
	} else {
		zerolog.SetGlobalLevel(zerolog.InfoLevel)
	}

	log.Info().Msg("Starting liquidation data collector")

	// Target symbols for liquidation cascade analysis
	symbols := []string{
		"BTCUSDT",
		"ETHUSDT", 
		"SOLUSDT",
		"BNBUSDT",
	}

	// Create collector
	collector, err := data.NewLiquidationCollector(*dbPath, symbols)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to create liquidation collector")
	}

	// Start collection
	if err := collector.Start(); err != nil {
		log.Fatal().Err(err).Msg("Failed to start liquidation collector")
	}

	// Setup graceful shutdown
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	log.Info().Strs("symbols", symbols).Str("db", *dbPath).Msg("Liquidation collector running")

	// Wait for shutdown signal
	select {
	case sig := <-sigChan:
		log.Info().Str("signal", sig.String()).Msg("Received shutdown signal")
	case <-ctx.Done():
	}

	log.Info().Msg("Shutting down liquidation collector")
	collector.Stop()
	log.Info().Msg("Liquidation collector stopped")
}