package strategy

import (
	"time"

	"github.com/cgn175/quant-bot/internal/features"
	"github.com/cgn175/quant-bot/internal/model"
)

type SignalType int

const (
	SignalNone SignalType = iota
	SignalLong
	SignalShort
	SignalCloseLong
	SignalCloseShort
)

func (s SignalType) String() string {
	switch s {
	case SignalLong:
		return "LONG"
	case SignalShort:
		return "SHORT"
	case SignalCloseLong:
		return "CLOSE_LONG"
	case SignalCloseShort:
		return "CLOSE_SHORT"
	default:
		return "NONE"
	}
}

type Signal struct {
	Symbol     string
	Type       SignalType
	Timestamp  time.Time
	Price      float64
	Prediction *model.Prediction
	Features   *features.FeatureVector
	Confidence float64
	StopLoss   float64
	TakeProfit float64
}

type Config struct {
	// Model thresholds
	ThresholdUp   float64
	ThresholdDown float64

	// Sentiment filters
	SentimentThresholdLong  float64
	SentimentThresholdShort float64
	SentimentExtremeLimit   float64 // e.g., 0.8

	// Volume filters
	MinVolumeRatio float64 // e.g., 0.5 (volume must be 50% of avg)

	// Risk parameters (for stop loss / take profit calculation)
	StopLossPercent   float64 // e.g., 1.0 for 1%
	TakeProfitPercent float64 // e.g., 2.0 for 2%

	// Mode flags
	AllowLong  bool
	AllowShort bool
}

type Strategy struct {
	config Config
}

func NewStrategy(config Config) *Strategy {
	return &Strategy{
		config: config,
	}
}

func (s *Strategy) Evaluate(fv *features.FeatureVector, pred *model.Prediction) *Signal {
	if fv == nil || pred == nil {
		return nil
	}

	// Validate prediction probabilities
	if !isValidPrediction(pred) {
		return nil
	}

	signal := &Signal{
		Symbol:     fv.Symbol,
		Timestamp:  fv.Timestamp,
		Price:      fv.Close,
		Prediction: pred,
		Features:   fv,
		Confidence: 0,
	}

	// Check volume filter
	if fv.VolumeRatio < s.config.MinVolumeRatio {
		return nil
	}

	// NOTE: Extreme sentiment is handled by ShouldReduceSize() which reduces
	// position size by 50% - we don't skip trades entirely.

	// Evaluate long signal
	if s.config.AllowLong && s.shouldGoLong(fv, pred) {
		signal.Type = SignalLong
		signal.Confidence = pred.ProbUp
		signal.StopLoss = fv.Close * (1.0 - s.config.StopLossPercent/100.0)
		signal.TakeProfit = fv.Close * (1.0 + s.config.TakeProfitPercent/100.0)
		return signal
	}

	// Evaluate short signal
	if s.config.AllowShort && s.shouldGoShort(fv, pred) {
		signal.Type = SignalShort
		signal.Confidence = pred.ProbDown
		signal.StopLoss = fv.Close * (1.0 + s.config.StopLossPercent/100.0)
		signal.TakeProfit = fv.Close * (1.0 - s.config.TakeProfitPercent/100.0)
		return signal
	}

	return nil
}

func (s *Strategy) shouldGoLong(fv *features.FeatureVector, pred *model.Prediction) bool {
	// Model probability check
	if pred.ProbUp < s.config.ThresholdUp {
		return false
	}

	// Sentiment filter: don't go long if sentiment is too negative
	if fv.SentimentScore1h < s.config.SentimentThresholdLong {
		return false
	}

	return true
}

func (s *Strategy) shouldGoShort(fv *features.FeatureVector, pred *model.Prediction) bool {
	// Model probability check
	if pred.ProbDown < s.config.ThresholdDown {
		return false
	}

	// Sentiment filter: disable shorts if sentiment is too positive
	if fv.SentimentScore1h > s.config.SentimentThresholdShort {
		return false
	}

	return true
}

func (s *Strategy) ShouldReduceSize(fv *features.FeatureVector) float64 {
	// Return a multiplier for position size (0.5 = reduce by 50%, 1.0 = no reduction)
	if fv == nil {
		return 1.0
	}

	// Reduce size by 50% if sentiment is extreme
	if fv.SentimentScore24h > s.config.SentimentExtremeLimit ||
		fv.SentimentScore24h < -s.config.SentimentExtremeLimit {
		return 0.5
	}

	return 1.0
}

// isValidPrediction checks if prediction probabilities are valid
// (non-NaN, non-negative, within [0, 1])
func isValidPrediction(pred *model.Prediction) bool {
	if pred == nil {
		return false
	}

	// Check for NaN
	if isNaN(pred.ProbDown) || isNaN(pred.ProbNeutral) || isNaN(pred.ProbUp) {
		return false
	}

	// Check for negative probabilities
	if pred.ProbDown < 0 || pred.ProbNeutral < 0 || pred.ProbUp < 0 {
		return false
	}

	// Check bounds (should be between 0 and 1)
	if pred.ProbDown > 1.0 || pred.ProbNeutral > 1.0 || pred.ProbUp > 1.0 {
		return false
	}

	// Sum should be approximately 1.0 (allow small floating point error)
	sum := pred.ProbDown + pred.ProbNeutral + pred.ProbUp
	if sum < 0.99 || sum > 1.01 {
		return false
	}

	return true
}

// isNaN checks if a float64 is NaN
func isNaN(f float64) bool {
	return f != f
}

// Evaluate4H evaluates a 4H feature vector against the strategy rules.
// Unlike Evaluate(), this method does not apply sentiment filters since
// the 4H model has no sentiment features.
func (s *Strategy) Evaluate4H(fv *features.FeatureVector4H, pred *model.Prediction) *Signal {
	if fv == nil || pred == nil {
		return nil
	}

	// Validate prediction probabilities
	if !isValidPrediction(pred) {
		return nil
	}

	signal := &Signal{
		Symbol:     fv.Symbol,
		Timestamp:  fv.Timestamp,
		Price:      fv.Close,
		Prediction: pred,
		Features:   nil, // 4H uses FeatureVector4H, not FeatureVector
		Confidence: 0,
	}

	// Check volume filter
	if fv.VolumeRatio < s.config.MinVolumeRatio {
		return nil
	}

	// Evaluate long signal (no sentiment filter for 4H)
	if s.config.AllowLong && pred.ProbUp >= s.config.ThresholdUp {
		signal.Type = SignalLong
		signal.Confidence = pred.ProbUp
		signal.StopLoss = fv.Close * (1.0 - s.config.StopLossPercent/100.0)
		signal.TakeProfit = fv.Close * (1.0 + s.config.TakeProfitPercent/100.0)
		return signal
	}

	// Evaluate short signal (no sentiment filter for 4H)
	if s.config.AllowShort && pred.ProbDown >= s.config.ThresholdDown {
		signal.Type = SignalShort
		signal.Confidence = pred.ProbDown
		signal.StopLoss = fv.Close * (1.0 + s.config.StopLossPercent/100.0)
		signal.TakeProfit = fv.Close * (1.0 - s.config.TakeProfitPercent/100.0)
		return signal
	}

	return nil
}

// ShouldReduceSize4H returns the position size multiplier for 4H trades.
// Since 4H models don't have sentiment features, no size reduction is applied.
func (s *Strategy) ShouldReduceSize4H(fv *features.FeatureVector4H) float64 {
	return 1.0
}
