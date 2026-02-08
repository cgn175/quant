// Package data provides candle storage with SQLite persistence.
package data

import (
	"database/sql"
	"fmt"
	"sync"
	"time"

	_ "modernc.org/sqlite"

	"github.com/cgn175/quant-bot/internal/exchange"
	"github.com/rs/zerolog/log"
)

// SQLiteStore wraps an in-memory CandleStore with SQLite persistence.
// On startup it loads historical candles from SQLite. New candles are
// written to both the in-memory store and SQLite.
type SQLiteStore struct {
	mem     *CandleStore
	db      *sql.DB
	mu      sync.Mutex // protects db writes
	dbPath  string
	maxRows int // max candles per symbol in DB (older ones pruned)
}

// SQLiteConfig holds configuration for the SQLite store.
type SQLiteConfig struct {
	DBPath     string // Path to SQLite database file
	MaxCandles int    // Max candles per symbol to keep in memory
	MaxDBRows  int    // Max candles per symbol in DB (0 = unlimited)
}

// NewSQLiteStore creates a new SQLite-backed candle store.
// If the database doesn't exist it will be created.
func NewSQLiteStore(cfg SQLiteConfig) (*SQLiteStore, error) {
	if cfg.DBPath == "" {
		cfg.DBPath = "candles.db"
	}
	if cfg.MaxCandles == 0 {
		cfg.MaxCandles = 500
	}
	if cfg.MaxDBRows == 0 {
		cfg.MaxDBRows = 2000 // ~333 days of 4h candles per symbol
	}

	db, err := sql.Open("sqlite", cfg.DBPath)
	if err != nil {
		return nil, fmt.Errorf("open sqlite: %w", err)
	}

	// Enable WAL mode for better concurrent read/write
	if _, err := db.Exec("PRAGMA journal_mode=WAL"); err != nil {
		db.Close()
		return nil, fmt.Errorf("set WAL mode: %w", err)
	}

	// Create table if not exists
	createSQL := `
		CREATE TABLE IF NOT EXISTS candles (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			symbol TEXT NOT NULL,
			open_time INTEGER NOT NULL,
			close_time INTEGER NOT NULL,
			open REAL NOT NULL,
			high REAL NOT NULL,
			low REAL NOT NULL,
			close REAL NOT NULL,
			volume REAL NOT NULL,
			is_closed INTEGER NOT NULL,
			created_at INTEGER NOT NULL,
			UNIQUE(symbol, open_time)
		);
		CREATE INDEX IF NOT EXISTS idx_candles_symbol_time ON candles(symbol, open_time DESC);
	`
	if _, err := db.Exec(createSQL); err != nil {
		db.Close()
		return nil, fmt.Errorf("create table: %w", err)
	}

	store := &SQLiteStore{
		mem:     NewCandleStore(cfg.MaxCandles),
		db:      db,
		dbPath:  cfg.DBPath,
		maxRows: cfg.MaxDBRows,
	}

	return store, nil
}

// LoadHistory loads historical candles from SQLite for the given symbols.
// This should be called once at startup after creating the store.
func (s *SQLiteStore) LoadHistory(symbols []string) error {
	for _, sym := range symbols {
		candles, err := s.loadFromDB(sym, s.mem.maxSize)
		if err != nil {
			return fmt.Errorf("load history for %s: %w", sym, err)
		}

		// Add to in-memory store (oldest first for proper ordering)
		for _, c := range candles {
			s.mem.Add(c)
		}

		log.Info().
			Str("symbol", sym).
			Int("loaded", len(candles)).
			Msg("loaded historical candles from SQLite")
	}
	return nil
}

// loadFromDB retrieves the most recent N candles for a symbol from SQLite.
// Returns candles in chronological order (oldest first).
func (s *SQLiteStore) loadFromDB(symbol string, limit int) ([]exchange.Candle, error) {
	query := `
		SELECT symbol, open_time, close_time, open, high, low, close, volume, is_closed
		FROM candles
		WHERE symbol = ?
		ORDER BY open_time DESC
		LIMIT ?
	`
	rows, err := s.db.Query(query, symbol, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var candles []exchange.Candle
	for rows.Next() {
		var c exchange.Candle
		var openTime, closeTime int64
		var isClosed int

		if err := rows.Scan(
			&c.Symbol,
			&openTime,
			&closeTime,
			&c.Open,
			&c.High,
			&c.Low,
			&c.Close,
			&c.Volume,
			&isClosed,
		); err != nil {
			return nil, err
		}

		c.OpenTime = time.UnixMilli(openTime)
		c.CloseTime = time.UnixMilli(closeTime)
		c.IsClosed = isClosed != 0
		candles = append(candles, c)
	}

	// Reverse to get chronological order (oldest first)
	for i, j := 0, len(candles)-1; i < j; i, j = i+1, j-1 {
		candles[i], candles[j] = candles[j], candles[i]
	}

	return candles, rows.Err()
}

// Add adds a candle to both the in-memory store and SQLite.
// Only closed candles are persisted to SQLite.
func (s *SQLiteStore) Add(candle exchange.Candle) {
	// Always update in-memory store (for real-time updates)
	s.mem.Add(candle)

	// Only persist closed candles to SQLite
	if !candle.IsClosed {
		return
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	// Upsert: INSERT OR REPLACE
	insertSQL := `
		INSERT OR REPLACE INTO candles 
		(symbol, open_time, close_time, open, high, low, close, volume, is_closed, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
	`
	isClosed := 0
	if candle.IsClosed {
		isClosed = 1
	}

	_, err := s.db.Exec(insertSQL,
		candle.Symbol,
		candle.OpenTime.UnixMilli(),
		candle.CloseTime.UnixMilli(),
		candle.Open,
		candle.High,
		candle.Low,
		candle.Close,
		candle.Volume,
		isClosed,
		time.Now().UnixMilli(),
	)
	if err != nil {
		log.Error().Err(err).
			Str("symbol", candle.Symbol).
			Time("open_time", candle.OpenTime).
			Msg("failed to persist candle to SQLite")
		return
	}

	// Prune old candles if we have too many
	s.pruneOldCandles(candle.Symbol)
}

// pruneOldCandles removes the oldest candles for a symbol if we exceed maxRows.
// Caller must hold s.mu.
func (s *SQLiteStore) pruneOldCandles(symbol string) {
	if s.maxRows <= 0 {
		return
	}

	// Count current rows
	var count int
	if err := s.db.QueryRow(
		"SELECT COUNT(*) FROM candles WHERE symbol = ?",
		symbol,
	).Scan(&count); err != nil {
		log.Warn().Err(err).Str("symbol", symbol).Msg("failed to count candles for pruning")
		return
	}

	if count <= s.maxRows {
		return
	}

	// Delete oldest candles
	deleteCount := count - s.maxRows
	_, err := s.db.Exec(`
		DELETE FROM candles 
		WHERE symbol = ? AND id IN (
			SELECT id FROM candles 
			WHERE symbol = ? 
			ORDER BY open_time ASC 
			LIMIT ?
		)
	`, symbol, symbol, deleteCount)
	if err != nil {
		log.Warn().Err(err).Str("symbol", symbol).Int("count", deleteCount).Msg("failed to prune old candles")
		return
	}

	log.Debug().Str("symbol", symbol).Int("pruned", deleteCount).Msg("pruned old candles from SQLite")
}

// Get returns the last n candles for a symbol (delegates to in-memory store).
func (s *SQLiteStore) Get(symbol string, n int) []exchange.Candle {
	return s.mem.Get(symbol, n)
}

// GetAll returns all candles for a symbol (delegates to in-memory store).
func (s *SQLiteStore) GetAll(symbol string) []exchange.Candle {
	return s.mem.GetAll(symbol)
}

// GetSince returns candles since a given time (delegates to in-memory store).
func (s *SQLiteStore) GetSince(symbol string, since time.Time) []exchange.Candle {
	return s.mem.GetSince(symbol, since)
}

// Len returns the number of candles for a symbol (delegates to in-memory store).
func (s *SQLiteStore) Len(symbol string) int {
	return s.mem.Len(symbol)
}

// Symbols returns all symbols with stored candles (delegates to in-memory store).
func (s *SQLiteStore) Symbols() []string {
	return s.mem.Symbols()
}

// LastCandleTime returns the close time of the most recent candle.
func (s *SQLiteStore) LastCandleTime(symbol string) time.Time {
	return s.mem.LastCandleTime(symbol)
}

// Close closes the SQLite database connection.
func (s *SQLiteStore) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.db != nil {
		return s.db.Close()
	}
	return nil
}

// DBPath returns the path to the SQLite database file.
func (s *SQLiteStore) DBPath() string {
	return s.dbPath
}

// Stats returns statistics about the store.
func (s *SQLiteStore) Stats() map[string]int {
	s.mu.Lock()
	defer s.mu.Unlock()

	stats := make(map[string]int)

	// Get count per symbol from DB
	rows, err := s.db.Query("SELECT symbol, COUNT(*) FROM candles GROUP BY symbol")
	if err != nil {
		log.Warn().Err(err).Msg("failed to query candle stats")
		return stats
	}
	defer rows.Close()

	for rows.Next() {
		var symbol string
		var count int
		if err := rows.Scan(&symbol, &count); err != nil {
			continue
		}
		stats[symbol] = count
	}

	return stats
}
