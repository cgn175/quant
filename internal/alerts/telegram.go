package alerts

import (
	"fmt"
	"strings"
	"sync"
	"time"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
	"github.com/rs/zerolog"
)

// AlertType defines different alert severities
type AlertType int

const (
	AlertTypeInfo AlertType = iota
	AlertTypeWarning
	AlertTypeError
	AlertTypeCritical
)

// Alert represents a single alert message
type Alert struct {
	Type      AlertType
	Title     string
	Message   string
	Timestamp time.Time
	Symbol    string // optional
}

// Manager handles telegram alerts
type Manager struct {
	mu           sync.Mutex
	bot          *tgbotapi.BotAPI
	chatID       int64
	enabled      bool
	rateLimit    time.Duration
	lastAlertMap map[string]time.Time // prevent spam
	log          zerolog.Logger
}

// Config for alert manager
type Config struct {
	TelegramToken string
	ChatID        int64
	RateLimitMs   int
	Enabled       bool
}

// NewManager creates a new alert manager
func NewManager(cfg Config, log zerolog.Logger) (*Manager, error) {
	mgr := &Manager{
		chatID:       cfg.ChatID,
		enabled:      cfg.Enabled,
		rateLimit:    time.Duration(cfg.RateLimitMs) * time.Millisecond,
		lastAlertMap: make(map[string]time.Time),
		log:          log,
	}

	if !cfg.Enabled {
		log.Info().Msg("telegram alerts disabled")
		return mgr, nil
	}

	if cfg.TelegramToken == "" {
		return nil, fmt.Errorf("telegram token required when alerts enabled")
	}

	bot, err := tgbotapi.NewBotAPI(cfg.TelegramToken)
	if err != nil {
		return nil, fmt.Errorf("failed to create telegram bot: %w", err)
	}

	mgr.bot = bot
	log.Info().Str("username", bot.Self.UserName).Msg("telegram bot connected")

	return mgr, nil
}

// escapeMarkdownV2 escapes special characters for Telegram MarkdownV2.
func escapeMarkdownV2(s string) string {
	// Characters that must be escaped in MarkdownV2 (except * which we use for bold)
	special := []string{"_", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"}
	for _, ch := range special {
		s = strings.ReplaceAll(s, ch, "\\"+ch)
	}
	return s
}

// SendAlert sends an alert message
func (m *Manager) SendAlert(alert Alert) error {
	if !m.enabled || m.bot == nil {
		return nil
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	// Rate limit check
	key := strings.Join([]string{alert.Title, alert.Symbol}, ":")
	if lastTime, exists := m.lastAlertMap[key]; exists {
		if time.Since(lastTime) < m.rateLimit {
			return nil // Rate limited, skip
		}
	}
	m.lastAlertMap[key] = time.Now()

	// Format message with MarkdownV2 escaping
	emoji := getEmoji(alert.Type)
	escapedTitle := escapeMarkdownV2(alert.Title)
	escapedMessage := escapeMarkdownV2(alert.Message)
	escapedTime := escapeMarkdownV2(alert.Timestamp.Format("15:04:05 MST"))

	msg := fmt.Sprintf(
		"%s *%s*\n\n%s\n\nTime: %s",
		emoji,
		escapedTitle,
		escapedMessage,
		escapedTime,
	)

	if alert.Symbol != "" {
		escapedSymbol := escapeMarkdownV2(alert.Symbol)
		msg = fmt.Sprintf(
			"%s *%s* \\(%s\\)\n\n%s\n\nTime: %s",
			emoji,
			escapedTitle,
			escapedSymbol,
			escapedMessage,
			escapedTime,
		)
	}

	msgConfig := tgbotapi.NewMessage(m.chatID, msg)
	msgConfig.ParseMode = "MarkdownV2"

	// Try MarkdownV2 first; fall back to plain text if parsing fails.
	_, err := m.bot.Send(msgConfig)
	if err != nil {
		// Retry without parse mode (plain text) — handles unescaped special chars.
		msgConfig.ParseMode = ""
		msgConfig.Text = strings.ReplaceAll(msg, "*", "")
		_, err = m.bot.Send(msgConfig)
		if err != nil {
			m.log.Error().Err(err).Msg("failed to send telegram alert")
			return err
		}
	}

	return nil
}

// TradeOpened sends alert when a position is opened
func (m *Manager) TradeOpened(symbol string, side string, entryPrice, size float64) error {
	alert := Alert{
		Type:      AlertTypeInfo,
		Title:     fmt.Sprintf("%s Position Opened", strings.ToUpper(side)),
		Symbol:    symbol,
		Timestamp: time.Now(),
		Message: fmt.Sprintf(
			"Symbol: %s\nSide: %s\nEntry Price: $%.2f\nSize: %.4f",
			symbol, side, entryPrice, size,
		),
	}
	return m.SendAlert(alert)
}

// TradeClosed sends alert when a position is closed
func (m *Manager) TradeClosed(symbol string, side string, entryPrice, exitPrice, size, pnl float64, reason string) error {
	alertType := AlertTypeInfo
	if pnl < 0 {
		alertType = AlertTypeWarning
	}

	pnlPct := (pnl / (entryPrice * size)) * 100

	alert := Alert{
		Type:      alertType,
		Title:     fmt.Sprintf("%s Position Closed (%s)", strings.ToUpper(side), reason),
		Symbol:    symbol,
		Timestamp: time.Now(),
		Message: fmt.Sprintf(
			"Symbol: %s\nEntry: $%.2f\nExit: $%.2f\nSize: %.4f\nPnL: $%.2f (%.2f%%)",
			symbol, entryPrice, exitPrice, size, pnl, pnlPct,
		),
	}
	return m.SendAlert(alert)
}

// DailyPnLSummary sends daily summary
func (m *Manager) DailyPnLSummary(totalPnL, equity, winRate float64, trades int) error {
	alertType := AlertTypeInfo
	if totalPnL < 0 {
		alertType = AlertTypeWarning
	}

	alert := Alert{
		Type:      alertType,
		Title:     "Daily Summary",
		Timestamp: time.Now(),
		Message: fmt.Sprintf(
			"Total PnL: $%.2f\nEquity: $%.2f\nTrades: %d\nWin Rate: %.1f%%",
			totalPnL, equity, trades, winRate*100,
		),
	}
	return m.SendAlert(alert)
}

// DailyLossLimit sends alert when daily loss limit is breached
func (m *Manager) DailyLossLimit(dailyPnL, maxDailyLoss float64) error {
	alert := Alert{
		Type:      AlertTypeCritical,
		Title:     "Daily Loss Limit Breached",
		Timestamp: time.Now(),
		Message: fmt.Sprintf(
			"Current Daily PnL: $%.2f\nMax Daily Loss: $%.2f\n\nTrading halted for the day.",
			dailyPnL, maxDailyLoss,
		),
	}
	return m.SendAlert(alert)
}

// SentimentRegimeChange sends alert for sentiment regime shift
func (m *Manager) SentimentRegimeChange(symbol string, sentiment float64, regime string) error {
	alert := Alert{
		Type:      AlertTypeWarning,
		Title:     fmt.Sprintf("Sentiment Regime Change: %s", strings.ToUpper(regime)),
		Symbol:    symbol,
		Timestamp: time.Now(),
		Message: fmt.Sprintf(
			"Symbol: %s\nSentiment Score: %.2f\nRegime: %s\n\nAdjusting position sizing.",
			symbol, sentiment, regime,
		),
	}
	return m.SendAlert(alert)
}

// BotStarted sends alert when bot starts
func (m *Manager) BotStarted(config string) error {
	alert := Alert{
		Type:      AlertTypeInfo,
		Title:     "Bot Started",
		Timestamp: time.Now(),
		Message:   config,
	}
	return m.SendAlert(alert)
}

// BotStopped sends alert when bot stops
func (m *Manager) BotStopped(reason string) error {
	alert := Alert{
		Type:      AlertTypeCritical,
		Title:     "Bot Stopped",
		Timestamp: time.Now(),
		Message:   reason,
	}
	return m.SendAlert(alert)
}

// Error sends error alert
func (m *Manager) Error(title string, err error) error {
	alert := Alert{
		Type:      AlertTypeError,
		Title:     title,
		Timestamp: time.Now(),
		Message:   err.Error(),
	}
	return m.SendAlert(alert)
}

// getEmoji returns emoji based on alert type
func getEmoji(alertType AlertType) string {
	switch alertType {
	case AlertTypeInfo:
		return "ℹ️"
	case AlertTypeWarning:
		return "⚠️"
	case AlertTypeError:
		return "❌"
	case AlertTypeCritical:
		return "🚨"
	default:
		return "📌"
	}
}
