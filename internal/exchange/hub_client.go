package exchange

import (
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"github.com/rs/zerolog/log"
)

const (
	binanceSpotBaseURL        = "https://api.binance.com"
	binanceSpotTestnetBaseURL = "https://testnet.binance.vision"
)

// HubClient implements the Client interface by connecting to a local WS hub
// that multiplexes Binance market data, instead of connecting directly to Binance.
type HubClient struct {
	hubURL     string
	testnet    bool
	conn       *websocket.Conn
	mu         sync.RWMutex
	done       chan struct{}
	handlers   map[string]interface{} // stream name -> CandleHandler or OrderBookHandler
	streamType map[string]streamType  // stream name -> type
	symbols    map[string]string      // stream name -> original symbol (for depth parsing)
	connected  bool
	httpClient *http.Client
}

// NewHubClient creates a new HubClient that connects to the given WS hub URL.
// The testnet flag controls which Binance REST endpoints are used for funding rates.
func NewHubClient(hubURL string, testnet bool) *HubClient {
	return &HubClient{
		hubURL:     hubURL,
		testnet:    testnet,
		done:       make(chan struct{}),
		handlers:   make(map[string]interface{}),
		streamType: make(map[string]streamType),
		symbols:    make(map[string]string),
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

// hubSubscribeMsg is the JSON message sent to the hub to subscribe to a stream.
type hubSubscribeMsg struct {
	Action string `json:"action"`
	Stream string `json:"stream"`
}

// hubMessage is the JSON envelope received from the hub.
type hubMessage struct {
	Stream string          `json:"stream"`
	Data   json.RawMessage `json:"data"`
}

func (c *HubClient) SubscribeCandles(symbol, interval string, handler CandleHandler) error {
	stream := fmt.Sprintf("%s@kline_%s", strings.ToLower(symbol), interval)

	c.mu.Lock()
	c.handlers[stream] = handler
	c.streamType[stream] = streamTypeCandle
	c.mu.Unlock()

	if err := c.ensureConnected(); err != nil {
		return err
	}

	if err := c.sendSubscribe(stream); err != nil {
		return err
	}

	log.Info().Str("symbol", symbol).Str("interval", interval).Str("hub", c.hubURL).Msg("hub: subscribed to candles")
	return nil
}

func (c *HubClient) SubscribeOrderBook(symbol string, handler OrderBookHandler) error {
	stream := fmt.Sprintf("%s@depth5@100ms", strings.ToLower(symbol))

	c.mu.Lock()
	c.handlers[stream] = handler
	c.streamType[stream] = streamTypeOrderBook
	c.symbols[stream] = symbol
	c.mu.Unlock()

	if err := c.ensureConnected(); err != nil {
		return err
	}

	if err := c.sendSubscribe(stream); err != nil {
		return err
	}

	log.Info().Str("symbol", symbol).Str("hub", c.hubURL).Msg("hub: subscribed to orderbook")
	return nil
}

// SubscribeRaw subscribes to any stream with a raw data handler
func (c *HubClient) SubscribeRaw(stream string, handler func([]byte)) error {
	c.mu.Lock()
	c.handlers[stream] = handler
	c.streamType[stream] = streamTypeRaw
	c.mu.Unlock()

	if err := c.sendSubscribe(stream); err != nil {
		return err
	}

	log.Info().Str("stream", stream).Str("hub", c.hubURL).Msg("hub: subscribed to raw stream")
	return nil
}

// PollCandles delegates to SubscribeCandles since the hub provides WS data.
func (c *HubClient) PollCandles(symbol, interval string, handler CandleHandler, _ time.Duration) {
	log.Info().Str("symbol", symbol).Str("interval", interval).Msg("hub mode: using WS subscription instead of REST polling")
	if err := c.SubscribeCandles(symbol, interval, handler); err != nil {
		log.Error().Err(err).Str("symbol", symbol).Msg("hub: failed to subscribe candles in poll mode")
	}
}

// PollOrderBook delegates to SubscribeOrderBook since the hub provides WS data.
func (c *HubClient) PollOrderBook(symbol string, handler OrderBookHandler, _ time.Duration) {
	log.Info().Str("symbol", symbol).Msg("hub mode: using WS subscription instead of REST polling")
	if err := c.SubscribeOrderBook(symbol, handler); err != nil {
		log.Error().Err(err).Str("symbol", symbol).Msg("hub: failed to subscribe orderbook in poll mode")
	}
}

func (c *HubClient) sendSubscribe(stream string) error {
	c.mu.RLock()
	conn := c.conn
	c.mu.RUnlock()

	if conn == nil {
		return fmt.Errorf("hub: not connected")
	}

	msg := hubSubscribeMsg{Action: "subscribe", Stream: stream}
	data, err := json.Marshal(msg)
	if err != nil {
		return fmt.Errorf("hub: marshal subscribe message: %w", err)
	}

	c.mu.Lock()
	defer c.mu.Unlock()
	if err := c.conn.WriteMessage(websocket.TextMessage, data); err != nil {
		return fmt.Errorf("hub: send subscribe message: %w", err)
	}

	return nil
}

func (c *HubClient) ensureConnected() error {
	c.mu.Lock()
	defer c.mu.Unlock()

	if c.connected {
		return nil
	}

	return c.connectToHubLocked()
}

func (c *HubClient) connectToHubLocked() error {
	url := "ws://" + c.hubURL
	conn, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		return fmt.Errorf("hub: failed to connect to %s: %w", url, err)
	}

	if c.conn != nil {
		c.conn.Close()
	}
	c.conn = conn
	c.connected = true

	log.Info().Str("url", url).Msg("hub: connected")

	go c.readLoop(conn)

	return nil
}

func (c *HubClient) readLoop(conn *websocket.Conn) {
	for {
		select {
		case <-c.done:
			return
		default:
		}

		_, message, err := conn.ReadMessage()
		if err != nil {
			c.mu.RLock()
			stillCurrent := c.conn == conn
			c.mu.RUnlock()

			if stillCurrent {
				log.Error().Err(err).Msg("hub: ws read error, will reconnect")
				go c.reconnectWithBackoff()
			}
			return
		}

		var msg hubMessage
		if err := json.Unmarshal(message, &msg); err != nil {
			log.Warn().Err(err).Msg("hub: failed to parse message")
			continue
		}

		//log.Info().Str("stream", msg.Stream).Msg("hub: received tick")
		c.dispatchMessage(msg)
	}
}

func (c *HubClient) dispatchMessage(msg hubMessage) {
	c.mu.RLock()
	handler, exists := c.handlers[msg.Stream]
	st := c.streamType[msg.Stream]
	symbol := c.symbols[msg.Stream]
	c.mu.RUnlock()

	if !exists {
		return
	}

	switch st {
	case streamTypeCandle:
		candle, err := ParseKlineMessage(msg.Data)
		if err != nil {
			log.Warn().Err(err).Str("stream", msg.Stream).Msg("hub: failed to parse kline")
			return
		}
		if h, ok := handler.(CandleHandler); ok {
			go h(candle)
		}

	case streamTypeOrderBook:
		ob, err := ParseDepthMessage(msg.Data, symbol)
		if err != nil {
			log.Warn().Err(err).Str("stream", msg.Stream).Msg("hub: failed to parse depth")
			return
		}
		if h, ok := handler.(OrderBookHandler); ok {
			go h(ob)
		}

	case streamTypeRaw:
		if h, ok := handler.(func([]byte)); ok {
			go h(msg.Data)
		}
	}
}

func (c *HubClient) reconnectWithBackoff() {
	c.mu.Lock()
	c.connected = false
	if c.conn != nil {
		c.conn.Close()
		c.conn = nil
	}
	c.mu.Unlock()

	backoff := initialBackoff

	for {
		select {
		case <-c.done:
			return
		default:
		}

		log.Info().Dur("backoff", backoff).Msg("hub: attempting reconnect")

		c.mu.Lock()
		err := c.connectToHubLocked()
		c.mu.Unlock()

		if err != nil {
			log.Error().Err(err).Dur("backoff", backoff).Msg("hub: reconnect failed, will retry")
			time.Sleep(backoff)
			backoff = time.Duration(math.Min(float64(backoff)*backoffFactor, float64(maxBackoff)))
			continue
		}

		// Re-subscribe to all streams after reconnection
		c.mu.RLock()
		streams := make([]string, 0, len(c.handlers))
		for stream := range c.handlers {
			streams = append(streams, stream)
		}
		c.mu.RUnlock()

		for _, stream := range streams {
			if err := c.sendSubscribe(stream); err != nil {
				log.Error().Err(err).Str("stream", stream).Msg("hub: re-subscribe failed")
			}
		}

		log.Info().Int("streams", len(streams)).Msg("hub: reconnected and re-subscribed")
		return
	}
}

func (c *HubClient) Close() error {
	close(c.done)

	c.mu.Lock()
	defer c.mu.Unlock()

	// Send unsubscribe for all streams
	if c.conn != nil {
		for stream := range c.handlers {
			msg := hubSubscribeMsg{Action: "unsubscribe", Stream: stream}
			data, _ := json.Marshal(msg)
			c.conn.WriteMessage(websocket.TextMessage, data)
		}
		c.conn.Close()
		c.conn = nil
	}

	c.connected = false
	c.handlers = make(map[string]interface{})
	c.streamType = make(map[string]streamType)
	c.symbols = make(map[string]string)

	return nil
}

// FetchSpotPrice fetches spot price via REST API (not via hub WebSocket)
func (c *HubClient) FetchSpotPrice(symbol string) (float64, error) {
	url := fmt.Sprintf("%s/api/v3/ticker/price?symbol=%s", c.spotBaseURL(), symbol)
	
	resp, err := c.httpClient.Get(url)
	if err != nil {
		return 0, fmt.Errorf("spot price request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return 0, fmt.Errorf("spot price API error: status=%d", resp.StatusCode)
	}

	var result struct {
		Symbol string `json:"symbol"`
		Price  string `json:"price"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return 0, fmt.Errorf("spot price parse failed: %w", err)
	}

	price, err := strconv.ParseFloat(result.Price, 64)
	if err != nil {
		return 0, fmt.Errorf("spot price parse float failed: %w", err)
	}

	return price, nil
}

func (c *HubClient) spotBaseURL() string {
	if c.testnet {
		return binanceSpotTestnetBaseURL
	}
	return binanceSpotBaseURL
}

// GetFundingRate is an alias for FetchFundingRate (for interface compatibility)
func (c *HubClient) GetFundingRate(symbol string) (*FundingRateInfo, error) {
	return c.FetchFundingRate(symbol)
}

// GetPerpPrice is an alias for FetchPerpPrice (for interface compatibility)
func (c *HubClient) GetPerpPrice(symbol string) (float64, error) {
	return c.FetchSpotPrice(symbol) // Hub client uses spot price
}

// ---------------------------------------------------------------------------
// Funding Rate REST calls — direct to Binance (not via hub)
// ---------------------------------------------------------------------------

func (c *HubClient) futuresBaseURL() string {
	if c.testnet {
		return binanceFuturesTestnetBaseURL
	}
	return binanceFuturesBaseURL
}

func (c *HubClient) FetchFundingRate(symbol string) (*FundingRateInfo, error) {
	url := fmt.Sprintf("%s/fapi/v1/premiumIndex?symbol=%s", c.futuresBaseURL(), symbol)

	resp, err := c.httpClient.Get(url)
	if err != nil {
		return nil, fmt.Errorf("funding rate HTTP request failed for %s: %w", symbol, err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("funding rate read body failed for %s: %w", symbol, err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("funding rate API error for %s: status=%d body=%s", symbol, resp.StatusCode, string(body))
	}

	var idx binancePremiumIndex
	if err := json.Unmarshal(body, &idx); err != nil {
		return nil, fmt.Errorf("funding rate JSON parse failed for %s: %w", symbol, err)
	}

	fundingRate, _ := strconv.ParseFloat(idx.LastFundingRate, 64)
	markPrice, _ := strconv.ParseFloat(idx.MarkPrice, 64)

	info := &FundingRateInfo{
		Symbol:      idx.Symbol,
		FundingRate: fundingRate,
		FundingTime: time.UnixMilli(idx.NextFundingTime),
		MarkPrice:   markPrice,
	}

	log.Debug().
		Str("symbol", symbol).
		Float64("funding_rate", fundingRate).
		Float64("mark_price", markPrice).
		Msg("fetched funding rate")

	return info, nil
}

func (c *HubClient) FetchFundingRates(symbols []string) (map[string]*FundingRateInfo, error) {
	results := make(map[string]*FundingRateInfo, len(symbols))

	for _, sym := range symbols {
		info, err := c.FetchFundingRate(sym)
		if err != nil {
			log.Warn().Err(err).Str("symbol", sym).Msg("failed to fetch funding rate, skipping")
			continue
		}
		results[sym] = info
	}

	if len(results) == 0 && len(symbols) > 0 {
		return results, fmt.Errorf("failed to fetch funding rates for all %d symbols", len(symbols))
	}

	return results, nil
}

func (c *HubClient) FetchOpenInterest(symbol string) (float64, error) {
	return 0, fmt.Errorf("open interest not implemented via hub")
}

func (c *HubClient) FetchAllFundingRates() (map[string]*FundingRateInfo, error) {
	url := fmt.Sprintf("%s/fapi/v1/premiumIndex", c.futuresBaseURL())

	resp, err := c.httpClient.Get(url)
	if err != nil {
		return nil, fmt.Errorf("bulk funding rate HTTP request failed: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("bulk funding rate read body failed: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("bulk funding rate API error: status=%d body=%s", resp.StatusCode, string(body))
	}

	var indices []binancePremiumIndex
	if err := json.Unmarshal(body, &indices); err != nil {
		return nil, fmt.Errorf("bulk funding rate JSON parse failed: %w", err)
	}

	results := make(map[string]*FundingRateInfo, len(indices))
	for _, idx := range indices {
		fundingRate, _ := strconv.ParseFloat(idx.LastFundingRate, 64)
		markPrice, _ := strconv.ParseFloat(idx.MarkPrice, 64)

		results[idx.Symbol] = &FundingRateInfo{
			Symbol:      idx.Symbol,
			FundingRate: fundingRate,
			FundingTime: time.UnixMilli(idx.NextFundingTime),
			MarkPrice:   markPrice,
		}
	}

	log.Debug().Int("count", len(results)).Msg("fetched bulk funding rates")

	return results, nil
}
