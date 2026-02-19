package marketmaking

import (
	"math"

	"github.com/cgn175/quant-bot/internal/exchange"
)

// OrderBookImbalance calculates the weighted bid/ask volume imbalance.
// Returns a value in [-1, 1]:
//   +1 = all volume on bid side (bullish)
//   -1 = all volume on ask side (bearish)
//    0 = balanced
func CalculateOrderBookImbalance(ob exchange.OrderBook, depth int) float64 {
	if len(ob.Bids) == 0 || len(ob.Asks) == 0 {
		return 0
	}

	// Calculate mid price for distance weighting
	mid := (ob.Bids[0].Price + ob.Asks[0].Price) / 2.0

	bidVol := 0.0
	askVol := 0.0

	// Weight by distance from mid (closer levels = more important)
	maxLevels := depth
	if len(ob.Bids) < maxLevels {
		maxLevels = len(ob.Bids)
	}
	if len(ob.Asks) < maxLevels {
		maxLevels = len(ob.Asks)
	}

	for i := 0; i < maxLevels; i++ {
		if i < len(ob.Bids) {
			distance := math.Abs(ob.Bids[i].Price-mid) / mid
			weight := 1.0 / (1.0 + distance*100) // decay with distance
			bidVol += ob.Bids[i].Quantity * weight
		}
		if i < len(ob.Asks) {
			distance := math.Abs(ob.Asks[i].Price-mid) / mid
			weight := 1.0 / (1.0 + distance*100)
			askVol += ob.Asks[i].Quantity * weight
		}
	}

	if bidVol+askVol == 0 {
		return 0
	}

	return (bidVol - askVol) / (bidVol + askVol)
}

// AdjustSpreadForImbalance skews bid/ask spreads based on order book imbalance.
// Positive imbalance (more bids) → tighten bid, widen ask (expect price up)
// Negative imbalance (more asks) → widen bid, tighten ask (expect price down)
func AdjustSpreadForImbalance(baseSpread, imbalance, skewFactor float64) (bidSpread, askSpread float64) {
	// Skew factor controls how much imbalance affects spread (default 0.5 = 50%)
	if skewFactor <= 0 {
		skewFactor = 0.5
	}

	skew := imbalance * skewFactor

	// Positive imbalance → reduce bid spread, increase ask spread
	// Negative imbalance → increase bid spread, reduce ask spread
	bidSpread = baseSpread * (1 - skew)
	askSpread = baseSpread * (1 + skew)

	// Ensure spreads don't go negative
	if bidSpread < baseSpread*0.2 {
		bidSpread = baseSpread * 0.2
	}
	if askSpread < baseSpread*0.2 {
		askSpread = baseSpread * 0.2
	}

	return bidSpread, askSpread
}
