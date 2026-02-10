package sentiment

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
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

	// Fetch insights from the insights endpoint
	ctx := context.Background()
	insights, err := s.client.fetchInsightsFromAPI(ctx, symbol)
	
	var reasoning []string
	var signal string
	var suggestedAction string
	
	if err == nil && insights != nil {
		if rec, ok := insights["recommendation"].(map[string]interface{}); ok {
			if r, ok := rec["reasoning"].([]interface{}); ok {
				for _, item := range r {
					if str, ok := item.(string); ok {
						reasoning = append(reasoning, str)
					}
				}
			}
			if s, ok := rec["signal"].(string); ok {
				signal = s
			}
			if sa, ok := rec["suggested_action"].(string); ok {
				suggestedAction = sa
			}
		}
	}
	
	// Fallback if no insights available
	if len(reasoning) == 0 {
		if sentimentData.Score24h > 0.3 {
			signal = "bullish"
			suggestedAction = "Consider buying"
			reasoning = []string{fmt.Sprintf("Positive sentiment score: %.2f", sentimentData.Score24h)}
		} else if sentimentData.Score24h < -0.3 {
			signal = "bearish"
			suggestedAction = "Consider selling"
			reasoning = []string{fmt.Sprintf("Negative sentiment score: %.2f", sentimentData.Score24h)}
		} else {
			signal = "neutral"
			suggestedAction = "Hold position"
			reasoning = []string{fmt.Sprintf("Neutral sentiment score: %.2f", sentimentData.Score24h)}
		}
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
		"reasoning":       reasoning,
		"signal":          signal,
		"suggested_action": suggestedAction,
	}
}

// fetchInsightsFromAPI fetches insights from the sentiment service API
func (c *Client) fetchInsightsFromAPI(ctx context.Context, symbol string) (map[string]interface{}, error) {
	url := fmt.Sprintf("%s/insights/%s", c.baseURL, symbol)
	
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return nil, err
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected status code: %d", resp.StatusCode)
	}

	var result map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, err
	}

	return result, nil
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
