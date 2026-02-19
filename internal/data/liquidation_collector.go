package data

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"github.com/rs/zerolog/log"
)

// LiquidationEvent represents a forced liquidation order
type LiquidationEvent struct {
	Symbol    string    `json:"s"`
	Side      string    `json:"S"` // SELL or BUY
	OrderType string    `json:"o"` // LIMIT or MARKET
	TimeInForce string  `json:"f"` // IOC, FOK, GTX
	Quantity  string    `json:"q"`
	Price     string    `json:"p"`
	AvgPrice  string    `json:"ap"`
	OrderStatus string  `json:"X"` // FILLED
	LastFilledQty string `json:"l"`
	FilledQty   string   `json:"z"`
	LastFilledPrice string `json:"L"`
	Time        int64    `json:"T"`
}

// OpenInterestData represents open interest for a symbol
type OpenInterestData struct {
	Symbol       string `json:"symbol"`
	OpenInterest string `json:"openInterest"`
	Time         int64  `json:"time"`
}

// LiquidationCollector collects liquidation and open interest data
type LiquidationCollector struct {
	db       *sql.DB
	hubURL   string
	symbols  []string
	wsConn   *websocket.Conn
	mu       sync.Mutex
	ctx      context.Context
	cancel   context.CancelFunc
}

// NewLiquidationCollector creates a new liquidation data collector
func NewLiquidationCollector(dbPath string, hubURL string, symbols []string) (*LiquidationCollector, error) {
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return nil, fmt.Errorf("open sqlite: %w", err)
	}

	if err := createLiquidationTables(db); err != nil {
		return nil, fmt.Errorf("create tables: %w", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	
	return &LiquidationCollector{
		db:      db,
		hubURL:  hubURL,
		symbols: symbols,
		ctx:     ctx,
		cancel:  cancel,
	}, nil
}

// Start begins data collection
func (lc *LiquidationCollector) Start() error {
	// Start liquidation WebSocket
	go lc.startLiquidationStream()
	
	// Start open interest polling
	go lc.startOpenInterestPolling()
	
	log.Info().Msg("Liquidation collector started")
	return nil
}

// Stop stops data collection
func (lc *LiquidationCollector) Stop() {
	lc.cancel()
	if lc.wsConn != nil {
		lc.wsConn.Close()
	}
	lc.db.Close()
	log.Info().Msg("Liquidation collector stopped")
}

func (lc *LiquidationCollector) startLiquidationStream() {
	backoff := time.Second
	maxBackoff := 60 * time.Second

	for {
		select {
		case <-lc.ctx.Done():
			return
		default:
		}

		if err := lc.connectLiquidationWS(); err != nil {
			log.Error().Err(err).Dur("backoff", backoff).Msg("Failed to connect liquidation WS, retrying")
			time.Sleep(backoff)
			if backoff < maxBackoff {
				backoff *= 2
			}
			continue
		}

		backoff = time.Second // Reset on successful connection
	}
}

func (lc *LiquidationCollector) connectLiquidationWS() error {
	// Use local hub if configured, otherwise connect directly to Binance
	var url string
	if lc.hubURL != "" {
		// Subscribe to liquidation stream via local hub
		url = fmt.Sprintf("ws://%s", lc.hubURL)
		log.Info().Str("hub_url", lc.hubURL).Msg("Connecting to liquidation stream via local hub")
	} else {
		// Connect directly to Binance
		url = "wss://fstream.binance.com/ws/!forceOrder@arr"
		log.Info().Msg("Connecting directly to Binance liquidation stream")
	}
	
	dialer := websocket.DefaultDialer
	conn, _, err := dialer.Dial(url, nil)
	if err != nil {
		return fmt.Errorf("dial websocket: %w", err)
	}

	lc.mu.Lock()
	lc.wsConn = conn
	lc.mu.Unlock()

	log.Info().Str("url", url).Msg("Connected to liquidation stream")
	
	// If using hub, subscribe to liquidation stream
	if lc.hubURL != "" {
		subscribeMsg := map[string]interface{}{
			"method": "SUBSCRIBE",
			"params": []string{"!forceOrder@arr"},
			"id":     1,
		}
		if err := conn.WriteJSON(subscribeMsg); err != nil {
			return fmt.Errorf("subscribe to liquidation stream: %w", err)
		}
		log.Info().Msg("Subscribed to !forceOrder@arr via hub")
	}

	// Read messages
	for {
		select {
		case <-lc.ctx.Done():
			return nil
		default:
		}

		conn.SetReadDeadline(time.Now().Add(90 * time.Second))
		_, message, err := conn.ReadMessage()
		if err != nil {
			return fmt.Errorf("read message: %w", err)
		}

		if err := lc.processLiquidationMessage(message); err != nil {
			log.Error().Err(err).Msg("Failed to process liquidation message")
		}
	}
}

func (lc *LiquidationCollector) processLiquidationMessage(message []byte) error {
	var wsMessage struct {
		Stream string          `json:"stream"`
		Data   LiquidationEvent `json:"data"`
	}

	if err := json.Unmarshal(message, &wsMessage); err != nil {
		return fmt.Errorf("unmarshal message: %w", err)
	}

	// Filter for our symbols
	if !lc.isTargetSymbol(wsMessage.Data.Symbol) {
		return nil
	}

	return lc.storeLiquidation(wsMessage.Data)
}

func (lc *LiquidationCollector) isTargetSymbol(symbol string) bool {
	for _, s := range lc.symbols {
		if s == symbol {
			return true
		}
	}
	return false
}

func (lc *LiquidationCollector) storeLiquidation(event LiquidationEvent) error {
	query := `
		INSERT OR REPLACE INTO liquidations 
		(timestamp, symbol, side, quantity, price, avg_price, filled_qty) 
		VALUES (?, ?, ?, ?, ?, ?, ?)`

	quantity, _ := strconv.ParseFloat(event.Quantity, 64)
	price, _ := strconv.ParseFloat(event.Price, 64)
	avgPrice, _ := strconv.ParseFloat(event.AvgPrice, 64)
	filledQty, _ := strconv.ParseFloat(event.FilledQty, 64)

	_, err := lc.db.Exec(query, event.Time, event.Symbol, event.Side, 
		quantity, price, avgPrice, filledQty)
	if err != nil {
		return fmt.Errorf("insert liquidation: %w", err)
	}

	log.Debug().
		Str("symbol", event.Symbol).
		Str("side", event.Side).
		Float64("quantity", quantity).
		Float64("price", price).
		Msg("Stored liquidation event")

	return nil
}

func (lc *LiquidationCollector) startOpenInterestPolling() {
	ticker := time.NewTicker(5 * time.Minute)
	defer ticker.Stop()

	// Initial collection
	lc.collectOpenInterest()

	for {
		select {
		case <-lc.ctx.Done():
			return
		case <-ticker.C:
			lc.collectOpenInterest()
		}
	}
}

func (lc *LiquidationCollector) collectOpenInterest() {
	for _, symbol := range lc.symbols {
		if err := lc.fetchOpenInterest(symbol); err != nil {
			log.Error().Err(err).Str("symbol", symbol).Msg("Failed to fetch open interest")
		}
		time.Sleep(100 * time.Millisecond) // Rate limit
	}
}

func (lc *LiquidationCollector) fetchOpenInterest(symbol string) error {
	url := fmt.Sprintf("https://fapi.binance.com/fapi/v1/openInterest?symbol=%s", symbol)
	
	resp, err := http.Get(url)
	if err != nil {
		return fmt.Errorf("http get: %w", err)
	}
	defer resp.Body.Close()

	var oi OpenInterestData
	if err := json.NewDecoder(resp.Body).Decode(&oi); err != nil {
		return fmt.Errorf("decode response: %w", err)
	}

	return lc.storeOpenInterest(oi)
}

func (lc *LiquidationCollector) storeOpenInterest(oi OpenInterestData) error {
	query := `
		INSERT OR REPLACE INTO open_interest 
		(timestamp, symbol, open_interest) 
		VALUES (?, ?, ?)`

	openInterest, _ := strconv.ParseFloat(oi.OpenInterest, 64)
	timestamp := time.Now().UnixMilli()

	_, err := lc.db.Exec(query, timestamp, oi.Symbol, openInterest)
	if err != nil {
		return fmt.Errorf("insert open interest: %w", err)
	}

	log.Debug().
		Str("symbol", oi.Symbol).
		Float64("open_interest", openInterest).
		Msg("Stored open interest")

	return nil
}

func createLiquidationTables(db *sql.DB) error {
	queries := []string{
		`CREATE TABLE IF NOT EXISTS liquidations (
			timestamp BIGINT,
			symbol TEXT,
			side TEXT,
			quantity REAL,
			price REAL,
			avg_price REAL,
			filled_qty REAL,
			PRIMARY KEY (timestamp, symbol)
		)`,
		`CREATE TABLE IF NOT EXISTS open_interest (
			timestamp BIGINT,
			symbol TEXT,
			open_interest REAL,
			PRIMARY KEY (timestamp, symbol)
		)`,
		`CREATE INDEX IF NOT EXISTS idx_liquidations_symbol_time ON liquidations(symbol, timestamp)`,
		`CREATE INDEX IF NOT EXISTS idx_oi_symbol_time ON open_interest(symbol, timestamp)`,
	}

	for _, query := range queries {
		if _, err := db.Exec(query); err != nil {
			return fmt.Errorf("exec query: %w", err)
		}
	}

	return nil
}