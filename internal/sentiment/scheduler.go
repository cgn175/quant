package sentiment

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/cgn175/quant-bot/internal/alerts"
	"github.com/rs/zerolog/log"
)

type Scheduler struct {
	client        *Client
	alertManager  *alerts.Manager
	scheduleTimes []string // e.g., ["08:00", "16:00"]
	done          chan struct{}
	symbols       []string
}

// NewScheduler creates a new sentiment scheduler
func NewScheduler(
	client *Client,
	alertManager *alerts.Manager,
	scheduleTimes []string,
	symbols []string,
) *Scheduler {
	return &Scheduler{
		client:        client,
		alertManager:  alertManager,
		scheduleTimes: scheduleTimes,
		symbols:       symbols,
		done:          make(chan struct{}),
	}
}

// Start begins the scheduler loop
func (s *Scheduler) Start() {
	go s.run()
}

// Stop stops the scheduler
func (s *Scheduler) Stop() {
	close(s.done)
}

func (s *Scheduler) run() {
	ticker := time.NewTicker(30 * time.Second) // Check every 30 seconds
	defer ticker.Stop()

	log.Info().
		Strs("times", s.scheduleTimes).
		Strs("symbols", s.symbols).
		Msg("sentiment scheduler started")

	for {
		select {
		case <-s.done:
			return
		case <-ticker.C:
			s.checkAndSend()
		}
	}
}

func (s *Scheduler) checkAndSend() {
	now := time.Now().UTC()
	currentTimeStr := fmt.Sprintf("%02d:%02d", now.Hour(), now.Minute())

	for _, scheduleTime := range s.scheduleTimes {
		// Check if current time matches any scheduled time (within a 1-minute window)
		if currentTimeStr == scheduleTime {
			s.sendSentimentSummary()
			time.Sleep(60 * time.Second) // Sleep to avoid duplicate sends
			return
		}
	}
}

func (s *Scheduler) sendSentimentSummary() {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	log.Info().Msg("sending sentiment summary notification")

	summary := s.buildSummary(ctx)
	if summary == "" {
		log.Warn().Msg("failed to build sentiment summary")
		return
	}

	s.alertManager.SendAlert(alerts.Alert{
		Type:      alerts.AlertTypeInfo,
		Title:     "📊 Market Sentiment Report",
		Message:   summary,
		Timestamp: time.Now(),
	})
}

func (s *Scheduler) buildSummary(ctx context.Context) string {
	parts := []string{"📊 *Market Sentiment Report*\n"}

	for _, symbol := range s.symbols {
		data := s.client.Get(symbol)
		if data == nil {
			continue
		}

		// Determine sentiment direction
		var sentimentEmoji string
		if data.Score24h > 0.3 {
			sentimentEmoji = "📈"
		} else if data.Score24h < -0.3 {
			sentimentEmoji = "📉"
		} else {
			sentimentEmoji = "➡️"
		}

		// Get historical data for trend
		history, err := s.client.FetchHistory(ctx, symbol, 7, "daily")
		trend := "→"
		if err == nil && len(history.Data) >= 2 {
			prev := history.Data[1].ScorePositive - history.Data[1].ScoreNegative
			curr := history.Data[0].ScorePositive - history.Data[0].ScoreNegative
			if curr > prev {
				trend = "↗️"
			} else if curr < prev {
				trend = "↘️"
			}
		}

		sourcesStr := strings.Join(data.Sources, ", ")

		symbolSummary := fmt.Sprintf(
			"%s *%s* %s\n  Score: %.2f (1h), %.2f (24h)\n  Mentions: %d (z-score: %.2f)\n  Sources: %s\n",
			sentimentEmoji,
			symbol,
			trend,
			data.Score1h,
			data.Score24h,
			data.Mentions,
			data.MentionsZScore,
			sourcesStr,
		)
		parts = append(parts, symbolSummary)
	}

	parts = append(parts, fmt.Sprintf("\n⏰ Updated: %s UTC", time.Now().UTC().Format("15:04")))
	return strings.Join(parts, "\n")
}
