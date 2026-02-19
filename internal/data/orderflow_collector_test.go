package data

import (
	"context"
	"database/sql"
	"testing"

	"github.com/stretchr/testify/assert"
	_ "modernc.org/sqlite"
)

func setupTestCollector(t *testing.T) (*OrderFlowCollector, *sql.DB) {
	db, err := sql.Open("sqlite", ":memory:")
	assert.NoError(t, err)

	err = createOrderFlowTables(db)
	assert.NoError(t, err)

	ctx, cancel := context.WithCancel(context.Background())

	ofc := &OrderFlowCollector{
		db:      db,
		symbols: []string{"BTCUSDT", "ETHUSDT"},
		ctx:     ctx,
		cancel:  cancel,
		deltas: map[string]*DeltaState{
			"BTCUSDT": {},
			"ETHUSDT": {},
		},
	}

	t.Cleanup(func() {
		cancel()
		db.Close()
	})

	return ofc, db
}

func TestProcessTrade_BuyerMaker(t *testing.T) {
	ofc, _ := setupTestCollector(t)

	trade := &aggTrade{
		Symbol:       "BTCUSDT",
		Price:        "50000.00",
		Quantity:     "1.5",
		IsBuyerMaker: true, // Sell at bid → negative delta
		Timestamp:    1000,
	}

	ofc.processTrade(trade)

	state := ofc.deltas["BTCUSDT"]
	assert.Less(t, state.delta1s, 0.0)
	assert.Less(t, state.delta5s, 0.0)
	assert.Less(t, state.delta1m, 0.0)
	assert.Less(t, state.cvd, 0.0)
	assert.InDelta(t, -1.5, state.delta1s, 0.001)
}

func TestProcessTrade_TakerBuy(t *testing.T) {
	ofc, _ := setupTestCollector(t)

	trade := &aggTrade{
		Symbol:       "BTCUSDT",
		Price:        "50000.00",
		Quantity:     "2.0",
		IsBuyerMaker: false, // Buy at ask → positive delta
		Timestamp:    1000,
	}

	ofc.processTrade(trade)

	state := ofc.deltas["BTCUSDT"]
	assert.Greater(t, state.delta1s, 0.0)
	assert.Greater(t, state.delta5s, 0.0)
	assert.Greater(t, state.delta1m, 0.0)
	assert.Greater(t, state.cvd, 0.0)
	assert.InDelta(t, 2.0, state.delta1s, 0.001)
}

func TestProcessTrade_UnknownSymbol(t *testing.T) {
	ofc, _ := setupTestCollector(t)

	trade := &aggTrade{
		Symbol:       "XRPUSDT", // Not in our symbols
		Price:        "1.00",
		Quantity:     "100.0",
		IsBuyerMaker: false,
		Timestamp:    1000,
	}

	// Should not panic or modify any state
	ofc.processTrade(trade)

	assert.InDelta(t, 0.0, ofc.deltas["BTCUSDT"].delta1s, 0.001)
	assert.InDelta(t, 0.0, ofc.deltas["ETHUSDT"].delta1s, 0.001)
}

func TestPersist_ResetsDelta(t *testing.T) {
	ofc, db := setupTestCollector(t)

	// Accumulate some delta
	ofc.deltas["BTCUSDT"].delta1s = 5.0
	ofc.deltas["BTCUSDT"].cvd = 5.0

	ofc.persist(1)

	// delta1s should be reset to 0
	assert.InDelta(t, 0.0, ofc.deltas["BTCUSDT"].delta1s, 0.001)
	// cvd should NOT be reset (it's cumulative)
	assert.InDelta(t, 5.0, ofc.deltas["BTCUSDT"].cvd, 0.001)

	// Verify data was written to DB
	var count int
	err := db.QueryRow("SELECT COUNT(*) FROM order_flow WHERE symbol = 'BTCUSDT'").Scan(&count)
	assert.NoError(t, err)
	assert.Equal(t, 1, count)
}

func TestPersist_SkipsZeroDelta(t *testing.T) {
	ofc, db := setupTestCollector(t)

	// Leave delta at 0 (default)
	ofc.persist(1)

	var count int
	err := db.QueryRow("SELECT COUNT(*) FROM order_flow").Scan(&count)
	assert.NoError(t, err)
	assert.Equal(t, 0, count) // Nothing should be persisted
}

func TestDeltaState_Accumulation(t *testing.T) {
	ofc, _ := setupTestCollector(t)

	trades := []struct {
		qty          string
		isBuyerMaker bool
	}{
		{"1.0", false},  // +1.0 (buy)
		{"0.5", true},   // -0.5 (sell)
		{"2.0", false},  // +2.0 (buy)
		{"0.3", true},   // -0.3 (sell)
	}

	for _, tr := range trades {
		ofc.processTrade(&aggTrade{
			Symbol:       "BTCUSDT",
			Price:        "50000.00",
			Quantity:     tr.qty,
			IsBuyerMaker: tr.isBuyerMaker,
			Timestamp:    1000,
		})
	}

	// Net delta: +1.0 - 0.5 + 2.0 - 0.3 = +2.2
	state := ofc.deltas["BTCUSDT"]
	assert.InDelta(t, 2.2, state.delta1s, 0.001)
	assert.InDelta(t, 2.2, state.delta5s, 0.001)
	assert.InDelta(t, 2.2, state.delta1m, 0.001)
	assert.InDelta(t, 2.2, state.cvd, 0.001)

	// ETH should be unaffected
	assert.InDelta(t, 0.0, ofc.deltas["ETHUSDT"].delta1s, 0.001)
}

func TestPersist_WindowSizes(t *testing.T) {
	ofc, _ := setupTestCollector(t)

	ofc.deltas["BTCUSDT"].delta1s = 1.0
	ofc.deltas["BTCUSDT"].delta5s = 5.0
	ofc.deltas["BTCUSDT"].delta1m = 10.0

	// Persist window=5 should only reset delta5s
	ofc.persist(5)

	assert.InDelta(t, 1.0, ofc.deltas["BTCUSDT"].delta1s, 0.001)  // untouched
	assert.InDelta(t, 0.0, ofc.deltas["BTCUSDT"].delta5s, 0.001)  // reset
	assert.InDelta(t, 10.0, ofc.deltas["BTCUSDT"].delta1m, 0.001) // untouched
}
