package data

import (
	"os"
	"testing"
	"time"
)

func tempStore(t *testing.T) *FundingStore {
	t.Helper()
	f, err := os.CreateTemp("", "funding_test_*.db")
	if err != nil {
		t.Fatal(err)
	}
	f.Close()
	t.Cleanup(func() { os.Remove(f.Name()) })

	store, err := NewFundingStore(f.Name())
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { store.Close() })
	return store
}

func TestInsertAndLoadFundingRates(t *testing.T) {
	store := tempStore(t)

	now := time.Now().Truncate(time.Millisecond)

	if err := store.InsertFundingRate("BTCUSDT", 0.0005, 60000, now); err != nil {
		t.Fatal(err)
	}
	if err := store.InsertFundingRate("BTCUSDT", 0.0003, 60100, now.Add(8*time.Hour)); err != nil {
		t.Fatal(err)
	}
	if err := store.InsertFundingRate("ETHUSDT", -0.0002, 3000, now); err != nil {
		t.Fatal(err)
	}

	// Load BTC rates
	rates, err := store.LoadFundingRates("BTCUSDT", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(rates) != 2 {
		t.Fatalf("expected 2 rates, got %d", len(rates))
	}
	// Should be oldest first
	if rates[0].Rate != 0.0005 {
		t.Errorf("expected first rate 0.0005, got %f", rates[0].Rate)
	}
	if rates[1].Rate != 0.0003 {
		t.Errorf("expected second rate 0.0003, got %f", rates[1].Rate)
	}

	// ETH
	rates, err = store.LoadFundingRates("ETHUSDT", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(rates) != 1 {
		t.Fatalf("expected 1 rate, got %d", len(rates))
	}
}

func TestDuplicateFundingRateIgnored(t *testing.T) {
	store := tempStore(t)
	now := time.Now().Truncate(time.Millisecond)

	if err := store.InsertFundingRate("BTCUSDT", 0.0005, 60000, now); err != nil {
		t.Fatal(err)
	}
	// Insert same timestamp again — should be ignored
	if err := store.InsertFundingRate("BTCUSDT", 0.0010, 61000, now); err != nil {
		t.Fatal(err)
	}

	rates, err := store.LoadFundingRates("BTCUSDT", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(rates) != 1 {
		t.Fatalf("expected 1 rate (duplicate ignored), got %d", len(rates))
	}
}

func TestSaveAndLoadOpenPositions(t *testing.T) {
	store := tempStore(t)

	now := time.Now().Truncate(time.Millisecond)

	pos := &ArbPosition{
		Symbol:       "BTCUSDT",
		Side:         "SHORT",
		EntryPrice:   60000,
		Size:         0.016,
		EntryTime:    now,
		EntryFunding: 0.0005,
	}

	id, err := store.SavePosition(pos)
	if err != nil {
		t.Fatal(err)
	}
	if id <= 0 {
		t.Fatal("expected positive ID")
	}

	// Load open positions
	positions, err := store.LoadOpenPositions()
	if err != nil {
		t.Fatal(err)
	}
	if len(positions) != 1 {
		t.Fatalf("expected 1 open position, got %d", len(positions))
	}

	p := positions[0]
	if p.Symbol != "BTCUSDT" || p.Side != "SHORT" {
		t.Errorf("unexpected position: %+v", p)
	}
	if p.EntryPrice != 60000 || p.Size != 0.016 {
		t.Errorf("unexpected entry data: price=%f size=%f", p.EntryPrice, p.Size)
	}
}

func TestUpdateAndClosePosition(t *testing.T) {
	store := tempStore(t)

	now := time.Now().Truncate(time.Millisecond)

	pos := &ArbPosition{
		Symbol:       "ETHUSDT",
		Side:         "LONG",
		EntryPrice:   3000,
		Size:         0.33,
		EntryTime:    now,
		EntryFunding: -0.0003,
	}

	id, err := store.SavePosition(pos)
	if err != nil {
		t.Fatal(err)
	}

	// Update funding collection
	if err := store.UpdatePosition(id, 1.5, 3); err != nil {
		t.Fatal(err)
	}

	positions, err := store.LoadOpenPositions()
	if err != nil {
		t.Fatal(err)
	}
	if positions[0].FundingCollected != 1.5 || positions[0].FundingPayments != 3 {
		t.Errorf("unexpected update: collected=%f payments=%d", positions[0].FundingCollected, positions[0].FundingPayments)
	}

	// Close position
	if err := store.ClosePosition(id, "funding_normalized", 3100, now.Add(24*time.Hour)); err != nil {
		t.Fatal(err)
	}

	// Should no longer appear in open positions
	positions, err = store.LoadOpenPositions()
	if err != nil {
		t.Fatal(err)
	}
	if len(positions) != 0 {
		t.Fatalf("expected 0 open positions after close, got %d", len(positions))
	}
}

func TestPruneFundingRates(t *testing.T) {
	store := tempStore(t)

	base := time.Now().Truncate(time.Millisecond)
	for i := 0; i < 10; i++ {
		if err := store.InsertFundingRate("BTCUSDT", float64(i)*0.0001, 60000, base.Add(time.Duration(i)*time.Hour)); err != nil {
			t.Fatal(err)
		}
	}

	// Prune to keep only 3
	if err := store.PruneFundingRates("BTCUSDT", 3); err != nil {
		t.Fatal(err)
	}

	rates, err := store.LoadFundingRates("BTCUSDT", 100)
	if err != nil {
		t.Fatal(err)
	}
	if len(rates) != 3 {
		t.Fatalf("expected 3 rates after prune, got %d", len(rates))
	}
	// Should keep the 3 most recent
	if rates[0].Rate != 0.0007 {
		t.Errorf("expected oldest kept rate 0.0007, got %f", rates[0].Rate)
	}
}
