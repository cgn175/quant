package data

import (
	"database/sql"
	"fmt"
	"sync"
	"time"

	_ "modernc.org/sqlite"

	"github.com/rs/zerolog/log"
)

// ArbPosition represents a persisted funding arb position.
type ArbPosition struct {
	ID               int64
	Symbol           string
	Side             string // "SHORT" or "LONG"
	EntryPrice       float64
	Size             float64
	EntryTime        time.Time
	EntryFunding     float64
	FundingCollected float64
	FundingPayments  int
	Status           string // "OPEN" or "CLOSED"
	CloseReason      string
	ClosePrice       float64
	CloseTime        time.Time
	SpotEntryPrice   float64
	SpotSize         float64
}

// FundingStore provides SQLite persistence for funding rates and arb positions.
type FundingStore struct {
	db *sql.DB
	mu sync.Mutex
}

// NewFundingStore opens (or creates) a SQLite database for the funding arb strategy.
func NewFundingStore(dbPath string) (*FundingStore, error) {
	if dbPath == "" {
		dbPath = "funding.db"
	}

	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return nil, fmt.Errorf("open sqlite: %w", err)
	}

	if _, err := db.Exec("PRAGMA journal_mode=WAL"); err != nil {
		db.Close()
		return nil, fmt.Errorf("set WAL mode: %w", err)
	}

	createSQL := `
		CREATE TABLE IF NOT EXISTS funding_rates (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			symbol TEXT NOT NULL,
			rate REAL NOT NULL,
			mark_price REAL NOT NULL,
			timestamp INTEGER NOT NULL,
			UNIQUE(symbol, timestamp)
		);
		CREATE INDEX IF NOT EXISTS idx_funding_symbol_time ON funding_rates(symbol, timestamp DESC);

		CREATE TABLE IF NOT EXISTS arb_positions (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			symbol TEXT NOT NULL,
			side TEXT NOT NULL,
			entry_price REAL NOT NULL,
			size REAL NOT NULL,
			entry_time INTEGER NOT NULL,
			entry_funding REAL NOT NULL,
			funding_collected REAL NOT NULL DEFAULT 0,
			funding_payments INTEGER NOT NULL DEFAULT 0,
			status TEXT NOT NULL DEFAULT 'OPEN',
			close_reason TEXT NOT NULL DEFAULT '',
			close_price REAL NOT NULL DEFAULT 0,
			close_time INTEGER NOT NULL DEFAULT 0,
			spot_entry_price REAL NOT NULL DEFAULT 0,
			spot_size REAL NOT NULL DEFAULT 0
		);
		CREATE INDEX IF NOT EXISTS idx_arb_status ON arb_positions(status);
	`
	if _, err := db.Exec(createSQL); err != nil {
		db.Close()
		return nil, fmt.Errorf("create tables: %w", err)
	}

	return &FundingStore{db: db}, nil
}

// Close closes the database connection.
func (s *FundingStore) Close() error {
	return s.db.Close()
}

// --- Funding Rates ---

// InsertFundingRate saves a funding rate snapshot.
func (s *FundingStore) InsertFundingRate(symbol string, rate, markPrice float64, ts time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	_, err := s.db.Exec(
		`INSERT OR IGNORE INTO funding_rates (symbol, rate, mark_price, timestamp) VALUES (?, ?, ?, ?)`,
		symbol, rate, markPrice, ts.UnixMilli(),
	)
	return err
}

// LoadFundingRates loads the most recent `limit` funding rates for a symbol (oldest first).
func (s *FundingStore) LoadFundingRates(symbol string, limit int) ([]FundingRate, error) {
	rows, err := s.db.Query(
		`SELECT symbol, rate, timestamp FROM funding_rates WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?`,
		symbol, limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var rates []FundingRate
	for rows.Next() {
		var r FundingRate
		var ts int64
		if err := rows.Scan(&r.Symbol, &r.Rate, &ts); err != nil {
			return nil, err
		}
		r.Timestamp = time.UnixMilli(ts)
		rates = append(rates, r)
	}

	// Reverse to chronological order (oldest first)
	for i, j := 0, len(rates)-1; i < j; i, j = i+1, j-1 {
		rates[i], rates[j] = rates[j], rates[i]
	}

	return rates, rows.Err()
}

// PruneFundingRates removes old funding rate rows beyond `keep` per symbol.
func (s *FundingStore) PruneFundingRates(symbol string, keep int) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	_, err := s.db.Exec(`
		DELETE FROM funding_rates WHERE symbol = ? AND id NOT IN (
			SELECT id FROM funding_rates WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?
		)`, symbol, symbol, keep)
	return err
}

// --- Arb Positions ---

// SavePosition inserts a new open arb position and returns its row ID.
func (s *FundingStore) SavePosition(pos *ArbPosition) (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	res, err := s.db.Exec(`
		INSERT INTO arb_positions
		(symbol, side, entry_price, size, entry_time, entry_funding, funding_collected, funding_payments, status, spot_entry_price, spot_size)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)`,
		pos.Symbol, pos.Side, pos.EntryPrice, pos.Size,
		pos.EntryTime.UnixMilli(), pos.EntryFunding,
		pos.FundingCollected, pos.FundingPayments,
		pos.SpotEntryPrice, pos.SpotSize,
	)
	if err != nil {
		return 0, err
	}
	return res.LastInsertId()
}

// UpdatePosition updates funding collection fields for an open position.
func (s *FundingStore) UpdatePosition(id int64, fundingCollected float64, fundingPayments int) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	_, err := s.db.Exec(
		`UPDATE arb_positions SET funding_collected = ?, funding_payments = ? WHERE id = ?`,
		fundingCollected, fundingPayments, id,
	)
	return err
}

// ClosePosition marks a position as closed with exit details.
func (s *FundingStore) ClosePosition(id int64, reason string, closePrice float64, closeTime time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	_, err := s.db.Exec(
		`UPDATE arb_positions SET status = 'CLOSED', close_reason = ?, close_price = ?, close_time = ? WHERE id = ?`,
		reason, closePrice, closeTime.UnixMilli(), id,
	)
	return err
}

// LoadOpenPositions returns all positions with status='OPEN'.
func (s *FundingStore) LoadOpenPositions() ([]ArbPosition, error) {
	rows, err := s.db.Query(`
		SELECT id, symbol, side, entry_price, size, entry_time, entry_funding,
		       funding_collected, funding_payments, status, spot_entry_price, spot_size
		FROM arb_positions WHERE status = 'OPEN'`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var positions []ArbPosition
	for rows.Next() {
		var p ArbPosition
		var entryTime int64
		if err := rows.Scan(
			&p.ID, &p.Symbol, &p.Side, &p.EntryPrice, &p.Size,
			&entryTime, &p.EntryFunding,
			&p.FundingCollected, &p.FundingPayments, &p.Status,
			&p.SpotEntryPrice, &p.SpotSize,
		); err != nil {
			return nil, err
		}
		p.EntryTime = time.UnixMilli(entryTime)
		positions = append(positions, p)
	}

	log.Info().Int("count", len(positions)).Msg("loaded open arb positions from DB")
	return positions, rows.Err()
}
