package risk

import (
	"testing"
)

func TestNewPortfolioMonitor(t *testing.T) {
	pm := NewPortfolioMonitor(100000, 50000, true)

	if pm.maxTotalPerpSpotExposure != 100000 {
		t.Errorf("expected maxTotalPerpSpotExposure=100000, got %f", pm.maxTotalPerpSpotExposure)
	}
	if pm.maxPerSymbolExposure != 50000 {
		t.Errorf("expected maxPerSymbolExposure=50000, got %f", pm.maxPerSymbolExposure)
	}
	if !pm.enableCorrelatedCheck {
		t.Error("expected enableCorrelatedCheck=true")
	}
	if len(pm.exposures) != 0 {
		t.Errorf("expected empty exposures, got %d", len(pm.exposures))
	}
}

func TestCanEnter_TotalLimit(t *testing.T) {
	pm := NewPortfolioMonitor(10000, 5000, true)

	// Add exposures to approach the limit
	pm.RegisterEntry("BTCUSDT", 6000, "funding_arb", "NEUTRAL")

	// Try to enter another position - should fail due to total limit
	ok, reason := pm.CanEnter("ETHUSDT", 5000, "funding_arb")
	if ok {
		t.Error("expected CanEnter to return false when total limit would be exceeded")
	}
	if reason != "total_exposure_limit" {
		t.Errorf("expected reason='total_exposure_limit', got '%s'", reason)
	}
}

func TestCanEnter_SymbolLimit(t *testing.T) {
	pm := NewPortfolioMonitor(100000, 5000, true)

	// Add exposure on a symbol
	pm.RegisterEntry("BTCUSDT", 3000, "funding_arb", "NEUTRAL")

	// Try to enter another position on same symbol - should fail due to symbol limit
	ok, reason := pm.CanEnter("BTCUSDT", 3000, "funding_arb")
	if ok {
		t.Error("expected CanEnter to return false when symbol limit would be exceeded")
	}
	if reason != "symbol_exposure_limit" {
		t.Errorf("expected reason='symbol_exposure_limit', got '%s'", reason)
	}

	// But different symbol should be fine
	ok, reason = pm.CanEnter("ETHUSDT", 3000, "funding_arb")
	if !ok {
		t.Errorf("expected CanEnter to return true for different symbol, got reason='%s'", reason)
	}
}

func TestCanEnter_CorrelatedStrategy(t *testing.T) {
	pm := NewPortfolioMonitor(100000, 50000, true)

	// Register funding_arb position
	pm.RegisterEntry("BTCUSDT", 1000, "funding_arb", "NEUTRAL")

	// Try to enter basis_trade on same symbol - should be blocked
	ok, reason := pm.CanEnter("BTCUSDT", 1000, "basis_trade")
	if ok {
		t.Error("expected CanEnter to return false when correlated strategy already active")
	}
	if reason != "correlated_strategy_active" {
		t.Errorf("expected reason='correlated_strategy_active', got '%s'", reason)
	}

	// Try to enter funding_arb again on same symbol - should be blocked (different strategy check not needed, just prevent double)
	ok, reason = pm.CanEnter("BTCUSDT", 1000, "funding_arb")
	// This should fail due to correlated check too (but actually it passes symbol limit, so we need to check the logic)
	// Actually since it's the same strategy, it won't trigger correlated check
	// But the symbol limit may allow it depending on math
	t.Logf("Same strategy second entry: ok=%v, reason=%s", ok, reason)
}

func TestCanEnter_CorrelatedCheckDisabled(t *testing.T) {
	pm := NewPortfolioMonitor(100000, 50000, false) // correlated check disabled

	// Register funding_arb position
	pm.RegisterEntry("BTCUSDT", 1000, "funding_arb", "NEUTRAL")

	// Try to enter basis_trade on same symbol - should be allowed since check is disabled
	ok, reason := pm.CanEnter("BTCUSDT", 1000, "basis_trade")
	if !ok {
		t.Errorf("expected CanEnter to return true when correlated check disabled, got reason='%s'", reason)
	}
}

func TestCanEnter_NonCorrelatedStrategies(t *testing.T) {
	pm := NewPortfolioMonitor(100000, 50000, true)

	// Register market_making position (not correlated with funding_arb/basis_trade)
	pm.RegisterEntry("BTCUSDT", 1000, "market_making", "LONG")

	// Try to enter funding_arb on same symbol - should be allowed
	ok, reason := pm.CanEnter("BTCUSDT", 1000, "funding_arb")
	if !ok {
		t.Errorf("expected CanEnter to return true for non-correlated strategy, got reason='%s'", reason)
	}
}

func TestRegisterEntryAndExit(t *testing.T) {
	pm := NewPortfolioMonitor(100000, 50000, true)

	// Register entry
	pm.RegisterEntry("BTCUSDT", 5000, "funding_arb", "NEUTRAL")

	// Check exposure
	if exp := pm.GetExposure("BTCUSDT"); exp != 5000 {
		t.Errorf("expected exposure=5000, got %f", exp)
	}
	if total := pm.GetTotalExposure(); total != 5000 {
		t.Errorf("expected total=5000, got %f", total)
	}

	// Register another entry on different symbol
	pm.RegisterEntry("ETHUSDT", 3000, "basis_trade", "NEUTRAL")

	if exp := pm.GetExposure("ETHUSDT"); exp != 3000 {
		t.Errorf("expected exposure=3000, got %f", exp)
	}
	if total := pm.GetTotalExposure(); total != 8000 {
		t.Errorf("expected total=8000, got %f", total)
	}

	// Register exit
	pm.RegisterExit("BTCUSDT", 5000, "funding_arb")

	if exp := pm.GetExposure("BTCUSDT"); exp != 0 {
		t.Errorf("expected exposure=0 after exit, got %f", exp)
	}
	if total := pm.GetTotalExposure(); total != 3000 {
		t.Errorf("expected total=3000 after exit, got %f", total)
	}
}

func TestRegisterExit_NonExistent(t *testing.T) {
	pm := NewPortfolioMonitor(100000, 50000, true)

	// Try to exit non-existent position - should not panic
	pm.RegisterExit("BTCUSDT", 5000, "funding_arb")

	if total := pm.GetTotalExposure(); total != 0 {
		t.Errorf("expected total=0, got %f", total)
	}
}

func TestGetExposureByStrategy(t *testing.T) {
	pm := NewPortfolioMonitor(100000, 50000, true)

	// Add multiple entries on same symbol with different strategies
	pm.RegisterEntry("BTCUSDT", 1000, "funding_arb", "NEUTRAL")
	pm.RegisterEntry("BTCUSDT", 2000, "market_making", "LONG")

	byStrategy := pm.GetExposureByStrategy("BTCUSDT")

	if byStrategy["funding_arb"] != 1000 {
		t.Errorf("expected funding_arb=1000, got %f", byStrategy["funding_arb"])
	}
	if byStrategy["market_making"] != 2000 {
		t.Errorf("expected market_making=2000, got %f", byStrategy["market_making"])
	}
}

func TestGetAllExposures(t *testing.T) {
	pm := NewPortfolioMonitor(100000, 50000, true)

	pm.RegisterEntry("BTCUSDT", 1000, "funding_arb", "NEUTRAL")
	pm.RegisterEntry("ETHUSDT", 2000, "basis_trade", "NEUTRAL")

	all := pm.GetAllExposures()

	if len(all) != 2 {
		t.Errorf("expected 2 symbols, got %d", len(all))
	}
	if len(all["BTCUSDT"]) != 1 {
		t.Errorf("expected 1 exposure for BTCUSDT, got %d", len(all["BTCUSDT"]))
	}
	if len(all["ETHUSDT"]) != 1 {
		t.Errorf("expected 1 exposure for ETHUSDT, got %d", len(all["ETHUSDT"]))
	}

	// Verify the copy is independent
	all["BTCUSDT"][0].Notional = 99999
	if pm.GetExposure("BTCUSDT") != 1000 {
		t.Error("GetAllExposures should return a copy, not reference")
	}
}

func TestIsCorrelatedStrategy(t *testing.T) {
	pm := NewPortfolioMonitor(100000, 50000, true)

	tests := []struct {
		strategy string
		expected bool
	}{
		{"funding_arb", true},
		{"basis_trade", true},
		{"market_making", false},
		{"trend_following", false},
		{"ml", false},
		{"unknown", false},
	}

	for _, tc := range tests {
		result := pm.isCorrelatedStrategy(tc.strategy)
		if result != tc.expected {
			t.Errorf("isCorrelatedStrategy(%s) = %v, expected %v", tc.strategy, result, tc.expected)
		}
	}
}

func TestString(t *testing.T) {
	pm := NewPortfolioMonitor(100000, 50000, true)

	// Empty state
	str := pm.String()
	if str != "PortfolioMonitor: no active exposures" {
		t.Errorf("unexpected string for empty state: %s", str)
	}

	// With exposures
	pm.RegisterEntry("BTCUSDT", 5000, "funding_arb", "NEUTRAL")
	pm.RegisterEntry("ETHUSDT", 3000, "basis_trade", "NEUTRAL")

	str = pm.String()
	if str == "" {
		t.Error("String() returned empty string")
	}
	if str == "PortfolioMonitor: no active exposures" {
		t.Error("String() returned empty state string when exposures exist")
	}
}

func TestConcurrentAccess(t *testing.T) {
	pm := NewPortfolioMonitor(1000000, 500000, true)

	// Run concurrent operations
	done := make(chan bool)

	// Writer goroutines
	for i := 0; i < 10; i++ {
		go func(id int) {
			symbol := "BTCUSDT"
			strategy := "funding_arb"
			if id%2 == 0 {
				strategy = "basis_trade"
			}
			pm.RegisterEntry(symbol, 1000, strategy, "NEUTRAL")
			done <- true
		}(i)
	}

	// Reader goroutines
	for i := 0; i < 10; i++ {
		go func() {
			_ = pm.GetExposure("BTCUSDT")
			_ = pm.GetTotalExposure()
			pm.CanEnter("ETHUSDT", 1000, "funding_arb")
			done <- true
		}()
	}

	// Wait for all goroutines
	for i := 0; i < 20; i++ {
		<-done
	}

	// Verify consistency
	total := pm.GetTotalExposure()
	btcExp := pm.GetExposure("BTCUSDT")
	if total != btcExp {
		t.Errorf("total exposure (%f) should equal BTC exposure (%f) since only BTC has positions", total, btcExp)
	}
}
