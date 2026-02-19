package main

import (
	"os"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"github.com/spf13/cobra"

	"github.com/cgn175/quant-bot/internal/bot"
	"github.com/cgn175/quant-bot/internal/config"
)

var (
	configPath string
	rootCmd    = &cobra.Command{
		Use:   "bot",
		Short: "Crypto scalping bot",
		RunE:  run,
	}
)

func init() {
	rootCmd.PersistentFlags().StringVarP(&configPath, "config", "c", "config.yaml", "config file path")
}

func main() {
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stderr, TimeFormat: "15:04:05"})
	zerolog.SetGlobalLevel(zerolog.InfoLevel)

	if err := rootCmd.Execute(); err != nil {
		log.Fatal().Err(err).Msg("failed to execute command")
	}
}

func run(cmd *cobra.Command, args []string) error {
	cfg, err := config.Load(configPath)
	if err != nil {
		return err
	}

	log.Info().
		Str("mode", cfg.Mode).
		Strs("symbols", cfg.Symbols).
		Str("exchange", cfg.Exchange.Name).
		Bool("testnet", cfg.Exchange.Testnet).
		Str("strategy", cfg.Strategy.Type).
		Msg("starting bot")

	// Route to the appropriate strategy runner
	switch cfg.Strategy.Type {
	case "trend_following":
		return bot.RunTrendFollowing(cmd, cfg)
	case "market_making":
		return bot.RunMarketMaking(cmd, cfg)
	case "funding_arb":
		return bot.RunFundingArb(cmd, cfg)
	case "basis_trade":
		return bot.RunBasisTrade(cmd, cfg)
	default:
		// Default to ML strategy for backward compatibility
		return bot.RunMLStrategy(cmd, cfg)
	}
}
