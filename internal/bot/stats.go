package bot

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/rs/zerolog/log"

	"github.com/cgn175/quant-bot/internal/execution"
)

// StrategyStats holds scraped metrics data
type StrategyStats struct {
	Strategy      string
	TotalTrades   float64
	WinningTrades float64
	LosingTrades  float64
	WinRate       float64
	TotalPnL      float64
	ProfitFactor  float64
}

// saveStats dumps trade statistics to a JSON file.
func saveStats(engine *execution.Engine, strategyName string) {
	stats := engine.GetTradeStatsByStrategy("") // get all trades for this run

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

// CompareStrategiesStats scrapes metrics from all running bots and returns a formatted comparison.
func CompareStrategiesStats(engine *execution.Engine, strategyName string) (string, error) {
	ports := map[string]int{
		"trend_following": 9090,
		"market_making":   9091,
		"funding_arb":     9092,
	}

	var allStats []StrategyStats

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

	sort.Slice(allStats, func(i, j int) bool {
		return allStats[i].Strategy < allStats[j].Strategy
	})

	var lines []string
	lines = append(lines, "*📊 Live Strategy Comparison*")
	lines = append(lines, "")

	for _, stats := range allStats {
		trades := int(stats.TotalTrades)
		wins := int(stats.WinningTrades)
		losses := int(stats.LosingTrades)

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
func scrapeMetrics(port int) (*StrategyStats, error) {
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

	stats := &StrategyStats{}
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

// escapeMarkdownV2Telegram escapes special characters for Telegram MarkdownV2.
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
