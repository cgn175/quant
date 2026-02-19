package main

import (
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/gorilla/websocket"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"github.com/spf13/cobra"
)

const (
	binanceCombinedURL        = "wss://stream.binance.com:9443/stream?streams="
	binanceTestnetCombinedURL = "wss://testnet.binance.vision/stream?streams="
	binanceFuturesURL         = "wss://fstream.binance.com/ws/!forceOrder@arr"
	binanceFuturesTestnetURL  = "wss://testnet.binancefuture.com/ws/!forceOrder@arr"

	initialBackoff = 1 * time.Second
	maxBackoff     = 60 * time.Second
	backoffFactor  = 2.0

	wsReadDeadline = 90 * time.Second
	wsPingInterval = 30 * time.Second
	wsPongTimeout  = 10 * time.Second

	clientSendBuf = 256
)

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool { return true },
}

// Hub maintains a single upstream Binance connection and fans out to local clients.
type Hub struct {
	testnet bool
	port    int
	mu      sync.RWMutex

	// Binance upstream (spot/futures combined streams)
	upstreamConn *websocket.Conn
	upstreamGen  uint64
	connectMu    sync.Mutex
	reconnecting bool
	
	// Liquidation stream (separate connection)
	liqConn      *websocket.Conn
	liqGen       uint64
	liqMu        sync.Mutex
	liqActive    bool
	streams      map[string]bool // union of all client subscriptions

	// Local clients
	clients map[*hubClient]bool

	done chan struct{}
}

type hubClient struct {
	conn    *websocket.Conn
	hub     *Hub
	streams map[string]bool
	send    chan []byte
}

// clientMessage is the JSON protocol from client → hub.
type clientMessage struct {
	Action string `json:"action"`
	Stream string `json:"stream"`
}

// broadcastMessage is the JSON protocol from hub → client (same as Binance combined stream).
type broadcastMessage struct {
	Stream string          `json:"stream"`
	Data   json.RawMessage `json:"data"`
}

func newHub(testnet bool, port int) *Hub {
	return &Hub{
		testnet: testnet,
		port:    port,
		streams: make(map[string]bool),
		clients: make(map[*hubClient]bool),
		done:    make(chan struct{}),
	}
}

func (h *Hub) combinedURL() string {
	if h.testnet {
		return binanceTestnetCombinedURL
	}
	return binanceCombinedURL
}

// recomputeStreams rebuilds h.streams from the union of all client subscriptions.
// Caller must hold h.mu write lock.
func (h *Hub) recomputeStreams() map[string]bool {
	merged := make(map[string]bool)
	for c := range h.clients {
		for s := range c.streams {
			merged[s] = true
		}
	}
	return merged
}

// connectUpstream dials Binance with the current stream set.
// Caller must hold h.connectMu.
func (h *Hub) connectUpstream() error {
	h.mu.RLock()
	streams := make([]string, 0, len(h.streams))
	for s := range h.streams {
		streams = append(streams, s)
	}
	h.mu.RUnlock()

	if len(streams) == 0 {
		log.Info().Msg("no streams to subscribe — skipping upstream connect")
		return nil
	}

	url := h.combinedURL() + strings.Join(streams, "/")
	conn, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		return fmt.Errorf("binance dial: %w", err)
	}

	conn.SetPongHandler(func(string) error {
		conn.SetReadDeadline(time.Now().Add(wsReadDeadline))
		log.Debug().Msg("upstream pong received")
		return nil
	})
	conn.SetReadDeadline(time.Now().Add(wsReadDeadline))

	h.mu.Lock()
	if h.upstreamConn != nil {
		h.upstreamConn.Close()
	}
	h.upstreamConn = conn
	h.upstreamGen++
	gen := h.upstreamGen
	h.mu.Unlock()

	log.Info().Int("streams", len(streams)).Uint64("gen", gen).Msg("connected to binance")

	go h.upstreamReadLoop(conn, gen)
	go h.upstreamPingLoop(conn, gen)

	return nil
}

// reconnectUpstream reconnects with exponential backoff.
func (h *Hub) reconnectUpstream() {
	h.connectMu.Lock()
	defer h.connectMu.Unlock()

	h.mu.Lock()
	if h.reconnecting {
		h.mu.Unlock()
		return
	}
	h.reconnecting = true
	if h.upstreamConn != nil {
		h.upstreamConn.Close()
		h.upstreamConn = nil
	}
	h.mu.Unlock()

	backoff := initialBackoff
	for {
		select {
		case <-h.done:
			h.mu.Lock()
			h.reconnecting = false
			h.mu.Unlock()
			return
		default:
		}

		log.Info().Dur("backoff", backoff).Msg("reconnecting to binance")
		if err := h.connectUpstream(); err != nil {
			log.Error().Err(err).Dur("backoff", backoff).Msg("reconnect failed, retrying")
			time.Sleep(backoff)
			backoff = time.Duration(math.Min(float64(backoff)*backoffFactor, float64(maxBackoff)))
			continue
		}

		h.mu.Lock()
		h.reconnecting = false
		h.mu.Unlock()
		return
	}
}

// refreshUpstream closes the current upstream and reconnects with the latest stream set.
func (h *Hub) refreshUpstream() {
	h.connectMu.Lock()
	defer h.connectMu.Unlock()

	h.mu.Lock()
	if h.upstreamConn != nil {
		h.upstreamConn.Close()
		h.upstreamConn = nil
	}
	h.mu.Unlock()

	// Small delay so the old readLoop can exit cleanly.
	time.Sleep(100 * time.Millisecond)

	if err := h.connectUpstream(); err != nil {
		log.Error().Err(err).Msg("refresh upstream failed, starting backoff reconnect")
		// Release connectMu before calling reconnectUpstream (which acquires it).
		go h.reconnectUpstream()
	}
}

func (h *Hub) upstreamReadLoop(conn *websocket.Conn, gen uint64) {
	for {
		select {
		case <-h.done:
			return
		default:
		}

		_, msg, err := conn.ReadMessage()
		if err != nil {
			h.mu.RLock()
			current := h.upstreamConn == conn && h.upstreamGen == gen
			h.mu.RUnlock()
			if current {
				log.Error().Err(err).Uint64("gen", gen).Msg("upstream read error, reconnecting")
				go h.reconnectUpstream()
			} else {
				log.Debug().Uint64("gen", gen).Msg("stale upstream readLoop exiting")
			}
			return
		}

		conn.SetReadDeadline(time.Now().Add(wsReadDeadline))

		// Parse the combined stream message to get the stream name.
		var combined broadcastMessage
		if err := json.Unmarshal(msg, &combined); err != nil {
			log.Warn().Err(err).Msg("failed to parse upstream message")
			continue
		}

		// Fan out to subscribed clients.
		h.mu.RLock()
		for c := range h.clients {
			if c.streams[combined.Stream] {
				select {
				case c.send <- msg:
				default:
					log.Warn().Str("stream", combined.Stream).Msg("client send buffer full, dropping")
				}
			}
		}
		h.mu.RUnlock()
	}
}

func (h *Hub) upstreamPingLoop(conn *websocket.Conn, gen uint64) {
	ticker := time.NewTicker(wsPingInterval)
	defer ticker.Stop()

	for {
		select {
		case <-h.done:
			return
		case <-ticker.C:
			h.mu.RLock()
			current := h.upstreamConn == conn && h.upstreamGen == gen
			h.mu.RUnlock()
			if !current {
				log.Debug().Uint64("gen", gen).Msg("stale upstream pingLoop exiting")
				return
			}
			if err := conn.WriteControl(websocket.PingMessage, nil, time.Now().Add(wsPongTimeout)); err != nil {
				log.Warn().Err(err).Uint64("gen", gen).Msg("upstream ping failed, reconnecting")
				conn.Close()
				go h.reconnectUpstream()
				return
			}
			log.Debug().Uint64("gen", gen).Msg("upstream ping sent")
		}
	}
}

// ---------- liquidation stream handling ----------

func (h *Hub) startLiquidationStream() {
	h.liqMu.Lock()
	defer h.liqMu.Unlock()
	
	url := binanceFuturesURL
	if h.testnet {
		url = binanceFuturesTestnetURL
	}
	
	conn, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		log.Error().Err(err).Msg("failed to connect liquidation stream")
		return
	}
	
	conn.SetPongHandler(func(string) error {
		conn.SetReadDeadline(time.Now().Add(wsReadDeadline))
		return nil
	})
	conn.SetReadDeadline(time.Now().Add(wsReadDeadline))
	
	if h.liqConn != nil {
		h.liqConn.Close()
	}
	h.liqConn = conn
	h.liqGen++
	gen := h.liqGen
	
	log.Info().Uint64("gen", gen).Msg("connected to liquidation stream")
	
	go h.liqReadLoop(conn, gen)
	go h.liqPingLoop(conn, gen)
}

func (h *Hub) liqReadLoop(conn *websocket.Conn, gen uint64) {
	for {
		select {
		case <-h.done:
			return
		default:
		}
		
		_, msg, err := conn.ReadMessage()
		if err != nil {
			h.liqMu.Lock()
			current := h.liqConn == conn && h.liqGen == gen
			h.liqMu.Unlock()
			if current {
				log.Error().Err(err).Uint64("gen", gen).Msg("liquidation read error, reconnecting")
				time.Sleep(5 * time.Second)
				go h.startLiquidationStream()
			}
			return
		}
		
		conn.SetReadDeadline(time.Now().Add(wsReadDeadline))
		
		// Wrap in combined stream format
		wrapped := broadcastMessage{
			Stream: "!forceOrder@arr",
			Data:   json.RawMessage(msg),
		}
		wrappedMsg, _ := json.Marshal(wrapped)
		
		// Broadcast to subscribed clients
		h.mu.RLock()
		for c := range h.clients {
			if c.streams["!forceOrder@arr"] {
				select {
				case c.send <- wrappedMsg:
				default:
					log.Warn().Msg("client send buffer full, dropping liquidation message")
				}
			}
		}
		h.mu.RUnlock()
	}
}

func (h *Hub) liqPingLoop(conn *websocket.Conn, gen uint64) {
	ticker := time.NewTicker(wsPingInterval)
	defer ticker.Stop()
	
	for {
		select {
		case <-h.done:
			return
		case <-ticker.C:
			h.liqMu.Lock()
			current := h.liqConn == conn && h.liqGen == gen
			h.liqMu.Unlock()
			if !current {
				return
			}
			if err := conn.WriteControl(websocket.PingMessage, nil, time.Now().Add(wsPongTimeout)); err != nil {
				log.Warn().Err(err).Msg("liquidation ping failed")
				conn.Close()
				go h.startLiquidationStream()
				return
			}
		}
	}
}

// ---------- local client handling ----------

func (h *Hub) handleWS(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Error().Err(err).Msg("websocket upgrade failed")
		return
	}

	c := &hubClient{
		conn:    conn,
		hub:     h,
		streams: make(map[string]bool),
		send:    make(chan []byte, clientSendBuf),
	}

	h.mu.Lock()
	h.clients[c] = true
	h.mu.Unlock()

	log.Info().Str("remote", conn.RemoteAddr().String()).Msg("client connected")

	go c.writePump()
	go c.readPump()
}

func (c *hubClient) readPump() {
	defer c.cleanup()

	c.conn.SetReadDeadline(time.Now().Add(wsReadDeadline))
	c.conn.SetPongHandler(func(string) error {
		c.conn.SetReadDeadline(time.Now().Add(wsReadDeadline))
		return nil
	})

	for {
		_, msg, err := c.conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseNormalClosure) {
				log.Warn().Err(err).Msg("client read error")
			}
			return
		}

		var cm clientMessage
		if err := json.Unmarshal(msg, &cm); err != nil {
			log.Warn().Err(err).Msg("invalid client message")
			continue
		}

		switch cm.Action {
		case "subscribe":
			c.subscribe(cm.Stream)
		case "unsubscribe":
			c.unsubscribe(cm.Stream)
		default:
			log.Warn().Str("action", cm.Action).Msg("unknown client action")
		}
	}
}

func (c *hubClient) writePump() {
	ticker := time.NewTicker(wsPingInterval)
	defer func() {
		ticker.Stop()
		c.conn.Close()
	}()

	for {
		select {
		case msg, ok := <-c.send:
			if !ok {
				c.conn.WriteMessage(websocket.CloseMessage, nil)
				return
			}
			c.conn.SetWriteDeadline(time.Now().Add(wsPongTimeout))
			if err := c.conn.WriteMessage(websocket.TextMessage, msg); err != nil {
				return
			}
		case <-ticker.C:
			c.conn.SetWriteDeadline(time.Now().Add(wsPongTimeout))
			if err := c.conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}

func (c *hubClient) subscribe(stream string) {
	if stream == "" {
		return
	}
	h := c.hub

	// Handle liquidation stream separately
	if stream == "!forceOrder@arr" {
		h.liqMu.Lock()
		c.streams[stream] = true
		needStart := !h.liqActive
		h.liqActive = true
		h.liqMu.Unlock()
		
		log.Info().Str("stream", stream).Bool("new_connection", needStart).Msg("client subscribed to liquidation")
		
		if needStart {
			go h.startLiquidationStream()
		}
		return
	}

	h.mu.Lock()
	c.streams[stream] = true
	needRefresh := !h.streams[stream]
	h.streams = h.recomputeStreams()
	h.mu.Unlock()

	log.Info().Str("stream", stream).Bool("new_upstream", needRefresh).Msg("client subscribed")

	if needRefresh {
		go h.refreshUpstream()
	}
}

func (c *hubClient) unsubscribe(stream string) {
	if stream == "" {
		return
	}
	h := c.hub

	h.mu.Lock()
	delete(c.streams, stream)
	oldHas := h.streams[stream]
	h.streams = h.recomputeStreams()
	removed := oldHas && !h.streams[stream]
	h.mu.Unlock()

	log.Info().Str("stream", stream).Bool("removed_upstream", removed).Msg("client unsubscribed")

	if removed {
		go h.refreshUpstream()
	}
}

func (c *hubClient) cleanup() {
	h := c.hub
	h.mu.Lock()
	delete(h.clients, c)
	h.streams = h.recomputeStreams()
	h.mu.Unlock()

	close(c.send)
	c.conn.Close()
	log.Info().Str("remote", c.conn.RemoteAddr().String()).Msg("client disconnected")
}

// ---------- main ----------

var (
	port    int
	testnet bool

	rootCmd = &cobra.Command{
		Use:   "wshub",
		Short: "Central WebSocket hub — one Binance connection, many local clients",
		RunE:  run,
	}
)

func init() {
	rootCmd.Flags().IntVar(&port, "port", 9090, "local WebSocket server port")
	rootCmd.Flags().BoolVar(&testnet, "testnet", false, "use Binance testnet")
}

func run(cmd *cobra.Command, args []string) error {
	h := newHub(testnet, port)

	mux := http.NewServeMux()
	mux.HandleFunc("/ws", h.handleWS)

	srv := &http.Server{
		Addr:    fmt.Sprintf(":%d", port),
		Handler: mux,
	}

	go func() {
		log.Info().Int("port", port).Bool("testnet", testnet).Msg("wshub listening")
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatal().Err(err).Msg("http server error")
		}
	}()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig

	log.Info().Msg("shutting down wshub")
	close(h.done)

	h.mu.Lock()
	if h.upstreamConn != nil {
		h.upstreamConn.Close()
	}
	for c := range h.clients {
		c.conn.Close()
	}
	h.mu.Unlock()

	srv.Close()
	return nil
}

func main() {
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stderr, TimeFormat: "15:04:05"})
	zerolog.SetGlobalLevel(zerolog.InfoLevel)

	if err := rootCmd.Execute(); err != nil {
		log.Fatal().Err(err).Msg("failed to execute")
	}
}
