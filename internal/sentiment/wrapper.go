package sentiment

import (
	"context"
	"sync"
)

// SentimentDataWrapper wraps the sentiment client to implement alerts.SentimentProvider
type SentimentDataWrapper struct {
	client  *Client
	symbols []string
	mu      sync.RWMutex
}

// NewSentimentDataWrapper creates a new sentiment data wrapper
func NewSentimentDataWrapper(client *Client, symbols []string) *SentimentDataWrapper {
	return &SentimentDataWrapper{
		client:  client,
		symbols: symbols,
	}
}

// GetSymbols returns the list of configured symbols
func (s *SentimentDataWrapper) GetSymbols() []string {
	s.mu.RLock()
	defer s.mu.RUnlock()

	symbols := make([]string, len(s.symbols))
	copy(symbols, s.symbols)
	return symbols
}

// GetSentimentData returns current sentiment data for a symbol
func (s *SentimentDataWrapper) GetSentimentData(symbol string) map[string]interface{} {
	sentimentData := s.client.Get(symbol)
	if sentimentData == nil {
		return nil
	}

	// Convert to generic map
	return map[string]interface{}{
		"symbol":          sentimentData.Symbol,
		"score_1h":        sentimentData.Score1h,
		"score_24h":       sentimentData.Score24h,
		"mentions":        sentimentData.Mentions,
		"mentions_zscore": sentimentData.MentionsZScore,
		"velocity":        sentimentData.Velocity,
		"sources":         sentimentData.Sources,
		"timestamp":       sentimentData.Timestamp,
	}
}

// GetHistoricalData returns historical sentiment data for a symbol
func (s *SentimentDataWrapper) GetHistoricalData(ctx context.Context, symbol string, days int, period string) ([]map[string]interface{}, error) {
	history, err := s.client.FetchHistory(ctx, symbol, days, period)
	if err != nil {
		return nil, err
	}

	if history == nil || len(history.Data) == 0 {
		return nil, nil
	}

	result := make([]map[string]interface{}, len(history.Data))
	for i, h := range history.Data {
		result[i] = map[string]interface{}{
			"timestamp":      h.Timestamp,
			"date":           h.Date,
			"score_positive": h.ScorePositive,
			"score_negative": h.ScoreNegative,
			"score_neutral":  h.ScoreNeutral,
			"mentions_count": h.MentionsCount,
			"sources":        h.Sources,
		}
	}

	return result, nil
}
