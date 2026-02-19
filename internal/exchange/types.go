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
	PollCandles(symbol, interval string, handler CandleHandler, pollInterval time.Duration)
	PollOrderBook(symbol string, handler OrderBookHandler, pollInterval time.Duration)
	FetchFundingRate(symbol string) (*FundingRateInfo, error)
	FetchFundingRates(symbols []string) (map[string]*FundingRateInfo, error)
	FetchAllFundingRates() (map[string]*FundingRateInfo, error)
	FetchSpotPrice(symbol string) (float64, error)
	FetchOpenInterest(symbol string) (float64, error)
	Close() error
}

// CrossExchangeClient provides minimal interface for cross-exchange arbitrage
type CrossExchangeClient interface {
	GetFundingRate(symbol string) (*FundingRateInfo, error)
	GetPerpPrice(symbol string) (float64, error)
	GetSpotPrice(symbol string) (float64, error)
	GetOrderBook(symbol string) (*OrderBook, error)
	PlaceOrder(symbol, side string, quantity, price float64) error
	Close() error
}

// ExchangeRates holds funding rates from multiple exchanges
type ExchangeRates struct {
	Binance map[string]*FundingRateInfo
	Bybit   map[string]*FundingRateInfo
	OKX     map[string]*FundingRateInfo
}

// CrossExchangeOpportunity represents an arbitrage opportunity
type CrossExchangeOpportunity struct {
	Symbol              string
	HighExchange        string
	LowExchange         string
	HighFundingRate     float64
	LowFundingRate      float64
	SpreadBps           float64 // Spread in basis points
	AnnualizedReturn    float64 // Expected annualized return %
	EstTransferCostBps  float64 // Estimated round-trip transfer cost in bps
	NetAnnualizedReturn float64 // Return after estimated transfer costs
}

// FundingRateInfo represents a funding rate from the exchange.
type FundingRateInfo struct {
	Symbol      string
	FundingRate float64
	FundingTime time.Time
	MarkPrice   float64
}
