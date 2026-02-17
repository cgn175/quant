package main

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/rs/zerolog/log"

	"github.com/cgn175/quant-bot/internal/alerts"
	"github.com/cgn175/quant-bot/internal/config"
	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/cgn175/quant-bot/internal/execution"
	"github.com/cgn175/quant-bot/internal/metrics"
	"github.com/cgn175/quant-bot/internal/risk"
	"github.com/cgn175/quant-bot/internal/strategy"
)

// tickEvent is sent from the WebSocket candle handler to the per-symbol
// processing goroutine.  This decouples the WS read loop from the
// (potentially slow) feature-building / model-inference / order-execution
// pipeline so we never block the WebSocket connection.
type tickEvent struct {
	symbol string
	candle exchange.Candle
}

// runPeriodicTasks handles recurring maintenance: metric snapshots and the
// daily Telegram PnL summary.
func runPeriodicTasks(ctx context.Context, riskMgr *risk.Manager, execEngine *execution.Engine, prom *metrics.Metrics, alertMgr *alerts.Manager) {
	dailyTicker := time.NewTicker(24 * time.Hour)
	defer dailyTicker.Stop()

	statsTicker := time.NewTicker(30 * time.Second)
	defer statsTicker.Stop()

	for {
		select {
		case <-ctx.Done():
			return

		case <-statsTicker.C:
			stats := riskMgr.GetStats()
			prom.Equity.Set(stats.Equity)
			prom.DailyPnL.Set(stats.DailyPnL)
			prom.OpenPositions.Set(float64(stats.OpenPositions))

			// Check daily loss limit and alert
			if stats.DailyPnL < -stats.DailyLossLimit {
				alertMgr.DailyLossLimit(stats.DailyPnL, stats.DailyLossLimit)
			}

		case <-dailyTicker.C:
			stats := riskMgr.GetStats()
			tradeStats := execEngine.GetTradeStats()
			alertMgr.DailyPnLSummary(
				stats.DailyPnL,
				stats.Equity,
				tradeStats.WinRate,
				tradeStats.TotalTrades,
			)
		}
	}
}

// closeAllPositions is called during graceful shutdown.  It closes every open
// position at whatever the last known price is.  In paper mode this is fine;
// in live mode the exchange handles the actual fill.
func closeAllPositions(riskMgr *risk.Manager, execEngine *execution.Engine, alertMgr *alerts.Manager) {
	positions := riskMgr.GetAllPositions()
	if len(positions) == 0 {
		return
	}

	log.Info().Int("count", len(positions)).Msg("closing all open positions on shutdown")

	for sym, pos := range positions {
		// Use the entry price as a fallback — in production we would query
		// the exchange for the current market price.
		exitPrice := pos.EntryPrice
		if pos.UnrealizedPnL != 0 {
			// Derive approximate current price from unrealized PnL.
			if pos.Side == "LONG" {
				exitPrice = pos.EntryPrice + pos.UnrealizedPnL/pos.Size
			} else {
				exitPrice = pos.EntryPrice - pos.UnrealizedPnL/pos.Size
			}
		}

		_, err := execEngine.ClosePosition(sym, pos.Side, exitPrice, pos.Size, "shutdown", strategy.SignalNone, "shutdown", pos.EntryPrice, pos.EntryTime)
		if err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("failed to close position on shutdown")
			continue
		}

		pnl, err := riskMgr.ClosePosition(sym, exitPrice)
		if err != nil {
			log.Error().Err(err).Str("symbol", sym).Msg("risk manager close on shutdown failed")
			continue
		}

		log.Info().
			Str("symbol", sym).
			Float64("pnl", pnl).
			Msg("position closed on shutdown")

		alertMgr.TradeClosed(sym, pos.Side, pos.EntryPrice, exitPrice, pos.Size, pnl, "shutdown")
	}
}

// saveStats dumps trade statistics to a JSON file.
func saveStats(engine *execution.Engine, strategyName string) {
	stats := engine.GetTradeStatsByStrategy("") // get all trades for this run

	// Create a map to hold the stats + metadata
	output := map[string]interface{}{
		"strategy":       strategyName,
		"timestamp":      time.Now().Format(time.RFC3339),
		"total_trades":   stats.TotalTrades,
		"winning_trades": stats.WinCount,
		"losing_trades":  stats.LossCount,
		"win_rate":       stats.WinRate * 100, // as percentage
		"total_pnl":      stats.NetPnL,
		"avg_pnl":        stats.AvgPnL,
		"profit_factor":  stats.ProfitFactor,
	}

	filename := fmt.Sprintf("stats_%s_%d.json", strategyName, time.Now().Unix())
	file, err := os.Create(filename)
	if err != nil {
		log.Error().Err(err).Msg("failed to create stats file")
		return
	}
	defer file.Close()

	encoder := json.NewEncoder(file)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(output); err != nil {
		log.Error().Err(err).Msg("failed to write stats to file")
		return
	}

	log.Info().Str("file", filename).Msg("saved strategy stats")
}

// strategyStats holds scraped metrics data
type strategyStats struct {
	Strategy      string
	TotalTrades   float64
	WinningTrades float64
	LosingTrades  float64
	WinRate       float64
	TotalPnL      float64
	ProfitFactor  float64
}

// compareStrategiesStats scrapes metrics from all running bots and returns a formatted comparison.
func compareStrategiesStats(engine *execution.Engine, strategyName string) (string, error) {
	// Define ports for known strategies
	ports := map[string]int{
		"trend_following": 9090,
		"market_making":   9091,
		"funding_arb":     9092,
	}

	var allStats []strategyStats

	for strat, port := range ports {
		data, err := scrapeMetrics(port)
		if err != nil {
			continue
		}
		data.Strategy = strat
		allStats = append(allStats, *data)
	}

	if len(allStats) == 0 {
		return "⚠️ No active strategies found (or metrics unscrapeable)", nil
	}

	// Sort by strategy name
	sort.Slice(allStats, func(i, j int) bool {
		return allStats[i].Strategy < allStats[j].Strategy
	})

	// Build comparison table (escape for Telegram MarkdownV2)
	var lines []string
	lines = append(lines, "*📊 Live Strategy Comparison*")
	lines = append(lines, "")

	for _, stats := range allStats {
		trades := int(stats.TotalTrades)
		wins := int(stats.WinningTrades)
		losses := int(stats.LosingTrades)

		// Calculate Win Rate if not provided or 0
		winRatePct := stats.WinRate * 100
		if stats.WinRate == 0 && trades > 0 {
			winRatePct = (float64(wins) / float64(trades)) * 100
		}

		pnlEmoji := "💰"
		if stats.TotalPnL < 0 {
			pnlEmoji = "📉"
		}

		avgPnL := 0.0
		if trades > 0 {
			avgPnL = stats.TotalPnL / float64(trades)
		}

		lines = append(lines, fmt.Sprintf("*%s*", escapeMarkdownV2Telegram(stats.Strategy)))
		lines = append(lines, fmt.Sprintf("  Trades: %d \\(Win: %d, Loss: %d\\)", trades, wins, losses))
		lines = append(lines, fmt.Sprintf("  Win Rate: %.1f%%", winRatePct))
		lines = append(lines, fmt.Sprintf("  %s Total PnL: $%.2f", pnlEmoji, stats.TotalPnL))
		lines = append(lines, fmt.Sprintf("  Avg PnL: $%.2f", avgPnL))
		if stats.ProfitFactor > 0 {
			lines = append(lines, fmt.Sprintf("  Profit Factor: %.2f", stats.ProfitFactor))
		}
		lines = append(lines, "")
	}

	return strings.Join(lines, "\n"), nil
}

// scrapeMetrics fetches prometheus metrics from the given port and parses key trading stats
func scrapeMetrics(port int) (*strategyStats, error) {
	url := fmt.Sprintf("http://localhost:%d/metrics", port)
	client := http.Client{Timeout: 500 * time.Millisecond}

	resp, err := client.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("bad status: %d", resp.StatusCode)
	}

	stats := &strategyStats{}
	scanner := bufio.NewScanner(resp.Body)

	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, "#") {
			continue
		}

		parts := strings.Fields(line)
		if len(parts) < 2 {
			continue
		}

		key := parts[0]
		valStr := parts[1]

		val, err := strconv.ParseFloat(valStr, 64)
		if err != nil {
			continue
		}

		// Match metric names from internal/metrics/prometheus.go
		switch key {
		case "trading_total_trades":
			stats.TotalTrades = val
		case "trading_winning_trades":
			stats.WinningTrades = val
		case "trading_losing_trades":
			stats.LosingTrades = val
		case "trading_realized_pnl":
			stats.TotalPnL = val
		case "trading_win_rate":
			stats.WinRate = val
		case "trading_profit_factor":
			stats.ProfitFactor = val
		}
	}

	if err := scanner.Err(); err != nil {
		return nil, err
	}

	return stats, nil
}

// escapeMarkdownV2Telegram escapes special characters for Telegram MarkdownV2 in comparison text.
func escapeMarkdownV2Telegram(s string) string {
	replacer := strings.NewReplacer(
		`\`, `\\`,
		`_`, `\_`,
		`*`, `\*`,
		`[`, `\[`,
		`]`, `\]`,
		`(`, `\(`,
		`)`, `\)`,
		`~`, `\~`,
		"`", "\\`",
		`>`, `\>`,
		`#`, `\#`,
		`+`, `\+`,
		`-`, `\-`,
		`=`, `\=`,
		`|`, `\|`,
		`{`, `\{`,
		`}`, `\}`,
		`.`, `\.`,
		`!`, `\!`,
	)
	return replacer.Replace(s)
}

// newExchangeClient creates an exchange.Client that connects via the central WS hub.
func newExchangeClient(cfg *config.Config) exchange.Client {
	log.Info().Str("hub_url", cfg.Exchange.HubURL).Msg("using WS hub for market data")
	return exchange.NewHubClient(cfg.Exchange.HubURL, cfg.Exchange.Testnet)
}
