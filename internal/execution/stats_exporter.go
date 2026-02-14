package execution

import (
	"encoding/json"
	"fmt"
	"os"
	"time"
)

// StatsSnapshot represents a point-in-time snapshot of trading performance.
type StatsSnapshot struct {
	Strategy      string    `json:"strategy"`
	StartTime     time.Time `json:"start_time"`
	EndTime       time.Time `json:"end_time"`
	TotalTrades   int       `json:"total_trades"`
	WinningTrades int       `json:"winning_trades"`
	LosingTrades  int       `json:"losing_trades"`
	WinRate       float64   `json:"win_rate"`
	NetPnL        float64   `json:"net_pnl"`
	AvgTradePnL   float64   `json:"avg_trade_pnl"`
	ProfitFactor  float64   `json:"profit_factor"`
}

// ExportStats writes trade statistics to a JSON file.
// Filename format: stats_{strategy}_{timestamp}.json
func (e *Engine) ExportStats(strategy string, startTime time.Time) error {
	stats := e.GetTradeStatsByStrategy(strategy)

	snapshot := StatsSnapshot{
		Strategy:      strategy,
		StartTime:     startTime,
		EndTime:       time.Now(),
		TotalTrades:   stats.TotalTrades,
		WinningTrades: stats.WinCount,
		LosingTrades:  stats.LossCount,
		WinRate:       stats.WinRate,
		NetPnL:        stats.NetPnL,
		AvgTradePnL:   stats.AvgPnL,
		ProfitFactor:  stats.ProfitFactor,
	}

	filename := fmt.Sprintf("stats_%s_%s.json", strategy, time.Now().Format("20060102_150405"))
	data, err := json.MarshalIndent(snapshot, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal stats: %w", err)
	}

	if err := os.WriteFile(filename, data, 0644); err != nil {
		return fmt.Errorf("failed to write stats file: %w", err)
	}

	return nil
}
