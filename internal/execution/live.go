package execution

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"time"
)

type LiveExecutor struct {
	apiKey     string
	apiSecret  string
	testnet    bool
	httpClient *http.Client
	// Market type for routing: "spot" or "futures" (default: "spot")
	marketType string
}

func NewLiveExecutor(apiKey, apiSecret string, testnet bool) *LiveExecutor {
	return &LiveExecutor{
		apiKey:     apiKey,
		apiSecret:  apiSecret,
		testnet:    testnet,
		marketType: "spot", // default to spot for backward compatibility
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

// NewLiveFuturesExecutor creates a LiveExecutor configured for futures perpetual orders.
func NewLiveFuturesExecutor(apiKey, apiSecret string, testnet bool) *LiveExecutor {
	return &LiveExecutor{
		apiKey:     apiKey,
		apiSecret:  apiSecret,
		testnet:    testnet,
		marketType: "futures",
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

func (l *LiveExecutor) baseURL() string {
	if l.marketType == "futures" {
		if l.testnet {
			return "https://testnet.binancefuture.com"
		}
		return "https://fapi.binance.com"
	}
	// Spot
	if l.testnet {
		return "https://testnet.binance.vision"
	}
	return "https://api.binance.com"
}

func (l *LiveExecutor) sign(queryString string) string {
	mac := hmac.New(sha256.New, []byte(l.apiSecret))
	mac.Write([]byte(queryString))
	return hex.EncodeToString(mac.Sum(nil))
}

type binanceOrderResponse struct {
	OrderID             int64  `json:"orderId"`
	ClientOrderID       string `json:"clientOrderId"`
	Symbol              string `json:"symbol"`
	Side                string `json:"side"`
	Type                string `json:"type"`
	Status              string `json:"status"`
	Price               string `json:"price"`
	OrigQty             string `json:"origQty"`
	ExecutedQty         string `json:"executedQty"`
	CummulativeQuoteQty string `json:"cummulativeQuoteQty"`
	TransactTime        int64  `json:"transactTime"`
	Time                int64  `json:"time"`
	UpdateTime          int64  `json:"updateTime"`
}

type binanceError struct {
	Code    int    `json:"code"`
	Message string `json:"msg"`
}

func (l *LiveExecutor) doSignedRequest(method, endpoint string, params url.Values) ([]byte, error) {
	params.Set("timestamp", strconv.FormatInt(time.Now().UnixMilli(), 10))
	queryString := params.Encode()
	signature := l.sign(queryString)
	queryString += "&signature=" + signature

	fullURL := l.baseURL() + endpoint + "?" + queryString

	req, err := http.NewRequest(method, fullURL, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("X-MBX-APIKEY", l.apiKey)

	resp, err := l.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	if resp.StatusCode >= 400 {
		var binErr binanceError
		if json.Unmarshal(body, &binErr) == nil && binErr.Code != 0 {
			return nil, fmt.Errorf("binance error %d: %s", binErr.Code, binErr.Message)
		}
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(body))
	}

	return body, nil
}

func (l *LiveExecutor) parseOrderResponse(body []byte) (*Order, error) {
	var resp binanceOrderResponse
	if err := json.Unmarshal(body, &resp); err != nil {
		return nil, fmt.Errorf("failed to parse order response: %w", err)
	}

	price, _ := strconv.ParseFloat(resp.Price, 64)
	origQty, _ := strconv.ParseFloat(resp.OrigQty, 64)
	executedQty, _ := strconv.ParseFloat(resp.ExecutedQty, 64)
	cumulativeQuoteQty, _ := strconv.ParseFloat(resp.CummulativeQuoteQty, 64)

	var filledPrice float64
	if executedQty > 0 {
		filledPrice = cumulativeQuoteQty / executedQty
	}

	var status OrderStatus
	switch resp.Status {
	case "NEW", "PARTIALLY_FILLED":
		status = OrderStatusNew
	case "FILLED":
		status = OrderStatusFilled
	case "CANCELED", "EXPIRED":
		status = OrderStatusCanceled
	case "REJECTED":
		status = OrderStatusRejected
	default:
		status = OrderStatusNew
	}

	timestamp := resp.TransactTime
	if timestamp == 0 {
		timestamp = resp.Time
	}

	return &Order{
		ID:            strconv.FormatInt(resp.OrderID, 10),
		Symbol:        resp.Symbol,
		Type:          OrderType(resp.Type),
		Side:          OrderSide(resp.Side),
		Price:         price,
		Size:          origQty,
		Status:        status,
		FilledPrice:   filledPrice,
		FilledSize:    executedQty,
		CreatedAt:     time.UnixMilli(timestamp),
		UpdatedAt:     time.UnixMilli(resp.UpdateTime),
		ClientOrderID: resp.ClientOrderID,
	}, nil
}

func (l *LiveExecutor) ExecuteMarketOrder(symbol string, side OrderSide, size float64) (*Order, error) {
	params := url.Values{}
	params.Set("symbol", symbol)
	params.Set("side", string(side))
	params.Set("type", "MARKET")
	params.Set("quantity", strconv.FormatFloat(size, 'f', -1, 64))

	// Futures require positionSide parameter for hedge mode
	if l.marketType == "futures" {
		params.Set("positionSide", "BOTH") // one-way mode (no hedge)
	}

	endpoint := "/api/v3/order"
	if l.marketType == "futures" {
		endpoint = "/fapi/v1/order"
	}

	body, err := l.doSignedRequest(http.MethodPost, endpoint, params)
	if err != nil {
		return nil, fmt.Errorf("market order failed: %w", err)
	}

	return l.parseOrderResponse(body)
}

func (l *LiveExecutor) ExecuteLimitOrder(symbol string, side OrderSide, price, size float64) (*Order, error) {
	params := url.Values{}
	params.Set("symbol", symbol)
	params.Set("side", string(side))
	params.Set("type", "LIMIT")
	params.Set("timeInForce", "GTC")
	params.Set("quantity", strconv.FormatFloat(size, 'f', -1, 64))
	params.Set("price", strconv.FormatFloat(price, 'f', -1, 64))

	if l.marketType == "futures" {
		params.Set("positionSide", "BOTH")
	}

	endpoint := "/api/v3/order"
	if l.marketType == "futures" {
		endpoint = "/fapi/v1/order"
	}

	body, err := l.doSignedRequest(http.MethodPost, endpoint, params)
	if err != nil {
		return nil, fmt.Errorf("limit order failed: %w", err)
	}

	return l.parseOrderResponse(body)
}

func (l *LiveExecutor) CancelOrder(symbol string, orderID string) error {
	params := url.Values{}
	params.Set("symbol", symbol)
	params.Set("orderId", orderID)

	endpoint := "/api/v3/order"
	if l.marketType == "futures" {
		endpoint = "/fapi/v1/order"
	}

	_, err := l.doSignedRequest(http.MethodDelete, endpoint, params)
	if err != nil {
		return fmt.Errorf("cancel order failed: %w", err)
	}

	return nil
}

func (l *LiveExecutor) GetOrder(symbol string, orderID string) (*Order, error) {
	params := url.Values{}
	params.Set("symbol", symbol)
	params.Set("orderId", orderID)

	endpoint := "/api/v3/order"
	if l.marketType == "futures" {
		endpoint = "/fapi/v1/order"
	}

	body, err := l.doSignedRequest(http.MethodGet, endpoint, params)
	if err != nil {
		return nil, fmt.Errorf("get order failed: %w", err)
	}

	return l.parseOrderResponse(body)
}

func (l *LiveExecutor) Close() error {
	return nil
}
