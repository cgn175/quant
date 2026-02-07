package data

import (
	"sync"
	"time"

	"github.com/cgn175/quant-bot/internal/exchange"
)

type CandleStore struct {
	mu      sync.RWMutex
	candles map[string][]exchange.Candle
	maxSize int
}

func NewCandleStore(maxSize int) *CandleStore {
	return &CandleStore{
		candles: make(map[string][]exchange.Candle),
		maxSize: maxSize,
	}
}

func (s *CandleStore) Add(candle exchange.Candle) {
	s.mu.Lock()
	defer s.mu.Unlock()

	key := candle.Symbol
	candles := s.candles[key]

	if len(candles) > 0 {
		last := candles[len(candles)-1]
		if last.OpenTime.Equal(candle.OpenTime) {
			candles[len(candles)-1] = candle
			s.candles[key] = candles
			return
		}
	}

	candles = append(candles, candle)

	if len(candles) > s.maxSize {
		candles = candles[len(candles)-s.maxSize:]
	}

	s.candles[key] = candles
}

func (s *CandleStore) Get(symbol string, n int) []exchange.Candle {
	s.mu.RLock()
	defer s.mu.RUnlock()

	candles := s.candles[symbol]
	if len(candles) == 0 {
		return nil
	}

	if n >= len(candles) {
		result := make([]exchange.Candle, len(candles))
		copy(result, candles)
		return result
	}

	result := make([]exchange.Candle, n)
	copy(result, candles[len(candles)-n:])
	return result
}

func (s *CandleStore) GetAll(symbol string) []exchange.Candle {
	s.mu.RLock()
	defer s.mu.RUnlock()

	candles := s.candles[symbol]
	result := make([]exchange.Candle, len(candles))
	copy(result, candles)
	return result
}

func (s *CandleStore) GetSince(symbol string, since time.Time) []exchange.Candle {
	s.mu.RLock()
	defer s.mu.RUnlock()

	candles := s.candles[symbol]
	var result []exchange.Candle

	for _, c := range candles {
		if !c.OpenTime.Before(since) {
			result = append(result, c)
		}
	}

	return result
}

func (s *CandleStore) Len(symbol string) int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return len(s.candles[symbol])
}

func (s *CandleStore) Symbols() []string {
	s.mu.RLock()
	defer s.mu.RUnlock()

	symbols := make([]string, 0, len(s.candles))
	for k := range s.candles {
		symbols = append(symbols, k)
	}
	return symbols
}
