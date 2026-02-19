package main

import (
	"os"
	"os/signal"
	"syscall"

	"github.com/cgn175/quant-bot/internal/data"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"github.com/spf13/cobra"
)

var (
	dbPath  string
	hubURL  string
	symbols []string
)

func main() {
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stderr, TimeFormat: "2006-01-02T15:04:05"})

	rootCmd := &cobra.Command{
		Use:   "orderflow_collector",
		Short: "Collect order flow imbalance data",
		Run:   run,
	}

	rootCmd.Flags().StringVar(&dbPath, "db", "data/orderflow.db", "Database path")
	rootCmd.Flags().StringVar(&hubURL, "hub-url", "localhost:9089/ws", "WebSocket hub URL")
	rootCmd.Flags().StringSliceVar(&symbols, "symbols", []string{"btcusdt", "ethusdt", "solusdt", "bnbusdt"}, "Symbols to collect")

	if err := rootCmd.Execute(); err != nil {
		log.Fatal().Err(err).Msg("failed to execute")
	}
}

func run(cmd *cobra.Command, args []string) {
	log.Info().
		Str("db", dbPath).
		Str("hub_url", hubURL).
		Strs("symbols", symbols).
		Msg("starting order flow collector")

	collector, err := data.NewOrderFlowCollector(dbPath, hubURL, symbols)
	if err != nil {
		log.Fatal().Err(err).Msg("failed to create collector")
	}

	if err := collector.Start(); err != nil {
		log.Fatal().Err(err).Msg("failed to start collector")
	}

	log.Info().Msg("order flow collector started")

	// Wait for interrupt
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, os.Interrupt, syscall.SIGTERM)
	<-sigCh

	log.Info().Msg("shutting down")
	collector.Stop()
}
