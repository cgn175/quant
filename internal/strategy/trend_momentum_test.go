package strategy

import (
	"testing"

	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/stretchr/testify/assert"
)

func TestCalculateMomentumScores(t *testing.T) {
	symbols := []string{"BTCUSDT", "ETHUSDT", "SOLUSDT"}
	
	// Create test candles: BTC up 10%, ETH up 5%, SOL down 5%
	candlesMap := make(map[string][]exchange.Candle)
	
	// BTC: strong uptrend
	btcCandles := make([]exchange.Candle, 126) // 21 days * 6 candles
	for i := range btcCandles {
		btcCandles[i] = exchange.Candle{
			Close: 100.0 + float64(i)*0.1, // gradual increase
		}
	}
	candlesMap["BTCUSDT"] = btcCandles
	
	// ETH: moderate uptrend
	ethCandles := make([]exchange.Candle, 126)
	for i := range ethCandles {
		ethCandles[i] = exchange.Candle{
			Close: 100.0 + float64(i)*0.05, // slower increase
		}
	}
	candlesMap["ETHUSDT"] = ethCandles
	
	// SOL: downtrend
	solCandles := make([]exchange.Candle, 126)
	for i := range solCandles {
		solCandles[i] = exchange.Candle{
			Close: 100.0 - float64(i)*0.05, // decrease
		}
	}
	candlesMap["SOLUSDT"] = solCandles
	
	scores := CalculateMomentumScores(symbols, candlesMap, 21)
	
	// Verify we got 3 scores
	assert.Equal(t, 3, len(scores))
	
	// Verify all scores are calculated
	assert.NotEqual(t, 0.0, scores[0].Score)
	assert.NotEqual(t, 0.0, scores[1].Score)
	assert.NotEqual(t, 0.0, scores[2].Score)
	
	// Verify ranks are assigned (1, 2, 3)
	assert.Equal(t, 1, scores[0].Rank)
	assert.Equal(t, 2, scores[1].Rank)
	assert.Equal(t, 3, scores[2].Rank)
	
	// Verify scores are sorted descending
	assert.GreaterOrEqual(t, scores[0].Score, scores[1].Score)
	assert.GreaterOrEqual(t, scores[1].Score, scores[2].Score)
}

func TestCalculateVolatility(t *testing.T) {
	// Test with stable prices (low volatility)
	stableCandles := make([]exchange.Candle, 10)
	for i := range stableCandles {
		stableCandles[i] = exchange.Candle{Close: 100.0}
	}
	vol := calculateVolatility(stableCandles)
	assert.Equal(t, 0.0, vol)
	
	// Test with volatile prices
	volatileCandles := []exchange.Candle{
		{Close: 100.0},
		{Close: 110.0},
		{Close: 95.0},
		{Close: 105.0},
		{Close: 90.0},
	}
	vol = calculateVolatility(volatileCandles)
	assert.Greater(t, vol, 0.0)
}

func TestIsTopMomentum(t *testing.T) {
	cfg := DefaultTrendConfig()
	cfg.MomentumFilter.Enabled = true
	cfg.MomentumFilter.TopPct = 0.5 // top 50%
	
	ts := NewTrendStrategy(cfg)
	
	symbols := []string{"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"}
	candlesMap := make(map[string][]exchange.Candle)
	
	// Create candles with different momentum
	for _, symbol := range symbols {
		candles := make([]exchange.Candle, 126)
		var increment float64
		switch symbol {
		case "BTCUSDT":
			increment = 0.2 // highest
		case "ETHUSDT":
			increment = 0.1 // second
		case "SOLUSDT":
			increment = 0.05 // third
		case "BNBUSDT":
			increment = 0.01 // lowest
		}
		
		for i := range candles {
			candles[i] = exchange.Candle{
				Close: 100.0 + float64(i)*increment,
			}
		}
		candlesMap[symbol] = candles
	}
	
	// Top 50% should be top 2 symbols (whichever they are)
	scores := CalculateMomentumScores(symbols, candlesMap, 21)
	top1 := scores[0].Symbol
	top2 := scores[1].Symbol
	bottom1 := scores[2].Symbol
	bottom2 := scores[3].Symbol
	
	assert.True(t, ts.IsTopMomentum(top1, symbols, candlesMap))
	assert.True(t, ts.IsTopMomentum(top2, symbols, candlesMap))
	assert.False(t, ts.IsTopMomentum(bottom1, symbols, candlesMap))
	assert.False(t, ts.IsTopMomentum(bottom2, symbols, candlesMap))
}

func TestIsTopMomentum_Disabled(t *testing.T) {
	cfg := DefaultTrendConfig()
	cfg.MomentumFilter.Enabled = false // disabled
	
	ts := NewTrendStrategy(cfg)
	
	// When disabled, all symbols should pass
	symbols := []string{"BTCUSDT"}
	candlesMap := make(map[string][]exchange.Candle)
	candlesMap["BTCUSDT"] = make([]exchange.Candle, 126)
	
	assert.True(t, ts.IsTopMomentum("BTCUSDT", symbols, candlesMap))
}

func TestGetMomentumRank(t *testing.T) {
	cfg := DefaultTrendConfig()
	ts := NewTrendStrategy(cfg)
	
	symbols := []string{"BTCUSDT", "ETHUSDT"}
	candlesMap := make(map[string][]exchange.Candle)
	
	// BTC higher momentum
	btcCandles := make([]exchange.Candle, 126)
	for i := range btcCandles {
		btcCandles[i] = exchange.Candle{Close: 100.0 + float64(i)*0.2}
	}
	candlesMap["BTCUSDT"] = btcCandles
	
	// ETH lower momentum
	ethCandles := make([]exchange.Candle, 126)
	for i := range ethCandles {
		ethCandles[i] = exchange.Candle{Close: 100.0 + float64(i)*0.1}
	}
	candlesMap["ETHUSDT"] = ethCandles
	
	// Just verify both get valid ranks (1 or 2)
	btcRank := ts.GetMomentumRank("BTCUSDT", symbols, candlesMap)
	ethRank := ts.GetMomentumRank("ETHUSDT", symbols, candlesMap)
	
	assert.True(t, btcRank == 1 || btcRank == 2)
	assert.True(t, ethRank == 1 || ethRank == 2)
	assert.NotEqual(t, btcRank, ethRank) // They should have different ranks
}
