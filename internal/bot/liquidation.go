package bot

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"time"

	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/rs/zerolog/log"

	"github.com/cgn175/quant-bot/internal/config"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/metrics"
	"github.com/cgn175/quant-bot/internal/strategy/liquidation"
)

type markPriceUpdate struct {
	Symbol      string `json:"s"`
	MarkPrice   string `json:"p"`
	FundingRate string `json:"r"`
	NextFunding int64  `json:"T"`
}

func RunLiquidation(ctx context.Context, cfg *config.Config) error {
	log.Info().Msg("starting liquidation cascade strategy")

	// Create metrics
	prom := metrics.NewMetrics()

	// Start Prometheus metrics server
	go func() {
		http.Handle("/metrics", promhttp.Handler())
		port := cfg.Monitoring.PrometheusPort
		if port == 0 {
			port = 9094 // Default port for liquidation strategy
		}
		log.Info().Int("port", port).Msg("starting prometheus metrics server")
		if err := http.ListenAndServe(fmt.Sprintf(":%d", port), nil); err != nil {
			log.Error().Err(err).Msg("prometheus server failed")
		}
	}()

	// Initialize liquidation metrics to zero for all symbols
	for _, symbol := range cfg.Symbols {
		prom.LiqFundingRate.WithLabelValues(symbol).Set(0)
		prom.LiqOIChangePct.WithLabelValues(symbol).Set(0)
		prom.LiqSignalActive.WithLabelValues(symbol).Set(0)
		prom.LiqSignalConfidence.WithLabelValues(symbol).Set(0)
		prom.LiqLiquidationCluster.WithLabelValues(symbol).Set(0)
	}

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
			handler := func(sym string) func(data []byte) {
				return func(data []byte) {
					var update markPriceUpdate
					if err := json.Unmarshal(data, &update); err != nil {
						log.Error().Err(err).Msg("failed to parse markPrice update")
						return
					}

					// Parse funding rate from update
					fundingRate, _ := strconv.ParseFloat(update.FundingRate, 64)
					prom.LiqFundingRate.WithLabelValues(sym).Set(fundingRate)

					// Trigger scan when funding rate updates
					signal, err := strategy.ScanOpportunities(sym)
					if err != nil {
						log.Error().Err(err).Str("symbol", sym).Msg("scan failed")
						return
					}

					// Update metrics based on signal
					if signal != nil {
						// Update OI change metric
						prom.LiqOIChangePct.WithLabelValues(sym).Set(signal.OIChange)

						// Update signal confidence
						prom.LiqSignalConfidence.WithLabelValues(sym).Set(signal.Confidence)

						// Update liquidation cluster price
						prom.LiqLiquidationCluster.WithLabelValues(sym).Set(signal.LiqCluster)

						// Update active signal (0=none, 1=long_squeeze, 2=short_squeeze)
						signalValue := 0.0
						if signal.Direction == "long_squeeze" {
							signalValue = 1.0
						} else if signal.Direction == "short_squeeze" {
							signalValue = 2.0
						}
						prom.LiqSignalActive.WithLabelValues(sym).Set(signalValue)

						// Log high-confidence signals
						if signal.Confidence >= cfg.Strategy.Liquidation.MinConfidence {
							log.Info().
								Str("symbol", signal.Symbol).
								Str("direction", signal.Direction).
								Float64("funding", signal.FundingRate).
								Float64("oi_change", signal.OIChange).
								Float64("liq_cluster", signal.LiqCluster).
								Float64("confidence", signal.Confidence).
								Msg("🔥 LIQUIDATION CASCADE SIGNAL")

							// Increment signal counter
							prom.LiqSignalsTotal.WithLabelValues(sym, signal.Direction).Inc()
						}
					} else {
						// No signal - reset metrics
						prom.LiqSignalActive.WithLabelValues(sym).Set(0)
						prom.LiqSignalConfidence.WithLabelValues(sym).Set(0)
					}
				}
			}(symbol)

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

			if signal != nil {
				// Update metrics
				prom.LiqFundingRate.WithLabelValues(symbol).Set(signal.FundingRate)
				prom.LiqOIChangePct.WithLabelValues(symbol).Set(signal.OIChange)
				prom.LiqSignalConfidence.WithLabelValues(symbol).Set(signal.Confidence)
				prom.LiqLiquidationCluster.WithLabelValues(symbol).Set(signal.LiqCluster)

				signalValue := 0.0
				if signal.Direction == "long_squeeze" {
					signalValue = 1.0
				} else if signal.Direction == "short_squeeze" {
					signalValue = 2.0
				}
				prom.LiqSignalActive.WithLabelValues(symbol).Set(signalValue)

				if signal.Confidence >= cfg.Strategy.Liquidation.MinConfidence {
					log.Info().
						Str("symbol", signal.Symbol).
						Str("direction", signal.Direction).
						Float64("funding", signal.FundingRate).
						Float64("oi_change", signal.OIChange).
						Float64("liq_cluster", signal.LiqCluster).
						Float64("confidence", signal.Confidence).
						Msg("🔥 LIQUIDATION CASCADE SIGNAL")

					prom.LiqSignalsTotal.WithLabelValues(symbol, signal.Direction).Inc()
				}
			} else {
				// No signal - reset
				prom.LiqSignalActive.WithLabelValues(symbol).Set(0)
				prom.LiqSignalConfidence.WithLabelValues(symbol).Set(0)
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
