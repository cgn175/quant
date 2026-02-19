package bot

import (
	"fmt"
	"net/http"

	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/rs/zerolog/log"
	"github.com/spf13/cobra"

	"github.com/cgn175/quant-bot/internal/config"
	"github.com/cgn175/quant-bot/internal/data"
	"github.com/cgn175/quant-bot/internal/execution"
	"github.com/cgn175/quant-bot/internal/metrics"
	fundingarb "github.com/cgn175/quant-bot/internal/strategy/funding_arb"
)

// RunFundingArb implements the funding rate arbitrage bot loop.
func RunFundingArb(cmd *cobra.Command, cfg *config.Config) error {
	ctx, cancel := SetupContext(cmd)
	defer cancel()

	log.Info().
		Str("mode", cfg.Mode).
		Strs("symbols", cfg.Symbols).
		Str("exchange", cfg.Exchange.Name).
		Bool("testnet", cfg.Exchange.Testnet).
		Str("strategy", cfg.Strategy.Type).
		Msg("starting funding arb bot")

	// Exchange client
	exchangeClient := SetupExchangeClient(cfg)
	defer exchangeClient.Close()

	// Executor
	var executor execution.Executor
	feePercent := cfg.Execution.FeePercent()
	if cfg.Mode == "live" {
		// Use futures executor for funding arb (perpetual contracts)
		executor = execution.NewLiveFuturesExecutor(cfg.Exchange.APIKey, cfg.Exchange.APISecret, cfg.Exchange.Testnet)
		log.Info().Msg("using live futures trading executor")
	} else {
		executor = execution.NewPaperExecutor(cfg.Execution.SlippageBP, feePercent)
		log.Info().Msg("using paper trading executor")
	}

	// Execution Engine
	execConfig := execution.Config{
		Mode:       cfg.Mode,
		SlippageBP: cfg.Execution.SlippageBP,
		FeePercent: feePercent,
	}
	execEngine := execution.NewEngine(execConfig, executor)

	// Metrics
	prom := metrics.NewMetrics()
	execEngine.SetMetrics(prom)

	// Start Prometheus metrics server for Funding Arb
	go func() {
		http.Handle("/metrics", promhttp.Handler())
		log.Info().Int("port", cfg.Monitoring.PrometheusPort).Msg("starting prometheus metrics server")
		if err := http.ListenAndServe(fmt.Sprintf(":%d", cfg.Monitoring.PrometheusPort), nil); err != nil {
			log.Error().Err(err).Msg("prometheus server failed")
		}
	}()

	// Funding store (SQLite persistence for positions + rates)
	fundingStore, err := data.NewFundingStore(cfg.Strategy.FundingArb.DBPath)
	if err != nil {
		return fmt.Errorf("open funding store: %w", err)
	}
	defer fundingStore.Close()

	// Strategy
	strat := fundingarb.NewStrategy(cfg.Strategy.FundingArb, exchangeClient, executor, execEngine, cfg.Symbols, fundingStore)

	// Block until context cancelled
	if err := strat.Start(ctx); err != nil {
		return err
	}

	<-ctx.Done()

	// Save stats on shutdown
	saveStats(execEngine, "funding_arb")

	log.Info().Msg("funding arb strategy stopped")
	return nil
}
