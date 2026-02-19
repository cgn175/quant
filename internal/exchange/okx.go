package exchange

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"time"

	"github.com/rs/zerolog/log"
)

const (
	okxBaseURL = "https://www.okx.com"
)

type OKXClient struct {
	httpClient *http.Client
}

func NewOKXClient() *OKXClient {
	return &OKXClient{
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

type okxFundingRate struct {
	InstID      string `json:"instId"`
	FundingRate string `json:"fundingRate"`
	NextFundingTime string `json:"nextFundingTime"`
	FundingTime string `json:"fundingTime"`
}

type okxFundingResponse struct {
	Code string           `json:"code"`
	Msg  string           `json:"msg"`
	Data []okxFundingRate `json:"data"`
}

func (c *OKXClient) GetFundingRate(symbol string) (*FundingRateInfo, error) {
	// OKX uses different symbol format (e.g., BTC-USDT-SWAP)
	instId := convertToOKXSymbol(symbol)
	url := fmt.Sprintf("%s/api/v5/public/funding-rate?instId=%s", okxBaseURL, instId)

	resp, err := c.httpClient.Get(url)
	if err != nil {
		return nil, fmt.Errorf("okx funding rate request failed: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("okx funding rate read failed: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("okx funding rate API error: status=%d body=%s", resp.StatusCode, string(body))
	}

	var response okxFundingResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return nil, fmt.Errorf("okx funding rate parse failed: %w", err)
	}

	if response.Code != "0" || len(response.Data) == 0 {
		return nil, fmt.Errorf("okx funding rate error: %s", response.Msg)
	}

	fr := response.Data[0]
	fundingRate, _ := strconv.ParseFloat(fr.FundingRate, 64)
	nextFundingTime, _ := strconv.ParseInt(fr.NextFundingTime, 10, 64)

	return &FundingRateInfo{
		Symbol:      symbol,
		FundingRate: fundingRate,
		FundingTime: time.UnixMilli(nextFundingTime),
		MarkPrice:   0, // Will be fetched separately if needed
	}, nil
}

type okxTicker struct {
	InstID    string `json:"instId"`
	MarkPx    string `json:"markPx"`
	Last      string `json:"last"`
}

type okxTickerResponse struct {
	Code string      `json:"code"`
	Msg  string      `json:"msg"`
	Data []okxTicker `json:"data"`
}

func (c *OKXClient) GetPerpPrice(symbol string) (float64, error) {
	instId := convertToOKXSymbol(symbol)
	url := fmt.Sprintf("%s/api/v5/market/ticker?instId=%s", okxBaseURL, instId)

	resp, err := c.httpClient.Get(url)
	if err != nil {
		return 0, fmt.Errorf("okx perp price request failed: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return 0, fmt.Errorf("okx perp price read failed: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return 0, fmt.Errorf("okx perp price API error: status=%d body=%s", resp.StatusCode, string(body))
	}

	var response okxTickerResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return 0, fmt.Errorf("okx perp price parse failed: %w", err)
	}

	if response.Code != "0" || len(response.Data) == 0 {
		return 0, fmt.Errorf("okx perp price error: %s", response.Msg)
	}

	price, err := strconv.ParseFloat(response.Data[0].MarkPx, 64)
	if err != nil {
		return 0, fmt.Errorf("okx perp price parse float failed: %w", err)
	}

	return price, nil
}

func (c *OKXClient) GetSpotPrice(symbol string) (float64, error) {
	// Convert BTCUSDT to BTC-USDT for spot
	instId := convertToOKXSpotSymbol(symbol)
	url := fmt.Sprintf("%s/api/v5/market/ticker?instId=%s", okxBaseURL, instId)

	resp, err := c.httpClient.Get(url)
	if err != nil {
		return 0, fmt.Errorf("okx spot price request failed: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return 0, fmt.Errorf("okx spot price read failed: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return 0, fmt.Errorf("okx spot price API error: status=%d body=%s", resp.StatusCode, string(body))
	}

	var response okxTickerResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return 0, fmt.Errorf("okx spot price parse failed: %w", err)
	}

	if response.Code != "0" || len(response.Data) == 0 {
		return 0, fmt.Errorf("okx spot price error: %s", response.Msg)
	}

	price, err := strconv.ParseFloat(response.Data[0].Last, 64)
	if err != nil {
		return 0, fmt.Errorf("okx spot price parse float failed: %w", err)
	}

	return price, nil
}

type okxOrderBook struct {
	Bids [][]string `json:"bids"`
	Asks [][]string `json:"asks"`
}

type okxOrderBookResponse struct {
	Code string        `json:"code"`
	Msg  string        `json:"msg"`
	Data []okxOrderBook `json:"data"`
}

func (c *OKXClient) GetOrderBook(symbol string) (*OrderBook, error) {
	instId := convertToOKXSymbol(symbol)
	url := fmt.Sprintf("%s/api/v5/market/books?instId=%s&sz=5", okxBaseURL, instId)

	resp, err := c.httpClient.Get(url)
	if err != nil {
		return nil, fmt.Errorf("okx orderbook request failed: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("okx orderbook read failed: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("okx orderbook API error: status=%d body=%s", resp.StatusCode, string(body))
	}

	var response okxOrderBookResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return nil, fmt.Errorf("okx orderbook parse failed: %w", err)
	}

	if response.Code != "0" || len(response.Data) == 0 {
		return nil, fmt.Errorf("okx orderbook error: %s", response.Msg)
	}

	ob := &OrderBook{
		Symbol:    symbol,
		Timestamp: time.Now(),
		Bids:      make([]PriceLevel, len(response.Data[0].Bids)),
		Asks:      make([]PriceLevel, len(response.Data[0].Asks)),
	}

	for i, bid := range response.Data[0].Bids {
		price, _ := strconv.ParseFloat(bid[0], 64)
		qty, _ := strconv.ParseFloat(bid[1], 64)
		ob.Bids[i] = PriceLevel{Price: price, Quantity: qty}
	}

	for i, ask := range response.Data[0].Asks {
		price, _ := strconv.ParseFloat(ask[0], 64)
		qty, _ := strconv.ParseFloat(ask[1], 64)
		ob.Asks[i] = PriceLevel{Price: price, Quantity: qty}
	}

	return ob, nil
}

// PlaceOrder is a placeholder for order execution - would need API keys and signing
func (c *OKXClient) PlaceOrder(symbol, side string, quantity, price float64) error {
	log.Warn().Str("exchange", "okx").Msg("PlaceOrder not implemented - requires API keys and signing")
	return fmt.Errorf("okx order placement not implemented")
}

func (c *OKXClient) Close() error {
	return nil
}

// Helper functions to convert symbol formats
func convertToOKXSymbol(symbol string) string {
	// Convert BTCUSDT to BTC-USDT-SWAP
	if len(symbol) >= 6 {
		base := symbol[:len(symbol)-4] // Remove USDT
		return fmt.Sprintf("%s-USDT-SWAP", base)
	}
	return symbol
}

func convertToOKXSpotSymbol(symbol string) string {
	// Convert BTCUSDT to BTC-USDT
	if len(symbol) >= 6 {
		base := symbol[:len(symbol)-4] // Remove USDT
		return fmt.Sprintf("%s-USDT", base)
	}
	return symbol
}