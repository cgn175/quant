package data

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/cgn175/quant-bot/internal/exchange"
)

func TestSQLiteStore_BasicOperations(t *testing.T) {
	// Create temp dir for test DB
	tmpDir := t.TempDir()
	dbPath := filepath.Join(tmpDir, "test_candles.db")

	// Create store
	store, err := NewSQLiteStore(SQLiteConfig{
		DBPath:     dbPath,
		MaxCandles: 100,
		MaxDBRows:  200,
	})
	if err != nil {
		t.Fatalf("NewSQLiteStore: %v", err)
	}
	defer store.Close()

	// Test Add and Get
	baseTime := time.Now().Truncate(4 * time.Hour)
	candle1 := exchange.Candle{
		Symbol:    "BTCUSDT",
		OpenTime:  baseTime,
		CloseTime: baseTime.Add(4 * time.Hour),
		Open:      50000,
		High:      51000,
		Low:       49000,
		Close:     50500,
		Volume:    1000,
		IsClosed:  true,
	}

	store.Add(candle1)

	// Check in-memory
	candles := store.GetAll("BTCUSDT")
	if len(candles) != 1 {
		t.Errorf("expected 1 candle, got %d", len(candles))
	}
	if candles[0].Close != 50500 {
		t.Errorf("expected Close=50500, got %f", candles[0].Close)
	}
}

func TestSQLiteStore_Persistence(t *testing.T) {
	tmpDir := t.TempDir()
	dbPath := filepath.Join(tmpDir, "persist_test.db")

	// Create and populate store
	store1, err := NewSQLiteStore(SQLiteConfig{
		DBPath:     dbPath,
		MaxCandles: 100,
	})
	if err != nil {
		t.Fatalf("NewSQLiteStore: %v", err)
	}

	baseTime := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	for i := 0; i < 5; i++ {
		c := exchange.Candle{
			Symbol:    "ETHUSDT",
			OpenTime:  baseTime.Add(time.Duration(i) * 4 * time.Hour),
			CloseTime: baseTime.Add(time.Duration(i+1) * 4 * time.Hour),
			Open:      3000 + float64(i*10),
			High:      3050 + float64(i*10),
			Low:       2950 + float64(i*10),
			Close:     3025 + float64(i*10),
			Volume:    500,
			IsClosed:  true,
		}
		store1.Add(c)
	}
	store1.Close()

	// Create new store with same DB path
	store2, err := NewSQLiteStore(SQLiteConfig{
		DBPath:     dbPath,
		MaxCandles: 100,
	})
	if err != nil {
		t.Fatalf("NewSQLiteStore (reopen): %v", err)
	}
	defer store2.Close()

	// Load history
	if err := store2.LoadHistory([]string{"ETHUSDT"}); err != nil {
		t.Fatalf("LoadHistory: %v", err)
	}

	// Verify candles were loaded
	candles := store2.GetAll("ETHUSDT")
	if len(candles) != 5 {
		t.Errorf("expected 5 candles after reload, got %d", len(candles))
	}

	// Verify order (should be oldest first)
	if len(candles) >= 2 {
		if !candles[0].OpenTime.Before(candles[1].OpenTime) {
			t.Errorf("candles not in chronological order")
		}
	}
}

func TestSQLiteStore_OnlyClosedCandles(t *testing.T) {
	tmpDir := t.TempDir()
	dbPath := filepath.Join(tmpDir, "closed_only_test.db")

	store, err := NewSQLiteStore(SQLiteConfig{
		DBPath:     dbPath,
		MaxCandles: 100,
	})
	if err != nil {
		t.Fatalf("NewSQLiteStore: %v", err)
	}
	defer store.Close()

	baseTime := time.Now().Truncate(4 * time.Hour)

	// Add unclosed candle (should not persist to DB)
	unclosed := exchange.Candle{
		Symbol:    "BTCUSDT",
		OpenTime:  baseTime,
		CloseTime: baseTime.Add(4 * time.Hour),
		Open:      50000,
		High:      50500,
		Low:       49500,
		Close:     50200,
		Volume:    100,
		IsClosed:  false, // NOT closed
	}
	store.Add(unclosed)

	// Add closed candle
	closed := exchange.Candle{
		Symbol:    "BTCUSDT",
		OpenTime:  baseTime.Add(-4 * time.Hour),
		CloseTime: baseTime,
		Open:      49000,
		High:      50000,
		Low:       48500,
		Close:     50000,
		Volume:    200,
		IsClosed:  true, // closed
	}
	store.Add(closed)

	// Reopen and check only closed candle was persisted
	store.Close()

	store2, err := NewSQLiteStore(SQLiteConfig{
		DBPath:     dbPath,
		MaxCandles: 100,
	})
	if err != nil {
		t.Fatalf("NewSQLiteStore (reopen): %v", err)
	}
	defer store2.Close()

	if err := store2.LoadHistory([]string{"BTCUSDT"}); err != nil {
		t.Fatalf("LoadHistory: %v", err)
	}

	candles := store2.GetAll("BTCUSDT")
	if len(candles) != 1 {
		t.Errorf("expected 1 candle (only closed), got %d", len(candles))
	}
	if len(candles) > 0 && candles[0].Close != 50000 {
		t.Errorf("expected the closed candle, got Close=%f", candles[0].Close)
	}
}

func TestSQLiteStore_Pruning(t *testing.T) {
	tmpDir := t.TempDir()
	dbPath := filepath.Join(tmpDir, "prune_test.db")

	maxRows := 5
	store, err := NewSQLiteStore(SQLiteConfig{
		DBPath:     dbPath,
		MaxCandles: 100,
		MaxDBRows:  maxRows,
	})
	if err != nil {
		t.Fatalf("NewSQLiteStore: %v", err)
	}
	defer store.Close()

	baseTime := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)

	// Add more candles than maxRows
	for i := 0; i < 10; i++ {
		c := exchange.Candle{
			Symbol:    "SOLUSDT",
			OpenTime:  baseTime.Add(time.Duration(i) * 4 * time.Hour),
			CloseTime: baseTime.Add(time.Duration(i+1) * 4 * time.Hour),
			Open:      100 + float64(i),
			High:      105 + float64(i),
			Low:       95 + float64(i),
			Close:     102 + float64(i),
			Volume:    50,
			IsClosed:  true,
		}
		store.Add(c)
	}

	// Check DB row count via Stats
	stats := store.Stats()
	if stats["SOLUSDT"] > maxRows {
		t.Errorf("expected <= %d rows in DB, got %d", maxRows, stats["SOLUSDT"])
	}
}

func TestSQLiteStore_Upsert(t *testing.T) {
	tmpDir := t.TempDir()
	dbPath := filepath.Join(tmpDir, "upsert_test.db")

	store, err := NewSQLiteStore(SQLiteConfig{
		DBPath:     dbPath,
		MaxCandles: 100,
	})
	if err != nil {
		t.Fatalf("NewSQLiteStore: %v", err)
	}
	defer store.Close()

	baseTime := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)

	// Add initial candle
	c1 := exchange.Candle{
		Symbol:    "BNBUSDT",
		OpenTime:  baseTime,
		CloseTime: baseTime.Add(4 * time.Hour),
		Open:      300,
		High:      310,
		Low:       290,
		Close:     305,
		Volume:    100,
		IsClosed:  true,
	}
	store.Add(c1)

	// Update same candle (same open_time)
	c2 := exchange.Candle{
		Symbol:    "BNBUSDT",
		OpenTime:  baseTime,         // same open_time
		CloseTime: baseTime.Add(4 * time.Hour),
		Open:      300,
		High:      315, // updated
		Low:       288, // updated
		Close:     312, // updated
		Volume:    150, // updated
		IsClosed:  true,
	}
	store.Add(c2)

	// Verify only one candle exists with updated values
	stats := store.Stats()
	if stats["BNBUSDT"] != 1 {
		t.Errorf("expected 1 candle after upsert, got %d", stats["BNBUSDT"])
	}

	// Reload and verify updated values
	store.Close()

	store2, err := NewSQLiteStore(SQLiteConfig{
		DBPath:     dbPath,
		MaxCandles: 100,
	})
	if err != nil {
		t.Fatalf("NewSQLiteStore (reopen): %v", err)
	}
	defer store2.Close()

	if err := store2.LoadHistory([]string{"BNBUSDT"}); err != nil {
		t.Fatalf("LoadHistory: %v", err)
	}

	candles := store2.GetAll("BNBUSDT")
	if len(candles) != 1 {
		t.Fatalf("expected 1 candle, got %d", len(candles))
	}
	if candles[0].Close != 312 {
		t.Errorf("expected Close=312 after upsert, got %f", candles[0].Close)
	}
	if candles[0].High != 315 {
		t.Errorf("expected High=315 after upsert, got %f", candles[0].High)
	}
}

func TestSQLiteStore_DBPath(t *testing.T) {
	tmpDir := t.TempDir()
	dbPath := filepath.Join(tmpDir, "custom_path.db")

	store, err := NewSQLiteStore(SQLiteConfig{
		DBPath: dbPath,
	})
	if err != nil {
		t.Fatalf("NewSQLiteStore: %v", err)
	}
	defer store.Close()

	if store.DBPath() != dbPath {
		t.Errorf("DBPath() = %s, want %s", store.DBPath(), dbPath)
	}

	// Verify file was created
	if _, err := os.Stat(dbPath); os.IsNotExist(err) {
		t.Errorf("DB file was not created at %s", dbPath)
	}
}
