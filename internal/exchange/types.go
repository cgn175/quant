package exchange

import "time"

type Candle struct {
	Symbol    string
	OpenTime  time.Time
	CloseTime time.Time
	Open      float64
	High      float64
	Low       float64
	Close     float64
	Volume    float64
	IsClosed  bool // true when this is the final update for this bar
}

type OrderBook struct {
	Symbol    string
	Timestamp time.Time
	Bids      []PriceLevel
	Asks      []PriceLevel
}

type PriceLevel struct {
	Price    float64
	Quantity float64
}

type CandleHandler func(candle Candle)
type OrderBookHandler func(ob OrderBook)

type Client interface {
	SubscribeCandles(symbol, interval string, handler CandleHandler) error
	SubscribeOrderBook(symbol string, handler OrderBookHandler) error
	Close() error
}

// FundingRateInfo represents a funding rate from the exchange.
type FundingRateInfo struct {
	Symbol      string
	FundingRate float64
	FundingTime time.Time
	MarkPrice   float64
}
