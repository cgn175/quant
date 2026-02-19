package main

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/rs/zerolog/log"
	"github.com/spf13/cobra"

	"github.com/cgn175/quant-bot/internal/config"
	"github.com/cgn175/quant-bot/internal/data"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/execution"
	"github.com/cgn175/quant-bot/internal/metrics"
	"github.com/cgn175/quant-bot/internal/risk"
	fundingarb "github.com/cgn175/quant-bot/internal/strategy/funding_arb"
)

// runFundingArb implements the funding rate arbitrage bot loop.
func runFundingArb(cmd *cobra.Command, cfg *config.Config) error {
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

	// Exchange client
	var exchangeClient exchange.Client = newExchangeClient(cfg)
	defer exchangeClient.Close()

	// Executor
	var executor execution.Executor
	feePercent := cfg.Execution.FeePercent()
	if cfg.Mode == "live" {
		executor = execution.NewLiveExecutor(cfg.Exchange.APIKey, cfg.Exchange.APISecret, cfg.Exchange.Testnet)
		log.Info().Msg("using live trading executor")
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

	// Portfolio monitor for cross-strategy position limits
	portfolioMonitor := risk.NewPortfolioMonitor(
		cfg.PortfolioRisk.MaxTotalPerpSpotExposure,
		cfg.PortfolioRisk.MaxPerSymbolExposure,
		cfg.PortfolioRisk.EnableCorrelatedCheck,
	)
	portfolioMonitor.SetMetrics(
		&prom.PortfolioSymbolExposure,
		prom.PortfolioTotalExposure,
		&prom.PortfolioEntriesBlocked,
	)
	log.Info().
		Float64("max_total", cfg.PortfolioRisk.MaxTotalPerpSpotExposure).
		Float64("max_per_symbol", cfg.PortfolioRisk.MaxPerSymbolExposure).
		Bool("correlated_check", cfg.PortfolioRisk.EnableCorrelatedCheck).
		Msg("portfolio monitor initialized")

	// Strategy
	strat := fundingarb.NewStrategy(cfg.Strategy.FundingArb, exchangeClient, executor, execEngine, cfg.Symbols, fundingStore, portfolioMonitor)

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
