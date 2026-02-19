package data

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"math"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"github.com/rs/zerolog/log"
)

// OrderFlowCollector collects order flow imbalance data
type OrderFlowCollector struct {
	db         *sql.DB
	hubURL     string
	symbols    []string
	ctx        context.Context
	cancel     context.CancelFunc
	mu         sync.Mutex
	
	// Per-symbol state
	deltas     map[string]*DeltaState
}

type DeltaState struct {
	delta1s    float64
	delta5s    float64
	delta1m    float64
	cvd        float64
	lastUpdate time.Time
}

type aggTrade struct {
	Symbol       string  `json:"s"`
	Price        string  `json:"p"`
	Quantity     string  `json:"q"`
	IsBuyerMaker bool    `json:"m"`
	Timestamp    int64   `json:"T"`
}

func NewOrderFlowCollector(dbPath, hubURL string, symbols []string) (*OrderFlowCollector, error) {
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return nil, fmt.Errorf("open sqlite: %w", err)
	}

	if err := createOrderFlowTables(db); err != nil {
		return nil, fmt.Errorf("create tables: %w", err)
	}

	ctx, cancel := context.WithCancel(context.Background())

	return &OrderFlowCollector{
		db:      db,
		hubURL:  hubURL,
		symbols: symbols,
		ctx:     ctx,
		cancel:  cancel,
		deltas:  make(map[string]*DeltaState),
	}, nil
}

func createOrderFlowTables(db *sql.DB) error {
	schema := `
	CREATE TABLE IF NOT EXISTS order_flow (
		timestamp INTEGER NOT NULL,
		symbol TEXT NOT NULL,
		window_size INTEGER NOT NULL,
		delta REAL NOT NULL,
		cvd REAL NOT NULL,
		volume REAL NOT NULL,
		PRIMARY KEY (timestamp, symbol, window_size)
	);
	CREATE INDEX IF NOT EXISTS idx_order_flow_symbol_time ON order_flow(symbol, timestamp);
	`
	_, err := db.Exec(schema)
	return err
}

func (ofc *OrderFlowCollector) Start() error {
	ofc.mu.Lock()
	for _, symbol := range ofc.symbols {
		ofc.deltas[symbol] = &DeltaState{}
	}
	ofc.mu.Unlock()

	for _, symbol := range ofc.symbols {
		go ofc.startTradeStream(symbol)
	}

	go ofc.persistLoop()
	return nil
}

func (ofc *OrderFlowCollector) startTradeStream(symbol string) {
	backoff := time.Second
	for {
		select {
		case <-ofc.ctx.Done():
			return
		default:
		}

		if err := ofc.connectTradeStream(symbol); err != nil {
			log.Error().Err(err).Str("symbol", symbol).Dur("backoff", backoff).Msg("trade stream error, retrying")
			time.Sleep(backoff)
			if backoff < 60*time.Second {
				backoff *= 2
			}
			continue
		}
		backoff = time.Second
	}
}

func (ofc *OrderFlowCollector) connectTradeStream(symbol string) error {
	url := fmt.Sprintf("ws://%s", ofc.hubURL)
	conn, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		return fmt.Errorf("dial: %w", err)
	}
	defer conn.Close()

	// Subscribe to aggTrade
	stream := fmt.Sprintf("%s@aggTrade", symbol)
	subscribeMsg := map[string]interface{}{
		"action": "subscribe",
		"stream": stream,
	}
	if err := conn.WriteJSON(subscribeMsg); err != nil {
		return fmt.Errorf("subscribe: %w", err)
	}

	log.Info().Str("symbol", symbol).Msg("subscribed to aggTrade")

	for {
		select {
		case <-ofc.ctx.Done():
			return nil
		default:
		}

		_, msg, err := conn.ReadMessage()
		if err != nil {
			return fmt.Errorf("read: %w", err)
		}

		var wrapper struct {
			Stream string          `json:"stream"`
			Data   json.RawMessage `json:"data"`
		}
		if err := json.Unmarshal(msg, &wrapper); err != nil {
			continue
		}

		var trade aggTrade
		if err := json.Unmarshal(wrapper.Data, &trade); err != nil {
			continue
		}

		ofc.processTrade(&trade)
	}
}

func (ofc *OrderFlowCollector) processTrade(trade *aggTrade) {
	ofc.mu.Lock()
	defer ofc.mu.Unlock()

	state, ok := ofc.deltas[trade.Symbol]
	if !ok {
		return
	}

	// Parse quantity
	var qty float64
	fmt.Sscanf(trade.Quantity, "%f", &qty)

	// Calculate delta
	delta := qty
	if trade.IsBuyerMaker {
		delta = -qty // Sell at bid
	}

	// Update windows
	state.delta1s += delta
	state.delta5s += delta
	state.delta1m += delta
	state.cvd += delta
	state.lastUpdate = time.Now()
}

func (ofc *OrderFlowCollector) persistLoop() {
	ticker1s := time.NewTicker(1 * time.Second)
	ticker5s := time.NewTicker(5 * time.Second)
	ticker1m := time.NewTicker(1 * time.Minute)
	defer ticker1s.Stop()
	defer ticker5s.Stop()
	defer ticker1m.Stop()

	for {
		select {
		case <-ofc.ctx.Done():
			return
		case <-ticker1s.C:
			ofc.persist(1)
		case <-ticker5s.C:
			ofc.persist(5)
		case <-ticker1m.C:
			ofc.persist(60)
		}
	}
}

func (ofc *OrderFlowCollector) persist(windowSize int) {
	ofc.mu.Lock()
	defer ofc.mu.Unlock()

	now := time.Now().Unix()
	for symbol, state := range ofc.deltas {
		var delta float64
		switch windowSize {
		case 1:
			delta = state.delta1s
			state.delta1s = 0
		case 5:
			delta = state.delta5s
			state.delta5s = 0
		case 60:
			delta = state.delta1m
			state.delta1m = 0
		}

		if delta == 0 {
			continue
		}

		_, err := ofc.db.Exec(`
			INSERT INTO order_flow (timestamp, symbol, window_size, delta, cvd, volume)
			VALUES (?, ?, ?, ?, ?, ?)
		`, now, symbol, windowSize, delta, state.cvd, math.Abs(delta))

		if err != nil {
			log.Error().Err(err).Str("symbol", symbol).Msg("failed to persist order flow")
		}
	}
}

// GetOrderFlowDelta returns the current 5-second delta for a symbol.
// Returns ok=false if the symbol is not tracked or data is stale.
func (ofc *OrderFlowCollector) GetOrderFlowDelta(symbol string) (delta5s float64, ok bool) {
	ofc.mu.Lock()
	defer ofc.mu.Unlock()

	state, exists := ofc.deltas[symbol]
	if !exists {
		return 0, false
	}

	// Consider data stale if last update was more than 10 seconds ago
	if time.Since(state.lastUpdate) > 10*time.Second {
		return 0, false
	}

	return state.delta5s, true
}

func (ofc *OrderFlowCollector) Stop() error {
	ofc.cancel()
	return ofc.db.Close()
}

