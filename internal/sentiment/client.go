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
	Symbol        string    `json:"symbol"`
	Score1h       float64   `json:"score_1h"`
	Score24h      float64   `json:"score_24h"`
	Mentions      int       `json:"mentions"`
	MentionsZScore float64  `json:"mentions_zscore"`
	Velocity      float64   `json:"velocity"`
	Timestamp     time.Time `json:"timestamp"`
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
