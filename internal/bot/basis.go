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
	"github.com/cgn175/quant-bot/internal/risk"
	basistrade "github.com/cgn175/quant-bot/internal/strategy/basis_trade"
)

// RunBasisTrade implements the basis trade (cash-and-carry) bot loop.
func RunBasisTrade(cmd *cobra.Command, cfg *config.Config) error {
	ctx, cancel := SetupContext(cmd)
	defer cancel()

	log.Info().
		Str("mode", cfg.Mode).
		Strs("symbols", cfg.Symbols).
		Str("exchange", cfg.Exchange.Name).
		Bool("testnet", cfg.Exchange.Testnet).
		Str("strategy", "basis_trade").
		Msg("starting basis trade bot")

	// Exchange client
	exchangeClient := SetupExchangeClient(cfg)
	defer exchangeClient.Close()

	// Executor
	var executor execution.Executor
	feePercent := cfg.Execution.FeePercent()
	if cfg.Mode == "live" {
		// Basis trade needs spot for one leg, futures for the other
		// We'll use spot executor here; strategy will handle both legs
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

	// Start Prometheus metrics server
	go func() {
		http.Handle("/metrics", promhttp.Handler())
		log.Info().Int("port", cfg.Monitoring.PrometheusPort).Msg("starting prometheus metrics server")
		if err := http.ListenAndServe(fmt.Sprintf(":%d", cfg.Monitoring.PrometheusPort), nil); err != nil {
			log.Error().Err(err).Msg("prometheus server failed")
		}
	}()

	// Basis trade store (reusing FundingStore for position persistence)
	store, err := data.NewFundingStore(cfg.Strategy.BasisTrade.DBPath)
	if err != nil {
		return fmt.Errorf("open basis trade store: %w", err)
	}
	defer store.Close()

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
	strat := basistrade.NewStrategy(cfg.Strategy.BasisTrade, cfg.Exchange, exchangeClient, executor, execEngine, cfg.Symbols, store, portfolioMonitor)

	// Block until context cancelled
	if err := strat.Start(ctx); err != nil {
		return err
	}

	<-ctx.Done()

	// Save stats on shutdown
	saveStats(execEngine, "basis_trade")

	log.Info().Msg("basis trade strategy stopped")
	return nil
}
