package alerts

import (
	"context"
	"fmt"
	"runtime"
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

// StatusProvider is an interface for components that can provide status information.
type StatusProvider interface {
	GetStatusInfo() StatusInfo
}

// StatusInfo contains bot status information for the /status command.
type StatusInfo struct {
	Mode             string
	Uptime           time.Duration
	OpenPositions    int
	DailyPnL         float64
	Equity           float64
	CandlesPerSymbol map[string]int64
	LastCandleTime   map[string]time.Time
	WebSocketStatus  string
	MemoryUsageMB    float64
}

// SentimentProvider is an interface for sentiment data.
type SentimentProvider interface {
	GetSymbols() []string
	GetSentimentData(symbol string) map[string]interface{}
}

// Manager handles telegram alerts
type Manager struct {
	mu                sync.Mutex
	bot               *tgbotapi.BotAPI
	chatID            int64
	enabled           bool
	rateLimit         time.Duration
	lastAlertMap      map[string]time.Time // prevent spam
	log               zerolog.Logger
	startTime         time.Time
	statusProvider    StatusProvider
	sentimentProvider SentimentProvider
	cancelFunc        context.CancelFunc
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
		startTime:    time.Now(),
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

// SetStatusProvider sets the status provider for the /status command.
func (m *Manager) SetStatusProvider(provider StatusProvider) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.statusProvider = provider
}

// SetSentimentProvider sets the sentiment provider for the /markets-news command.
func (m *Manager) SetSentimentProvider(provider SentimentProvider) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.sentimentProvider = provider
}

// StartCommandListener starts listening for Telegram commands in a background goroutine.
// Call Stop() to stop the listener.
func (m *Manager) StartCommandListener(ctx context.Context) {
	if !m.enabled || m.bot == nil {
		return
	}

	// Create a cancellable context for the command listener
	listenerCtx, cancel := context.WithCancel(ctx)
	m.mu.Lock()
	m.cancelFunc = cancel
	m.mu.Unlock()

	go m.commandLoop(listenerCtx)
	m.log.Info().Msg("telegram command listener started")
}

// Stop stops the command listener.
func (m *Manager) Stop() {
	m.mu.Lock()
	if m.cancelFunc != nil {
		m.cancelFunc()
	}
	m.mu.Unlock()
}

// commandLoop listens for incoming Telegram commands.
func (m *Manager) commandLoop(ctx context.Context) {
	u := tgbotapi.NewUpdate(0)
	u.Timeout = 30

	updates := m.bot.GetUpdatesChan(u)

	for {
		select {
		case <-ctx.Done():
			m.log.Info().Msg("telegram command listener stopped")
			return
		case update := <-updates:
			if update.Message == nil || !update.Message.IsCommand() {
				continue
			}

			// Only respond to messages from the configured chat
			if update.Message.Chat.ID != m.chatID {
				continue
			}

			switch update.Message.Command() {
			case "status":
				m.handleStatusCommand(update.Message)
			case "markets-news":
				m.handleMarketsNewsCommand(update.Message)
			case "help":
				m.handleHelpCommand(update.Message)
			}
		}
	}
}

// handleStatusCommand handles the /status command.
func (m *Manager) handleStatusCommand(msg *tgbotapi.Message) {
	m.mu.Lock()
	provider := m.statusProvider
	startTime := m.startTime
	m.mu.Unlock()

	var statusMsg string

	if provider != nil {
		info := provider.GetStatusInfo()

		// Format uptime
		uptime := time.Since(startTime)
		uptimeStr := formatDuration(uptime)

		// Format candles per symbol
		var candleLines []string
		for sym, count := range info.CandlesPerSymbol {
			lastTime := ""
			if t, ok := info.LastCandleTime[sym]; ok && !t.IsZero() {
				lastTime = fmt.Sprintf(" (last: %s)", t.Format("15:04:05"))
			}
			candleLines = append(candleLines, fmt.Sprintf("  %s: %d%s", sym, count, lastTime))
		}
		candlesStr := strings.Join(candleLines, "\n")
		if candlesStr == "" {
			candlesStr = "  No data yet"
		}

		// Get memory stats
		var memStats runtime.MemStats
		runtime.ReadMemStats(&memStats)
		memMB := float64(memStats.Alloc) / 1024 / 1024

		statusMsg = fmt.Sprintf(`📊 *Bot Status*

*Mode:* %s
*Uptime:* %s
*Open Positions:* %d
*Daily PnL:* $%.2f
*Equity:* $%.2f

*Candles Received:*
%s

*WebSocket:* %s
*Memory:* %.1f MB`,
			escapeMarkdownV2(info.Mode),
			escapeMarkdownV2(uptimeStr),
			info.OpenPositions,
			info.DailyPnL,
			info.Equity,
			escapeMarkdownV2(candlesStr),
			escapeMarkdownV2(info.WebSocketStatus),
			memMB,
		)
	} else {
		// Fallback if no provider set
		uptime := time.Since(startTime)
		var memStats runtime.MemStats
		runtime.ReadMemStats(&memStats)
		memMB := float64(memStats.Alloc) / 1024 / 1024

		statusMsg = fmt.Sprintf(`📊 *Bot Status*

*Uptime:* %s
*Memory:* %.1f MB

_Status provider not configured_`,
			escapeMarkdownV2(formatDuration(uptime)),
			memMB,
		)
	}

	reply := tgbotapi.NewMessage(msg.Chat.ID, statusMsg)
	reply.ParseMode = "MarkdownV2"
	reply.ReplyToMessageID = msg.MessageID

	if _, err := m.bot.Send(reply); err != nil {
		// Retry without markdown
		reply.ParseMode = ""
		reply.Text = strings.ReplaceAll(statusMsg, "*", "")
		reply.Text = strings.ReplaceAll(reply.Text, "_", "")
		m.bot.Send(reply)
	}
}

// handleMarketsNewsCommand handles the /markets-news command.
func (m *Manager) handleMarketsNewsCommand(msg *tgbotapi.Message) {
	m.mu.Lock()
	provider := m.sentimentProvider
	m.mu.Unlock()

	var newsMsg string

	if provider == nil {
		newsMsg = "❌ Sentiment service not available. Please configure sentiment in config.yaml"
	} else {
		symbols := provider.GetSymbols()
		if len(symbols) == 0 {
			newsMsg = "⚠️ No symbols configured for sentiment analysis"
		} else {
			var lines []string
			lines = append(lines, "📰 *Market Sentiment News*\n")

			for _, symbol := range symbols {
				sentimentData := provider.GetSentimentData(symbol)
				if sentimentData == nil {
					continue
				}

				// Extract data
				score24h, _ := sentimentData["score_24h"].(float64)
				mentions, _ := sentimentData["mentions"].(int)
				velocity, _ := sentimentData["velocity"].(float64)
				sources, _ := sentimentData["sources"].([]string)

				// Determine emoji based on score
				emoji := "➡️"
				if score24h > 0.3 {
					emoji = "📈"
				} else if score24h < -0.3 {
					emoji = "📉"
				}

				sourcesStr := "reddit"
				if len(sources) > 0 {
					sourcesStr = strings.Join(sources, ", ")
				}

				symbolLine := fmt.Sprintf("%s *%s*\n  Score: %.2f | Mentions: %d | Velocity: %.2f\n  Sources: %s",
					emoji, symbol, score24h, mentions, velocity, sourcesStr)
				lines = append(lines, symbolLine)
			}

			lines = append(lines, fmt.Sprintf("\n⏰ Updated: %s UTC", time.Now().UTC().Format("15:04")))
			newsMsg = strings.Join(lines, "\n")
		}
	}

	reply := tgbotapi.NewMessage(msg.Chat.ID, newsMsg)
	reply.ParseMode = "MarkdownV2"
	reply.ReplyToMessageID = msg.MessageID

	if _, err := m.bot.Send(reply); err != nil {
		// Retry without markdown
		reply.ParseMode = ""
		reply.Text = strings.ReplaceAll(newsMsg, "*", "")
		reply.Text = strings.ReplaceAll(reply.Text, "_", "")
		m.bot.Send(reply)
	}
}

// handleHelpCommand handles the /help command.
func (m *Manager) handleHelpCommand(msg *tgbotapi.Message) {
	helpMsg := `🤖 *Quant Bot Commands*

/status \\- Show bot status and health info
/markets\\-news \\- Show market sentiment news
/help \\- Show this help message`

	reply := tgbotapi.NewMessage(msg.Chat.ID, helpMsg)
	reply.ParseMode = "MarkdownV2"
	reply.ReplyToMessageID = msg.MessageID

	if _, err := m.bot.Send(reply); err != nil {
		reply.ParseMode = ""
		reply.Text = strings.ReplaceAll(helpMsg, "*", "")
		reply.Text = strings.ReplaceAll(reply.Text, "\\", "")
		m.bot.Send(reply)
	}
}

// ...existing code...

// formatDuration formats a duration in a human-readable way.
func formatDuration(d time.Duration) string {
	days := int(d.Hours() / 24)
	hours := int(d.Hours()) % 24
	minutes := int(d.Minutes()) % 60

	if days > 0 {
		return fmt.Sprintf("%dd %dh %dm", days, hours, minutes)
	}
	if hours > 0 {
		return fmt.Sprintf("%dh %dm", hours, minutes)
	}
	return fmt.Sprintf("%dm", minutes)
}

// mdv2Replacer escapes all special characters for Telegram MarkdownV2.
// Order matters: backslash must be escaped first to avoid double-escaping.
var mdv2Replacer = strings.NewReplacer(
	`\`, `\\`,
	`_`, `\_`,
	`*`, `\*`,
	`[`, `\[`,
	`]`, `\]`,
	`(`, `\(`,
	`)`, `\)`,
	`~`, `\~`,
	"`", "\\`",
	`>`, `\>`,
	`#`, `\#`,
	`+`, `\+`,
	`-`, `\-`,
	`=`, `\=`,
	`|`, `\|`,
	`{`, `\{`,
	`}`, `\}`,
	`.`, `\.`,
	`!`, `\!`,
)

// escapeMarkdownV2 escapes special characters for Telegram MarkdownV2.
func escapeMarkdownV2(s string) string {
	return mdv2Replacer.Replace(s)
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

// PartialExit sends alert when a partial position is closed at an R-target
func (m *Manager) PartialExit(symbol string, side string, entryPrice, exitPrice, exitSize, remainingSize, pnl float64, reason string, stopMovedToBE bool) error {
	// Map reason to human-readable label
	reasonLabel := reason
	switch reason {
	case "partial_3r":
		reasonLabel = "3R Target"
	case "partial_6r":
		reasonLabel = "6R Target"
	}

	pnlPct := 0.0
	if entryPrice > 0 && exitSize > 0 {
		pnlPct = (pnl / (entryPrice * exitSize)) * 100
	}

	stopNote := ""
	if stopMovedToBE {
		stopNote = "\n⚡ Stop moved to breakeven"
	}

	alert := Alert{
		Type:      AlertTypeInfo,
		Title:     fmt.Sprintf("Partial Exit (%s)", reasonLabel),
		Symbol:    symbol,
		Timestamp: time.Now(),
		Message: fmt.Sprintf(
			"Symbol: %s\nSide: %s\nEntry: $%.2f\nExit: $%.2f\nClosed: %.4f\nRemaining: %.4f\nPnL: $%.2f (%.2f%%)%s",
			symbol, strings.ToUpper(side), entryPrice, exitPrice, exitSize, remainingSize, pnl, pnlPct, stopNote,
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
