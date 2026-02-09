package mlfilter

import (
	"sync"
	"time"
)

type CircuitBreaker struct {
	mu               sync.Mutex
	results          []bool // true=success, false=error
	windowSize       int
	errorThreshold   float64
	tripped          bool
	trippedAt        time.Time
	cooldownDuration time.Duration
}

func NewCircuitBreaker(windowSize int, errorThreshold float64, cooldown time.Duration) *CircuitBreaker {
	return &CircuitBreaker{
		results:          make([]bool, 0, windowSize),
		windowSize:       windowSize,
		errorThreshold:   errorThreshold,
		cooldownDuration: cooldown,
	}
}

func (cb *CircuitBreaker) RecordSuccess() {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	cb.record(true)
}

func (cb *CircuitBreaker) RecordError() {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	cb.record(false)
	cb.checkTrip()
}

func (cb *CircuitBreaker) IsTripped() bool {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	if !cb.tripped {
		return false
	}

	if time.Since(cb.trippedAt) >= cb.cooldownDuration {
		cb.tripped = false
		cb.results = cb.results[:0]
		return false
	}

	return true
}

func (cb *CircuitBreaker) Reset() {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	cb.tripped = false
	cb.results = cb.results[:0]
}

func (cb *CircuitBreaker) record(success bool) {
	cb.results = append(cb.results, success)
	if len(cb.results) > cb.windowSize {
		cb.results = cb.results[len(cb.results)-cb.windowSize:]
	}
}

func (cb *CircuitBreaker) checkTrip() {
	if len(cb.results) < cb.windowSize {
		return
	}

	errors := 0
	for _, ok := range cb.results {
		if !ok {
			errors++
		}
	}

	errorRate := float64(errors) / float64(len(cb.results))
	if errorRate >= cb.errorThreshold {
		cb.tripped = true
		cb.trippedAt = time.Now()
	}
}
