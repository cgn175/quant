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
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/execution"
	"github.com/cgn175/quant-bot/internal/metrics"
	marketmaking "github.com/cgn175/quant-bot/internal/strategy/market_making"
)

// runMarketMaking implements the pure market making bot loop.
func runMarketMaking(cmd *cobra.Command, cfg *config.Config) error {
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
		Mode:           cfg.Mode,
		UseLimitOrders: true, // MM always uses limit orders
		SlippageBP:     cfg.Execution.SlippageBP,
		FeePercent:     feePercent,
		// No aggressive timeout for MM — it manages its own orders
	}
	execEngine := execution.NewEngine(execConfig, executor)

	// Metrics
	prom := metrics.NewMetrics()
	execEngine.SetMetrics(prom)

	// Start Prometheus metrics server for MM
	go func() {
		http.Handle("/metrics", promhttp.Handler())
		log.Info().Int("port", cfg.Monitoring.PrometheusPort).Msg("starting prometheus metrics server")
		if err := http.ListenAndServe(fmt.Sprintf(":%d", cfg.Monitoring.PrometheusPort), nil); err != nil {
			log.Error().Err(err).Msg("prometheus server failed")
		}
	}()

	// Strategy
	strat := marketmaking.NewStrategy(cfg.Strategy.MarketMaking, exchangeClient, executor, execEngine, cfg.Symbols, prom)

	// Block until context cancelled
	if err := strat.Start(ctx); err != nil {
		return err
	}

	<-ctx.Done()

	// Save stats on shutdown
	saveStats(execEngine, "market_making")

	log.Info().Msg("market making strategy stopped")
	return nil
}
