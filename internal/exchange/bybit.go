package exchange

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"time"

	"github.com/rs/zerolog/log"
)

const (
	bybitBaseURL        = "https://api.bybit.com"
	bybitTestnetBaseURL = "https://api-testnet.bybit.com"
)

type BybitClient struct {
	testnet    bool
	apiKey     string
	apiSecret  string
	httpClient *http.Client
}

func NewBybitClient(testnet bool) *BybitClient {
	return &BybitClient{
		testnet: testnet,
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

// NewBybitAuthClient creates an authenticated Bybit client
func NewBybitAuthClient(testnet bool, apiKey, apiSecret string) *BybitClient {
	return &BybitClient{
		testnet:   testnet,
		apiKey:    apiKey,
		apiSecret: apiSecret,
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

func (c *BybitClient) baseURL() string {
	if c.testnet {
		return bybitTestnetBaseURL
	}
	return bybitBaseURL
}

type bybitFundingRate struct {
	Symbol               string `json:"symbol"`
	FundingRate          string `json:"fundingRate"`
	FundingRateTimestamp string `json:"fundingRateTimestamp"`
}

type bybitFundingResult struct {
	Category string             `json:"category"`
	List     []bybitFundingRate `json:"list"`
}

type bybitFundingResponse struct {
	RetCode int                `json:"retCode"`
	RetMsg  string             `json:"retMsg"`
	Result  bybitFundingResult `json:"result"`
}

func (c *BybitClient) GetFundingRate(symbol string) (*FundingRateInfo, error) {
	url := fmt.Sprintf("%s/v5/market/funding/history?category=linear&symbol=%s&limit=1", c.baseURL(), symbol)

	resp, err := c.httpClient.Get(url)
	if err != nil {
		return nil, fmt.Errorf("bybit funding rate request failed: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("bybit funding rate read failed: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("bybit funding rate API error: status=%d body=%s", resp.StatusCode, string(body))
	}

	var response bybitFundingResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return nil, fmt.Errorf("bybit funding rate parse failed: %w", err)
	}

	if response.RetCode != 0 || len(response.Result.List) == 0 {
		return nil, fmt.Errorf("bybit funding rate error: %s", response.RetMsg)
	}

	fr := response.Result.List[0]
	fundingRate, _ := strconv.ParseFloat(fr.FundingRate, 64)
	fundingTimestamp, _ := strconv.ParseInt(fr.FundingRateTimestamp, 10, 64)

	return &FundingRateInfo{
		Symbol:      symbol,
		FundingRate: fundingRate,
		FundingTime: time.UnixMilli(fundingTimestamp),
		MarkPrice:   0, // Will be fetched separately if needed
	}, nil
}

type bybitTicker struct {
	Symbol    string `json:"symbol"`
	MarkPrice string `json:"markPrice"`
}

type bybitTickerResponse struct {
	RetCode int           `json:"retCode"`
	RetMsg  string        `json:"retMsg"`
	Result  []bybitTicker `json:"result"`
}

func (c *BybitClient) GetPerpPrice(symbol string) (float64, error) {
	url := fmt.Sprintf("%s/v5/market/tickers?category=linear&symbol=%s", c.baseURL(), symbol)

	resp, err := c.httpClient.Get(url)
	if err != nil {
		return 0, fmt.Errorf("bybit perp price request failed: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return 0, fmt.Errorf("bybit perp price read failed: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return 0, fmt.Errorf("bybit perp price API error: status=%d body=%s", resp.StatusCode, string(body))
	}

	var response bybitTickerResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return 0, fmt.Errorf("bybit perp price parse failed: %w", err)
	}

	if response.RetCode != 0 || len(response.Result) == 0 {
		return 0, fmt.Errorf("bybit perp price error: %s", response.RetMsg)
	}

	price, err := strconv.ParseFloat(response.Result[0].MarkPrice, 64)
	if err != nil {
		return 0, fmt.Errorf("bybit perp price parse float failed: %w", err)
	}

	return price, nil
}

func (c *BybitClient) GetSpotPrice(symbol string) (float64, error) {
	url := fmt.Sprintf("%s/v5/market/tickers?category=spot&symbol=%s", c.baseURL(), symbol)

	resp, err := c.httpClient.Get(url)
	if err != nil {
		return 0, fmt.Errorf("bybit spot price request failed: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return 0, fmt.Errorf("bybit spot price read failed: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return 0, fmt.Errorf("bybit spot price API error: status=%d body=%s", resp.StatusCode, string(body))
	}

	var response bybitTickerResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return 0, fmt.Errorf("bybit spot price parse failed: %w", err)
	}

	if response.RetCode != 0 || len(response.Result) == 0 {
		return 0, fmt.Errorf("bybit spot price error: %s", response.RetMsg)
	}

	price, err := strconv.ParseFloat(response.Result[0].MarkPrice, 64)
	if err != nil {
		return 0, fmt.Errorf("bybit spot price parse float failed: %w", err)
	}

	return price, nil
}

type bybitOrderBook struct {
	Symbol string     `json:"s"`
	Bids   [][]string `json:"b"`
	Asks   [][]string `json:"a"`
}

type bybitOrderBookResponse struct {
	RetCode int            `json:"retCode"`
	RetMsg  string         `json:"retMsg"`
	Result  bybitOrderBook `json:"result"`
}

func (c *BybitClient) GetOrderBook(symbol string) (*OrderBook, error) {
	url := fmt.Sprintf("%s/v5/market/orderbook?category=linear&symbol=%s&limit=5", c.baseURL(), symbol)

	resp, err := c.httpClient.Get(url)
	if err != nil {
		return nil, fmt.Errorf("bybit orderbook request failed: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("bybit orderbook read failed: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("bybit orderbook API error: status=%d body=%s", resp.StatusCode, string(body))
	}

	var response bybitOrderBookResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return nil, fmt.Errorf("bybit orderbook parse failed: %w", err)
	}

	if response.RetCode != 0 {
		return nil, fmt.Errorf("bybit orderbook error: %s", response.RetMsg)
	}

	ob := &OrderBook{
		Symbol:    symbol,
		Timestamp: time.Now(),
		Bids:      make([]PriceLevel, len(response.Result.Bids)),
		Asks:      make([]PriceLevel, len(response.Result.Asks)),
	}

	for i, bid := range response.Result.Bids {
		price, _ := strconv.ParseFloat(bid[0], 64)
		qty, _ := strconv.ParseFloat(bid[1], 64)
		ob.Bids[i] = PriceLevel{Price: price, Quantity: qty}
	}

	for i, ask := range response.Result.Asks {
		price, _ := strconv.ParseFloat(ask[0], 64)
		qty, _ := strconv.ParseFloat(ask[1], 64)
		ob.Asks[i] = PriceLevel{Price: price, Quantity: qty}
	}

	return ob, nil
}

func (c *BybitClient) sign(timestamp, recvWindow, params string) string {
	message := timestamp + c.apiKey + recvWindow + params
	h := hmac.New(sha256.New, []byte(c.apiSecret))
	h.Write([]byte(message))
	return hex.EncodeToString(h.Sum(nil))
}

func (c *BybitClient) PlaceOrder(symbol, side string, quantity, price float64) error {
	if c.apiKey == "" || c.apiSecret == "" {
		return fmt.Errorf("bybit authentication not configured")
	}

	timestamp := fmt.Sprintf("%d", time.Now().UnixMilli())
	recvWindow := "5000"

	orderReq := map[string]interface{}{
		"category":  "linear",
		"symbol":    symbol,
		"side":      side,
		"orderType": "Market",
		"qty":       fmt.Sprintf("%.4f", quantity),
	}

	bodyBytes, _ := json.Marshal(orderReq)
	signature := c.sign(timestamp, recvWindow, string(bodyBytes))

	req, _ := http.NewRequest("POST", c.baseURL()+"/v5/order/create", bytes.NewBuffer(bodyBytes))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-BAPI-API-KEY", c.apiKey)
	req.Header.Set("X-BAPI-TIMESTAMP", timestamp)
	req.Header.Set("X-BAPI-SIGN", signature)
	req.Header.Set("X-BAPI-RECV-WINDOW", recvWindow)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("bybit order request failed: %w", err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("bybit order failed: status=%d body=%s", resp.StatusCode, string(body))
	}

	var result struct {
		RetCode int    `json:"retCode"`
		RetMsg  string `json:"retMsg"`
	}
	if err := json.Unmarshal(body, &result); err != nil {
		return fmt.Errorf("bybit order parse failed: %w", err)
	}

	if result.RetCode != 0 {
		return fmt.Errorf("bybit order error: %s", result.RetMsg)
	}

	log.Info().Str("exchange", "bybit").Str("symbol", symbol).Str("side", side).Float64("qty", quantity).Msg("Order placed")
	return nil
}

func (c *BybitClient) Close() error {
	return nil
}