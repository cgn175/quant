package bot

import (
	"context"
	"database/sql"
	"time"

	"github.com/cgn175/quant-bot/internal/config"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/strategy/liquidation"
	"github.com/rs/zerolog/log"
)

func RunLiquidation(ctx context.Context, cfg *config.Config) error {
	log.Info().Msg("starting liquidation cascade strategy")

	// Open liquidation database
	db, err := sql.Open("sqlite", cfg.Strategy.Liquidation.DBPath)
	if err != nil {
		return err
	}
	defer db.Close()

	// Create exchange client
	var client liquidation.LiquidationDataClient
	if cfg.Exchange.HubURL != "" {
		client = exchange.NewHubClient(cfg.Exchange.HubURL, cfg.Exchange.Testnet)
	} else {
		client = exchange.NewBinanceClient(cfg.Exchange.Testnet)
	}

	// Create liquidation strategy
	strategy := liquidation.NewLiquidationStrategy(cfg.Strategy.Liquidation, db, client)

	// Scan for opportunities every 5 minutes
	ticker := time.NewTicker(5 * time.Minute)
	defer ticker.Stop()

	scan := func() {
		for _, symbol := range cfg.Symbols {
			signal, err := strategy.ScanOpportunities(symbol)
			if err != nil {
				log.Error().Err(err).Str("symbol", symbol).Msg("scan failed")
				continue
			}

			if signal != nil && signal.Confidence >= cfg.Strategy.Liquidation.MinConfidence {
				log.Info().
					Str("symbol", signal.Symbol).
					Str("direction", signal.Direction).
					Float64("funding", signal.FundingRate).
					Float64("oi_change", signal.OIChange).
					Float64("liq_cluster", signal.LiqCluster).
					Float64("confidence", signal.Confidence).
					Msg("🔥 LIQUIDATION CASCADE SIGNAL")
			}
		}
	}

	// Scan immediately
	scan()

	// Then scan every 5 minutes
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			scan()
		}
	}
}
