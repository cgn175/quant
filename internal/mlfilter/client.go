package mlfilter

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"time"

	"github.com/rs/zerolog/log"
)

type Config struct {
	Enabled       bool
	URL           string
	Threshold     float64
	TimeoutMs     int
	FailOpen      bool
	FallbackToADX bool
}

type Client struct {
	cfg        Config
	httpClient *http.Client
	cb         *CircuitBreaker
}

type PredictRequest struct {
	Symbol   string             `json:"symbol"`
	Features map[string]float64 `json:"features"`
}

type PredictResponse struct {
	Symbol       string  `json:"symbol"`
	Prob         float64 `json:"prob"`
	ModelVersion string  `json:"model_version"`
}

type RegimeResponse struct {
	Symbol       string  `json:"symbol"`
	ProbSafe     float64 `json:"prob_safe"`
	ModelVersion string  `json:"model_version"`
}

type VolatilityResponse struct {
	Symbol       string  `json:"symbol"`
	PredRangePct float64 `json:"pred_range_pct"`
	ModelVersion string  `json:"model_version"`
}

func NewClient(cfg Config) *Client {
	if cfg.TimeoutMs <= 0 {
		cfg.TimeoutMs = 200
	}
	if cfg.URL == "" {
		cfg.URL = "http://localhost:9001"
	}

	transport := &http.Transport{
		MaxIdleConns:        10,
		MaxIdleConnsPerHost: 10,
		IdleConnTimeout:     90 * time.Second,
		DialContext: (&net.Dialer{
			Timeout:   time.Duration(cfg.TimeoutMs) * time.Millisecond,
			KeepAlive: 30 * time.Second,
		}).DialContext,
	}

	return &Client{
		cfg: cfg,
		httpClient: &http.Client{
			Transport: transport,
		},
		cb: NewCircuitBreaker(20, 0.5, 5*time.Minute),
	}
}

func (c *Client) IsEnabled() bool {
	return c.cfg.Enabled
}

func (c *Client) Predict(ctx context.Context, symbol string, features map[string]float64) (float64, error) {
	if c.cb.IsTripped() {
		return 0, fmt.Errorf("circuit breaker tripped: ML service disabled")
	}

	timeout := time.Duration(c.cfg.TimeoutMs) * time.Millisecond
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	reqBody := PredictRequest{
		Symbol:   symbol,
		Features: features,
	}

	body, err := json.Marshal(reqBody)
	if err != nil {
		return 0, fmt.Errorf("marshal predict request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.cfg.URL+"/predict", bytes.NewReader(body))
	if err != nil {
		return 0, fmt.Errorf("create predict request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		c.cb.RecordError()
		return 0, fmt.Errorf("predict request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		c.cb.RecordError()
		return 0, fmt.Errorf("predict returned status %d", resp.StatusCode)
	}

	var result PredictResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		c.cb.RecordError()
		return 0, fmt.Errorf("decode predict response: %w", err)
	}

	c.cb.RecordSuccess()

	log.Debug().
		Str("symbol", symbol).
		Float64("prob", result.Prob).
		Str("model_version", result.ModelVersion).
		Msg("ML prediction")

	return result.Prob, nil
}

// PredictRegime calls the regime classifier (Traffic Light) endpoint.
// Returns the probability that the current market regime is SAFE_TO_TRADE.
func (c *Client) PredictRegime(ctx context.Context, symbol string, features map[string]float64) (float64, error) {
	if c.cb.IsTripped() {
		return 0, fmt.Errorf("circuit breaker tripped: ML service disabled")
	}

	timeout := time.Duration(c.cfg.TimeoutMs) * time.Millisecond
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	reqBody := PredictRequest{
		Symbol:   symbol,
		Features: features,
	}

	body, err := json.Marshal(reqBody)
	if err != nil {
		return 0, fmt.Errorf("marshal regime request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.cfg.URL+"/predict_regime", bytes.NewReader(body))
	if err != nil {
		return 0, fmt.Errorf("create regime request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		c.cb.RecordError()
		return 0, fmt.Errorf("regime request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		c.cb.RecordError()
		return 0, fmt.Errorf("regime returned status %d", resp.StatusCode)
	}

	var result RegimeResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		c.cb.RecordError()
		return 0, fmt.Errorf("decode regime response: %w", err)
	}

	c.cb.RecordSuccess()

	log.Debug().
		Str("symbol", symbol).
		Float64("prob_safe", result.ProbSafe).
		Str("model_version", result.ModelVersion).
		Msg("Regime prediction")

	return result.ProbSafe, nil
}

// PredictVolatility calls the volatility predictor (Dynamic Stop-Loss) endpoint.
// Returns the predicted next-candle range as a percentage (e.g., 0.025 = 2.5%).
func (c *Client) PredictVolatility(ctx context.Context, symbol string, features map[string]float64) (float64, error) {
	if c.cb.IsTripped() {
		return 0, fmt.Errorf("circuit breaker tripped: ML service disabled")
	}

	timeout := time.Duration(c.cfg.TimeoutMs) * time.Millisecond
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	reqBody := PredictRequest{
		Symbol:   symbol,
		Features: features,
	}

	body, err := json.Marshal(reqBody)
	if err != nil {
		return 0, fmt.Errorf("marshal volatility request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.cfg.URL+"/predict_volatility", bytes.NewReader(body))
	if err != nil {
		return 0, fmt.Errorf("create volatility request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		c.cb.RecordError()
		return 0, fmt.Errorf("volatility request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		c.cb.RecordError()
		return 0, fmt.Errorf("volatility returned status %d", resp.StatusCode)
	}

	var result VolatilityResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		c.cb.RecordError()
		return 0, fmt.Errorf("decode volatility response: %w", err)
	}

	c.cb.RecordSuccess()

	log.Debug().
		Str("symbol", symbol).
		Float64("pred_range_pct", result.PredRangePct).
		Str("model_version", result.ModelVersion).
		Msg("Volatility prediction")

	return result.PredRangePct, nil
}
