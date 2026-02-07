package backtest

import (
	"fmt"
	"sort"
	"sync"
	"time"

	"github.com/cgn175/quant-bot/internal/features"
	"github.com/cgn175/quant-bot/internal/model"
	"github.com/cgn175/quant-bot/internal/risk"
	"github.com/cgn175/quant-bot/internal/strategy"
)

// Bar represents a single OHLCV candle
type Bar struct {
	Symbol    string
	Timestamp time.Time
	Open      float64
	High      float64
	Low       float64
	Close     float64
	Volume    float64
}

// Backtest engine replays historical data and simulates trading
type Engine struct {
	mu              sync.RWMutex
	bars            map[string][]*Bar          // symbol -> sorted bars
	featureBuilder  *features.Builder          // for computing TA indicators
	strategyEngine  *strategy.Strategy         // signal generation
	riskManager     *risk.Manager              // position sizing + risk
	predictor       *model.Predictor           // ML model
	symbolOrder     []string                   // for deterministic processing
	currentIdx      map[string]int             // current index per symbol
	trades          []*Trade                   // closed trades
	openPositions   map[string]*OpenPosition   // open positions during backtest
	executionConfig ExecutionConfig
	stats           BacktestStats
}

// ExecutionConfig controls how orders are simulated
type ExecutionConfig struct {
	FeePercent float64 // 0.025 = 0.025%
	SlippageBP float64 // 10 = 10 basis points
	Mode       string  // "paper" or "market"
}

// OpenPosition tracks an open position during backtest
type OpenPosition struct {
	Symbol     string
	Side       string    // "LONG" or "SHORT"
	EntryPrice float64
	EntryTime  time.Time
	EntryBar   int
	Size       float64
	StopLoss   float64
	TakeProfit float64
}

// Trade is a closed trade result
type Trade struct {
	Symbol     string
	Side       string
	EntryPrice float64
	EntryTime  time.Time
	ExitPrice  float64
	ExitTime   time.Time
	Size       float64
	GrossPnL   float64
	NetPnL     float64
	ExitReason string
}

// BacktestStats summarizes backtest results
type BacktestStats struct {
	StartTime          time.Time
	EndTime            time.Time
	InitialEquity      float64
	FinalEquity        float64
	TotalTrades        int
	WinningTrades      int
	LosingTrades       int
	WinRate            float64
	ProfitFactor       float64
	GrossPnL           float64
	NetPnL             float64
	AvgPnL             float64
	MaxDrawdown        float64
	SharpeRatio        float64
	TotalDaysTraded    int
}

// NewEngine creates a new backtest engine
func NewEngine(
	strategyEngine *strategy.Strategy,
	riskManager *risk.Manager,
	predictor *model.Predictor,
	featureBuilder *features.Builder,
	execConfig ExecutionConfig,
) *Engine {
	return &Engine{
		bars:            make(map[string][]*Bar),
		featureBuilder:  featureBuilder,
		strategyEngine:  strategyEngine,
		riskManager:     riskManager,
		predictor:       predictor,
		currentIdx:      make(map[string]int),
		openPositions:   make(map[string]*OpenPosition),
		executionConfig: execConfig,
		trades:          make([]*Trade, 0),
	}
}

// AddBars adds historical candles for a symbol
func (e *Engine) AddBars(symbol string, bars []*Bar) error {
	if len(bars) == 0 {
		return fmt.Errorf("no bars provided")
	}

	e.mu.Lock()
	defer e.mu.Unlock()

	// Sort bars by timestamp
	sortedBars := make([]*Bar, len(bars))
	copy(sortedBars, bars)
	sort.Slice(sortedBars, func(i, j int) bool {
		return sortedBars[i].Timestamp.Before(sortedBars[j].Timestamp)
	})

	e.bars[symbol] = sortedBars
	e.currentIdx[symbol] = 0
	e.symbolOrder = append(e.symbolOrder, symbol)

	return nil
}

// Run executes the backtest
func (e *Engine) Run() (*BacktestStats, error) {
	e.mu.Lock()

	if len(e.bars) == 0 {
		e.mu.Unlock()
		return nil, fmt.Errorf("no bars loaded")
	}

	// Find date range
	minTime := time.Now()
	maxTime := time.Time{}
	maxBarCount := 0

	for _, bars := range e.bars {
		if len(bars) > 0 {
			if bars[0].Timestamp.Before(minTime) {
				minTime = bars[0].Timestamp
			}
			if bars[len(bars)-1].Timestamp.After(maxTime) {
				maxTime = bars[len(bars)-1].Timestamp
			}
			if len(bars) > maxBarCount {
				maxBarCount = len(bars)
			}
		}
	}

	e.stats.StartTime = minTime
	e.stats.EndTime = maxTime
	e.stats.InitialEquity = e.riskManager.GetEquity()

	e.mu.Unlock()

	// Process each bar in time order
	for barNum := 0; barNum < maxBarCount; barNum++ {
		e.mu.Lock()

		// Process signals for all symbols at this bar
		for _, symbol := range e.symbolOrder {
			bars := e.bars[symbol]
			if barNum >= len(bars) {
				continue
			}

			bar := bars[barNum]

			// Check for exit conditions (stop loss / take profit)
			e.checkExitConditions(symbol, bar)

			// Only generate new signals if we have enough history
			if barNum < 20 {
				continue // Skip first 20 bars for indicator warmup
			}

			// Build feature vector
			fv := e.buildFeatureVector(symbol, bar, barNum, bars)
			if fv == nil {
				continue
			}

			// Get model prediction
			pred, err := e.predictor.Predict(fv.ToArray())
			if err != nil {
				continue
			}

			// Evaluate signal
			signal := e.strategyEngine.Evaluate(fv, pred)
			if signal == nil {
				continue
			}

			// Execute signal
			e.executeSignal(signal, bar)
		}

		e.mu.Unlock()
	}

	// Close any remaining open positions at last bar
	e.mu.Lock()

	for symbol, pos := range e.openPositions {
		bars := e.bars[symbol]
		if len(bars) > 0 {
			lastBar := bars[len(bars)-1]
			e.closeTrade(symbol, pos, lastBar.Close, lastBar.Timestamp, "end_of_data")
		}
	}

	e.stats.FinalEquity = e.riskManager.GetEquity()
	e.computeStats()

	e.mu.Unlock()

	return &e.stats, nil
}

// checkExitConditions checks if any open position should be closed
func (e *Engine) checkExitConditions(symbol string, bar *Bar) {
	pos, exists := e.openPositions[symbol]
	if !exists {
		return
	}

	// Check stop loss
	if pos.Side == "LONG" && bar.Low <= pos.StopLoss {
		e.closeTrade(symbol, pos, pos.StopLoss, bar.Timestamp, "stop_loss")
		return
	}
	if pos.Side == "SHORT" && bar.High >= pos.StopLoss {
		e.closeTrade(symbol, pos, pos.StopLoss, bar.Timestamp, "stop_loss")
		return
	}

	// Check take profit
	if pos.Side == "LONG" && bar.High >= pos.TakeProfit {
		e.closeTrade(symbol, pos, pos.TakeProfit, bar.Timestamp, "take_profit")
		return
	}
	if pos.Side == "SHORT" && bar.Low <= pos.TakeProfit {
		e.closeTrade(symbol, pos, pos.TakeProfit, bar.Timestamp, "take_profit")
		return
	}
}

// executeSignal processes a trading signal
func (e *Engine) executeSignal(signal *strategy.Signal, bar *Bar) {
	symbol := signal.Symbol

	// If already have a position, don't open another
	if _, exists := e.openPositions[symbol]; exists {
		return
	}

	// Only process entry signals
	if signal.Type != strategy.SignalLong && signal.Type != strategy.SignalShort {
		return
	}

	// Calculate position size
	var side string
	if signal.Type == strategy.SignalLong {
		side = "LONG"
	} else {
		side = "SHORT"
	}

	sizeMultiplier := e.strategyEngine.ShouldReduceSize(signal.Features)
	size, err := e.riskManager.CalculatePositionSize(symbol, bar.Close, signal.StopLoss, sizeMultiplier)
	if err != nil {
		return
	}

	if size <= 0 {
		return
	}

	// Open position
	e.openPositions[symbol] = &OpenPosition{
		Symbol:     symbol,
		Side:       side,
		EntryPrice: bar.Close,
		EntryTime:  bar.Timestamp,
		Size:       size,
		StopLoss:   signal.StopLoss,
		TakeProfit: signal.TakeProfit,
	}

	// Register in risk manager
	riskAmount := bar.Close * size * (e.executionConfig.FeePercent / 100.0)
	e.riskManager.OpenPosition(symbol, side, bar.Close, size, signal.StopLoss, signal.TakeProfit, riskAmount)
}

// closeTrade closes an open position and records trade result
func (e *Engine) closeTrade(symbol string, pos *OpenPosition, exitPrice float64, exitTime time.Time, reason string) {
	if pos == nil {
		return
	}

	// Calculate fees and slippage
	entryFees := pos.EntryPrice * pos.Size * (e.executionConfig.FeePercent / 100.0)
	exitFees := exitPrice * pos.Size * (e.executionConfig.FeePercent / 100.0)
	exitSlippage := exitPrice * pos.Size * (e.executionConfig.SlippageBP / 10000.0)

	// Calculate PnL
	var grossPnL float64
	if pos.Side == "LONG" {
		grossPnL = (exitPrice - pos.EntryPrice) * pos.Size
	} else {
		grossPnL = (pos.EntryPrice - exitPrice) * pos.Size
	}

	netPnL := grossPnL - entryFees - exitFees - exitSlippage

	trade := &Trade{
		Symbol:     symbol,
		Side:       pos.Side,
		EntryPrice: pos.EntryPrice,
		EntryTime:  pos.EntryTime,
		ExitPrice:  exitPrice,
		ExitTime:   exitTime,
		Size:       pos.Size,
		GrossPnL:   grossPnL,
		NetPnL:     netPnL,
		ExitReason: reason,
	}

	e.trades = append(e.trades, trade)

	// Update risk manager
	e.riskManager.ClosePosition(symbol, exitPrice)

	// Remove from open positions
	delete(e.openPositions, symbol)
}

// buildFeatureVector constructs a feature vector for the current bar
func (e *Engine) buildFeatureVector(symbol string, bar *Bar, barNum int, bars []*Bar) *features.FeatureVector {
	if e.featureBuilder == nil {
		return nil
	}

	// For now, create a minimal feature vector
	// In production, this would use the featureBuilder to compute indicators
	fv := &features.FeatureVector{
		Symbol:           symbol,
		Timestamp:        bar.Timestamp,
		Close:            bar.Close,
		Open:             bar.Open,
		High:             bar.High,
		Low:              bar.Low,
		Volume:           bar.Volume,
		VolumeRatio:      1.0, // placeholder
		SentimentScore1h: 0.0, // placeholder (would come from historical sentiment data)
		SentimentScore24h: 0.0,
	}

	// Compute basic indicators
	if barNum >= 20 {
		// EMA 5
		fv.EMA5 = e.computeEMA(bars, barNum, 5)
		fv.EMA9 = e.computeEMA(bars, barNum, 9)
		fv.EMA21 = e.computeEMA(bars, barNum, 21)
		fv.EMA50 = e.computeEMA(bars, barNum, 50)
	}

	return fv
}

// computeEMA computes exponential moving average
func (e *Engine) computeEMA(bars []*Bar, barNum int, period int) float64 {
	if barNum < period-1 {
		return 0
	}

	multiplier := 2.0 / float64(period+1)
	var sma float64
	for i := barNum - period + 1; i <= barNum; i++ {
		sma += bars[i].Close
	}
	sma /= float64(period)

	ema := sma
	for i := barNum - period + 2; i <= barNum; i++ {
		ema = bars[i].Close*multiplier + ema*(1-multiplier)
	}
	return ema
}

// computeStats computes final backtest statistics
func (e *Engine) computeStats() {
	if len(e.trades) == 0 {
		e.stats.TotalTrades = 0
		e.stats.NetPnL = 0
		e.stats.GrossPnL = 0
		return
	}

	e.stats.TotalTrades = len(e.trades)

	for _, trade := range e.trades {
		e.stats.GrossPnL += trade.GrossPnL
		e.stats.NetPnL += trade.NetPnL

		if trade.NetPnL > 0 {
			e.stats.WinningTrades++
		} else if trade.NetPnL < 0 {
			e.stats.LosingTrades++
		}
	}

	e.stats.WinRate = float64(e.stats.WinningTrades) / float64(e.stats.TotalTrades)

	if e.stats.LosingTrades > 0 {
		totalWins := 0.0
		totalLosses := 0.0
		for _, trade := range e.trades {
			if trade.NetPnL > 0 {
				totalWins += trade.NetPnL
			} else if trade.NetPnL < 0 {
				totalLosses -= trade.NetPnL
			}
		}
		if totalLosses > 0 {
			e.stats.ProfitFactor = totalWins / totalLosses
		}
	}

	if e.stats.TotalTrades > 0 {
		e.stats.AvgPnL = e.stats.NetPnL / float64(e.stats.TotalTrades)
	}

	// Compute max drawdown
	e.stats.MaxDrawdown = e.computeMaxDrawdown()

	// Days traded
	if !e.stats.StartTime.IsZero() && !e.stats.EndTime.IsZero() {
		e.stats.TotalDaysTraded = int(e.stats.EndTime.Sub(e.stats.StartTime).Hours() / 24)
	}
}

// computeMaxDrawdown calculates max drawdown from peak equity
func (e *Engine) computeMaxDrawdown() float64 {
	if len(e.trades) == 0 {
		return 0
	}

	equity := e.stats.InitialEquity
	peakEquity := equity
	maxDD := 0.0

	for _, trade := range e.trades {
		equity += trade.NetPnL
		if equity > peakEquity {
			peakEquity = equity
		}
		dd := (peakEquity - equity) / peakEquity
		if dd > maxDD {
			maxDD = dd
		}
	}

	return maxDD
}

// GetTrades returns all closed trades
func (e *Engine) GetTrades() []*Trade {
	e.mu.RLock()
	defer e.mu.RUnlock()

	result := make([]*Trade, len(e.trades))
	copy(result, e.trades)
	return result
}

// GetStats returns backtest statistics
func (e *Engine) GetStats() BacktestStats {
	e.mu.RLock()
	defer e.mu.RUnlock()
	return e.stats
}
