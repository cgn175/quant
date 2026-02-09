package sentiment

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"sync"
	"time"

	"github.com/rs/zerolog/log"
)

type SentimentData struct {
	Symbol         string    `json:"symbol"`
	Score1h        float64   `json:"score_1h"`
	Score24h       float64   `json:"score_24h"`
	Mentions       int       `json:"mentions"`
	MentionsZScore float64   `json:"mentions_zscore"`
	Velocity       float64   `json:"velocity"`
	Sources        []string  `json:"sources"`
	Timestamp      time.Time `json:"timestamp"`
}

type HistoricalSentiment struct {
	Timestamp     time.Time `json:"timestamp,omitempty"`
	Date          string    `json:"date,omitempty"`
	ScorePositive float64   `json:"score_positive"`
	ScoreNegative float64   `json:"score_negative"`
	ScoreNeutral  float64   `json:"score_neutral"`
	MentionsCount int       `json:"mentions_count"`
	Sources       []string  `json:"sources"`
}

type HistoricalResponse struct {
	Symbol string                `json:"symbol"`
	Data   []HistoricalSentiment `json:"data"`
	Period string                `json:"period"`
}

type Client struct {
	baseURL    string
	httpClient *http.Client
	cache      map[string]*SentimentData
	mu         sync.RWMutex
	interval   time.Duration
	done       chan struct{}
}

func NewClient(baseURL string, pollInterval time.Duration) *Client {
	return &Client{
		baseURL: baseURL,
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
		cache:    make(map[string]*SentimentData),
		interval: pollInterval,
		done:     make(chan struct{}),
	}
}

func (c *Client) Start(symbols []string) {
	go c.pollLoop(symbols)
}

func (c *Client) Stop() {
	close(c.done)
}

func (c *Client) pollLoop(symbols []string) {
	ticker := time.NewTicker(c.interval)
	defer ticker.Stop()

	c.fetchAll(symbols)

	for {
		select {
		case <-c.done:
			return
		case <-ticker.C:
			c.fetchAll(symbols)
		}
	}
}

func (c *Client) fetchAll(symbols []string) {
	for _, symbol := range symbols {
		data, err := c.Fetch(context.Background(), symbol)
		if err != nil {
			log.Warn().Err(err).Str("symbol", symbol).Msg("failed to fetch sentiment")
			continue
		}

		c.mu.Lock()
		c.cache[symbol] = data
		c.mu.Unlock()

		log.Debug().
			Str("symbol", symbol).
			Float64("score_1h", data.Score1h).
			Float64("score_24h", data.Score24h).
			Msg("sentiment updated")
	}
}

func (c *Client) Fetch(ctx context.Context, symbol string) (*SentimentData, error) {
	url := fmt.Sprintf("%s/sentiment/%s", c.baseURL, symbol)

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected status: %d", resp.StatusCode)
	}

	var data SentimentData
	if err := json.NewDecoder(resp.Body).Decode(&data); err != nil {
		return nil, err
	}

	return &data, nil
}

// FetchHistory retrieves historical sentiment data
func (c *Client) FetchHistory(ctx context.Context, symbol string, days int, period string) (*HistoricalResponse, error) {
	url := fmt.Sprintf("%s/sentiment/%s/history?days=%d&period=%s", c.baseURL, symbol, days, period)

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected status: %d", resp.StatusCode)
	}

	var data HistoricalResponse
	if err := json.NewDecoder(resp.Body).Decode(&data); err != nil {
		return nil, err
	}

	return &data, nil
}

// ComputeDailySentimentAverage computes the average sentiment for a given day from hourly data
func (c *Client) ComputeDailySentimentAverage(ctx context.Context, symbol string) (*HistoricalSentiment, error) {
	history, err := c.FetchHistory(ctx, symbol, 1, "hourly")
	if err != nil {
		return nil, err
	}

	if len(history.Data) == 0 {
		return nil, fmt.Errorf("no sentiment data available for %s", symbol)
	}

	// Average the hourly data for the day
	var sumPositive, sumNegative, sumNeutral float64
	var sumMentions int
	sources := make(map[string]bool)

	for _, h := range history.Data {
		sumPositive += h.ScorePositive
		sumNegative += h.ScoreNegative
		sumNeutral += h.ScoreNeutral
		sumMentions += h.MentionsCount
		for _, src := range h.Sources {
			sources[src] = true
		}
	}

	count := float64(len(history.Data))
	sourceList := make([]string, 0, len(sources))
	for src := range sources {
		sourceList = append(sourceList, src)
	}

	return &HistoricalSentiment{
		ScorePositive: sumPositive / count,
		ScoreNegative: sumNegative / count,
		ScoreNeutral:  sumNeutral / count,
		MentionsCount: sumMentions / len(history.Data),
		Sources:       sourceList,
	}, nil
}

func (c *Client) Get(symbol string) *SentimentData {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.cache[symbol]
}

func (c *Client) GetAll() map[string]*SentimentData {
	c.mu.RLock()
	defer c.mu.RUnlock()

	result := make(map[string]*SentimentData, len(c.cache))
	for k, v := range c.cache {
		result[k] = v
	}
	return result
}
