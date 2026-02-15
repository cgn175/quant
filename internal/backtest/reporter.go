package backtest

import (
	"fmt"
	"sort"
	"time"
)

// Reporter generates backtest reports
type Reporter struct {
	stats  *BacktestStats
	trades []*Trade
}

// NewReporter creates a new backtest reporter
func NewReporter(stats *BacktestStats, trades []*Trade) *Reporter {
	return &Reporter{
		stats:  stats,
		trades: trades,
	}
}

// Summary returns a string summary of the backtest results
func (r *Reporter) Summary() string {
	return fmt.Sprintf(`
=== BACKTEST RESULTS ===
Period:          %s to %s (%d days)
Initial Equity:  $%.2f
Final Equity:    $%.2f
Net PnL:         $%.2f (%.2f%%)
Gross PnL:       $%.2f

--- Performance ---
CAGR:            %.2f%%
Sharpe Ratio:    %.2f
Sortino Ratio:   %.2f
Calmar Ratio:    %.2f
Max Drawdown:    %.2f%%

--- Trading ---
Total Trades:    %d
Winning Trades:  %d
Losing Trades:   %d
Win Rate:        %.2f%%
Profit Factor:   %.2f
Avg Winner:      $%.2f
Avg Loser:       $%.2f
Win/Loss Ratio:  %.2f
Expectancy:      $%.2f (%.3f%%)
Max Consec Losses: %d

--- Costs ---
Total Fees:      $%.2f
========================
`,
		r.stats.StartTime.Format("2006-01-02"),
		r.stats.EndTime.Format("2006-01-02"),
		r.stats.TotalDaysTraded,
		r.stats.InitialEquity,
		r.stats.FinalEquity,
		r.stats.NetPnL,
		((r.stats.FinalEquity-r.stats.InitialEquity)/r.stats.InitialEquity)*100,
		r.stats.GrossPnL,
		r.stats.CAGR*100,
		r.stats.SharpeRatio,
		r.stats.SortinoRatio,
		r.stats.CalmarRatio,
		r.stats.MaxDrawdown*100,
		r.stats.TotalTrades,
		r.stats.WinningTrades,
		r.stats.LosingTrades,
		r.stats.WinRate*100,
		r.stats.ProfitFactor,
		r.stats.AvgWin,
		r.stats.AvgLoss,
		r.stats.AvgWinLossRatio,
		r.stats.Expectancy,
		r.stats.ExpectancyPct,
		r.stats.MaxConsecLosses,
		r.stats.TotalFees,
	)
}

// TradeLog returns a formatted list of all trades
func (r *Reporter) TradeLog() string {
	if len(r.trades) == 0 {
		return "No trades executed.\n"
	}

	output := fmt.Sprintf("=== TRADE LOG (%d trades) ===\n", len(r.trades))
	output += fmt.Sprintf("%-10s %-6s %-12s %-10s %-12s %-10s %-12s %s\n",
		"Symbol", "Side", "Entry", "Entry Price", "Exit Price", "Size", "PnL", "Exit Reason")
	output += fmt.Sprintf("%s\n", "-------------------------------"+
		"-------------------------------"+
		"---------")

	for i, trade := range r.trades {
		output += fmt.Sprintf("%-10s %-6s %-12s $%-9.2f $%-11.2f %-10.4f $%-11.2f %s\n",
			trade.Symbol,
			trade.Side,
			trade.EntryTime.Format("2006-01-02"),
			trade.EntryPrice,
			trade.ExitPrice,
			trade.Size,
			trade.NetPnL,
			trade.ExitReason,
		)

		// Print every 20 trades
		if (i+1)%20 == 0 {
			output += "\n"
		}
	}

	return output
}

// MonthlyReturns returns monthly aggregated returns
func (r *Reporter) MonthlyReturns() string {
	if len(r.trades) == 0 {
		return "No trades to aggregate.\n"
	}

	// Group trades by month
	monthlyPnL := make(map[string]float64)
	monthlyCount := make(map[string]int)

	for _, trade := range r.trades {
		month := trade.ExitTime.Format("2006-01")
		monthlyPnL[month] += trade.NetPnL
		monthlyCount[month]++
	}

	// Sort months
	months := make([]string, 0, len(monthlyPnL))
	for month := range monthlyPnL {
		months = append(months, month)
	}
	sort.Strings(months)

	output := "=== MONTHLY RETURNS ===\n"
	output += fmt.Sprintf("%-12s %-12s %-10s\n", "Month", "PnL", "Trades")
	output += fmt.Sprintf("%s\n", "-------------------------------")

	totalPnL := 0.0
	for _, month := range months {
		pnl := monthlyPnL[month]
		count := monthlyCount[month]
		totalPnL += pnl
		output += fmt.Sprintf("%-12s $%-11.2f %-10d\n", month, pnl, count)
	}

	output += fmt.Sprintf("%s\n", "-------------------------------")
	output += fmt.Sprintf("%-12s $%-11.2f\n", "Total", totalPnL)

	return output
}

// DrawdownAnalysis provides drawdown details
func (r *Reporter) DrawdownAnalysis() string {
	if len(r.trades) == 0 {
		return "No trades to analyze.\n"
	}

	output := "=== DRAWDOWN PERIODS ===\n"
	output += fmt.Sprintf("%-20s %-20s %-15s\n", "Period", "Drawdown", "Recovery")
	output += fmt.Sprintf("%s\n", "--------------------------------------")

	equity := float64(r.stats.InitialEquity)
	peakEquity := equity
	drawnDownTime := time.Time{}
	maxDD := 0.0

	for _, trade := range r.trades {
		equity += trade.NetPnL

		if equity > peakEquity {
			if drawnDownTime != (time.Time{}) && maxDD > 0 {
				output += fmt.Sprintf("%-20s %-15.2f%% %-15s\n",
					drawnDownTime.Format("2006-01-02"),
					maxDD*100,
					trade.ExitTime.Format("2006-01-02"),
				)
			}
			peakEquity = equity
			drawnDownTime = time.Time{}
			maxDD = 0
		}

		currentDD := (peakEquity - equity) / peakEquity
		if currentDD > 0 {
			if drawnDownTime == (time.Time{}) {
				drawnDownTime = trade.ExitTime
			}
			if currentDD > maxDD {
				maxDD = currentDD
			}
		}
	}

	if drawnDownTime != (time.Time{}) && maxDD > 0 {
		output += fmt.Sprintf("%-20s %-15.2f%% (ongoing)\n",
			drawnDownTime.Format("2006-01-02"),
			maxDD*100,
		)
	}

	return output
}

// SymbolStats returns statistics broken down by symbol
func (r *Reporter) SymbolStats() string {
	if len(r.trades) == 0 {
		return "No trades to analyze.\n"
	}

	// Group by symbol
	symbolTrades := make(map[string][]*Trade)
	for _, trade := range r.trades {
		symbolTrades[trade.Symbol] = append(symbolTrades[trade.Symbol], trade)
	}

	output := "=== SYMBOL STATISTICS ===\n"
	output += fmt.Sprintf("%-10s %-8s %-8s %-10s %-12s %s\n",
		"Symbol", "Trades", "Win Rate", "PnL", "Avg PnL", "Profit Factor")
	output += fmt.Sprintf("%s\n", "----------------------------------------------")

	symbols := make([]string, 0, len(symbolTrades))
	for sym := range symbolTrades {
		symbols = append(symbols, sym)
	}
	sort.Strings(symbols)

	for _, symbol := range symbols {
		trades := symbolTrades[symbol]
		count := len(trades)
		wins := 0
		pnl := 0.0
		totalWins := 0.0
		totalLosses := 0.0

		for _, t := range trades {
			pnl += t.NetPnL
			if t.NetPnL > 0 {
				wins++
				totalWins += t.NetPnL
			} else if t.NetPnL < 0 {
				totalLosses -= t.NetPnL
			}
		}

		winRate := float64(wins) / float64(count)
		avgPnL := pnl / float64(count)
		pf := 0.0
		if totalLosses > 0 {
			pf = totalWins / totalLosses
		}

		output += fmt.Sprintf("%-10s %-8d %-8.1f%% $%-11.2f $%-11.2f %.2f\n",
			symbol, count, winRate*100, pnl, avgPnL, pf)
	}

	return output
}
