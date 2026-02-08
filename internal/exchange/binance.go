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
	binanceWSBaseURL        = "wss://stream.binance.com:9443/ws"
	binanceTestnetWSBaseURL = "wss://testnet.binance.vision/ws"

	binanceCombinedURL        = "wss://stream.binance.com:9443/stream?streams="
	binanceTestnetCombinedURL = "wss://testnet.binance.vision/stream?streams="

	initialBackoff = 1 * time.Second
	maxBackoff     = 60 * time.Second
	backoffFactor  = 2.0
)

type streamType int

const (
	streamTypeCandle streamType = iota
	streamTypeOrderBook
)

type streamSubscription struct {
	streamType streamType
	stream     string
	symbol     string
	interval   string
	handler    interface{}
}

type BinanceClient struct {
	testnet       bool
	conn          *websocket.Conn
	mu            sync.RWMutex
	done          chan struct{}
	subscriptions map[string]*streamSubscription
	connected     bool
	reconnecting  bool
	httpClient    *http.Client // reusable HTTP client with timeout for REST calls
}

func NewBinanceClient(testnet bool) *BinanceClient {
	return &BinanceClient{
		testnet:       testnet,
		done:          make(chan struct{}),
		subscriptions: make(map[string]*streamSubscription),
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

func (c *BinanceClient) combinedURL() string {
	if c.testnet {
		return binanceTestnetCombinedURL
	}
	return binanceCombinedURL
}

func (c *BinanceClient) connect() error {
	c.mu.Lock()
	streams := make([]string, 0, len(c.subscriptions))
	for stream := range c.subscriptions {
		streams = append(streams, stream)
	}
	c.mu.Unlock()

	if len(streams) == 0 {
		return nil
	}

	url := c.combinedURL() + strings.Join(streams, "/")
	conn, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		return fmt.Errorf("failed to connect to binance ws: %w", err)
	}

	c.mu.Lock()
	c.conn = conn
	c.connected = true
	c.mu.Unlock()

	log.Info().Int("streams", len(streams)).Msg("connected to binance combined stream")
	return nil
}

func (c *BinanceClient) reconnectWithBackoff() {
	c.mu.Lock()
	if c.reconnecting {
		c.mu.Unlock()
		return
	}
	c.reconnecting = true
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
			c.mu.Lock()
			c.reconnecting = false
			c.mu.Unlock()
			return
		default:
		}

		log.Info().Dur("backoff", backoff).Msg("attempting to reconnect to binance")

		if err := c.connect(); err != nil {
			log.Error().Err(err).Dur("backoff", backoff).Msg("reconnection failed, will retry")
			time.Sleep(backoff)
			backoff = time.Duration(math.Min(float64(backoff)*backoffFactor, float64(maxBackoff)))
			continue
		}

		c.mu.Lock()
		c.reconnecting = false
		c.mu.Unlock()

		go c.readLoop()
		return
	}
}

func (c *BinanceClient) ensureConnected() error {
	c.mu.RLock()
	connected := c.connected
	c.mu.RUnlock()

	if connected {
		return nil
	}

	if err := c.connect(); err != nil {
		return err
	}

	go c.readLoop()
	return nil
}

func (c *BinanceClient) addSubscriptionAndReconnect(sub *streamSubscription) error {
	c.mu.Lock()
	c.subscriptions[sub.stream] = sub
	wasConnected := c.connected
	if c.conn != nil {
		c.conn.Close()
		c.conn = nil
	}
	c.connected = false
	c.mu.Unlock()

	if wasConnected {
		time.Sleep(100 * time.Millisecond)
	}

	return c.ensureConnected()
}

func (c *BinanceClient) SubscribeCandles(symbol, interval string, handler CandleHandler) error {
	stream := fmt.Sprintf("%s@kline_%s", strings.ToLower(symbol), interval)

	sub := &streamSubscription{
		streamType: streamTypeCandle,
		stream:     stream,
		symbol:     symbol,
		interval:   interval,
		handler:    handler,
	}

	if err := c.addSubscriptionAndReconnect(sub); err != nil {
		return err
	}

	log.Info().Str("symbol", symbol).Str("interval", interval).Msg("subscribed to candles")
	return nil
}

func (c *BinanceClient) SubscribeOrderBook(symbol string, handler OrderBookHandler) error {
	stream := fmt.Sprintf("%s@depth5@100ms", strings.ToLower(symbol))

	sub := &streamSubscription{
		streamType:  streamTypeOrderBook,
		stream:      stream,
		symbol:      symbol,
		handler:     handler,
	}

	if err := c.addSubscriptionAndReconnect(sub); err != nil {
		return err
	}

	log.Info().Str("symbol", symbol).Msg("subscribed to orderbook")
	return nil
}

type combinedStreamMessage struct {
	Stream string          `json:"stream"`
	Data   json.RawMessage `json:"data"`
}

func (c *BinanceClient) readLoop() {
	for {
		select {
		case <-c.done:
			return
		default:
		}

		c.mu.RLock()
		conn := c.conn
		c.mu.RUnlock()

		if conn == nil {
			return
		}

		_, message, err := conn.ReadMessage()
		if err != nil {
			log.Error().Err(err).Msg("ws read error, initiating reconnect")
			go c.reconnectWithBackoff()
			return
		}

		var combined combinedStreamMessage
		if err := json.Unmarshal(message, &combined); err != nil {
			log.Warn().Err(err).Msg("failed to parse combined stream message")
			continue
		}

		c.mu.RLock()
		sub, exists := c.subscriptions[combined.Stream]
		c.mu.RUnlock()

		if !exists {
			log.Warn().Str("stream", combined.Stream).Msg("received message for unknown stream")
			continue
		}

		c.handleStreamMessage(sub, combined.Data)
	}
}

func (c *BinanceClient) handleStreamMessage(sub *streamSubscription, data json.RawMessage) {
	switch sub.streamType {
	case streamTypeCandle:
		candle, err := parseKlineMessage(data)
		if err != nil {
			log.Warn().Err(err).Msg("failed to parse kline message")
			return
		}
		if handler, ok := sub.handler.(CandleHandler); ok {
			handler(candle)
		}

	case streamTypeOrderBook:
		ob, err := parseDepthMessage(data, sub.symbol)
		if err != nil {
			log.Warn().Err(err).Msg("failed to parse depth message")
			return
		}
		if handler, ok := sub.handler.(OrderBookHandler); ok {
			handler(ob)
		}
	}
}

type binanceKlineEvent struct {
	EventType string       `json:"e"`
	EventTime int64        `json:"E"`
	Symbol    string       `json:"s"`
	Kline     binanceKline `json:"k"`
}

type binanceKline struct {
	StartTime    int64  `json:"t"`
	CloseTime    int64  `json:"T"`
	Symbol       string `json:"s"`
	Interval     string `json:"i"`
	FirstTradeID int64  `json:"f"`
	LastTradeID  int64  `json:"L"`
	Open         string `json:"o"`
	Close        string `json:"c"`
	High         string `json:"h"`
	Low          string `json:"l"`
	Volume       string `json:"v"`
	NumTrades    int64  `json:"n"`
	IsClosed     bool   `json:"x"`
	QuoteVolume  string `json:"q"`
	TakerBuyVol  string `json:"V"`
	TakerBuyQ    string `json:"Q"`
	Ignore       string `json:"B"`
}

func parseKlineMessage(data []byte) (Candle, error) {
	var event binanceKlineEvent
	if err := json.Unmarshal(data, &event); err != nil {
		return Candle{}, err
	}

	k := event.Kline

	open, _ := strconv.ParseFloat(k.Open, 64)
	high, _ := strconv.ParseFloat(k.High, 64)
	low, _ := strconv.ParseFloat(k.Low, 64)
	close, _ := strconv.ParseFloat(k.Close, 64)
	volume, _ := strconv.ParseFloat(k.Volume, 64)

	return Candle{
		Symbol:    k.Symbol,
		OpenTime:  time.UnixMilli(k.StartTime),
		CloseTime: time.UnixMilli(k.CloseTime),
		Open:      open,
		High:      high,
		Low:       low,
		Close:     close,
		Volume:    volume,
		IsClosed:  k.IsClosed,
	}, nil
}

type binanceDepthEvent struct {
	Bids [][]string `json:"bids"`
	Asks [][]string `json:"asks"`
}

func parseDepthMessage(data []byte, symbol string) (OrderBook, error) {
	var event binanceDepthEvent
	if err := json.Unmarshal(data, &event); err != nil {
		return OrderBook{}, err
	}

	ob := OrderBook{
		Symbol:    symbol,
		Timestamp: time.Now(),
		Bids:      make([]PriceLevel, len(event.Bids)),
		Asks:      make([]PriceLevel, len(event.Asks)),
	}

	for i, bid := range event.Bids {
		price, _ := strconv.ParseFloat(bid[0], 64)
		qty, _ := strconv.ParseFloat(bid[1], 64)
		ob.Bids[i] = PriceLevel{Price: price, Quantity: qty}
	}

	for i, ask := range event.Asks {
		price, _ := strconv.ParseFloat(ask[0], 64)
		qty, _ := strconv.ParseFloat(ask[1], 64)
		ob.Asks[i] = PriceLevel{Price: price, Quantity: qty}
	}

	return ob, nil
}

func (c *BinanceClient) Close() error {
	close(c.done)

	c.mu.Lock()
	defer c.mu.Unlock()

	if c.conn != nil {
		c.conn.Close()
		c.conn = nil
	}
	c.connected = false
	c.subscriptions = make(map[string]*streamSubscription)

	return nil
}

// ---------------------------------------------------------------------------
// Funding Rate REST Polling (Binance Futures API)
// ---------------------------------------------------------------------------

const (
	binanceFuturesBaseURL        = "https://fapi.binance.com"
	binanceFuturesTestnetBaseURL = "https://testnet.binancefuture.com"
)

func (c *BinanceClient) futuresBaseURL() string {
	if c.testnet {
		return binanceFuturesTestnetBaseURL
	}
	return binanceFuturesBaseURL
}

// binancePremiumIndex is the JSON response from GET /fapi/v1/premiumIndex.
type binancePremiumIndex struct {
	Symbol          string `json:"symbol"`
	MarkPrice       string `json:"markPrice"`
	LastFundingRate string `json:"lastFundingRate"`
	NextFundingTime int64  `json:"nextFundingTime"`
	Time            int64  `json:"time"`
}

// FetchFundingRate fetches the current funding rate for a single symbol
// from the Binance Futures premiumIndex endpoint (REST, not WebSocket).
func (c *BinanceClient) FetchFundingRate(symbol string) (*FundingRateInfo, error) {
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

// FetchFundingRates fetches funding rates for multiple symbols. Errors for
// individual symbols are logged but do not prevent other symbols from being
// fetched. Returns all successfully fetched rates.
func (c *BinanceClient) FetchFundingRates(symbols []string) (map[string]*FundingRateInfo, error) {
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

// FetchAllFundingRates fetches funding rates for ALL symbols in a single
// bulk request to GET /fapi/v1/premiumIndex (no symbol parameter). This
// is significantly faster than calling FetchFundingRate per-symbol, and
// the caller can filter by desired symbols.
func (c *BinanceClient) FetchAllFundingRates() (map[string]*FundingRateInfo, error) {
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
