package bot

import (
	"context"
	"database/sql"
	"encoding/json"
	"time"

	"github.com/cgn175/quant-bot/internal/config"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/strategy/liquidation"
	"github.com/rs/zerolog/log"
)

type markPriceUpdate struct {
	Symbol      string `json:"s"`
	MarkPrice   string `json:"p"`
	FundingRate string `json:"r"`
	NextFunding int64  `json:"T"`
}

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

	// Subscribe to markPrice streams for real-time funding rate updates
	if hubClient, ok := client.(*exchange.HubClient); ok {
		// Subscribe to markPrice for each symbol
		for _, symbol := range cfg.Symbols {
			stream := symbol + "@markPrice"
			handler := func(data []byte) {
				var update markPriceUpdate
				if err := json.Unmarshal(data, &update); err != nil {
					log.Error().Err(err).Msg("failed to parse markPrice update")
					return
				}

				// Trigger scan when funding rate updates
				signal, err := strategy.ScanOpportunities(update.Symbol)
				if err != nil {
					log.Error().Err(err).Str("symbol", update.Symbol).Msg("scan failed")
					return
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

			if err := hubClient.SubscribeRaw(stream, handler); err != nil {
				log.Error().Err(err).Str("stream", stream).Msg("failed to subscribe")
			} else {
				log.Info().Str("stream", stream).Msg("subscribed to markPrice stream")
			}
		}

		// Keep running until context cancelled
		<-ctx.Done()
		return nil
	}

	// Fallback: REST polling if not using hub
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

	scan()

	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			scan()
		}
	}
}
