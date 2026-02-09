# Sentiment Integration Plan for Trading Bot

## Current State

### ✅ What's Already Implemented

**Sentiment Collection & Analysis:**
- Python microservice fetching from 9 sources (Reddit, NewsAPI, CoinGecko, CryptoPanic, etc.)
- FinBERT sentiment analysis
- SQLite persistence (hourly + daily aggregates, 7-day history)
- `/sentiment/{symbol}` endpoint returning scores, mentions, z-scores, velocity
- `/sentiment/{symbol}/insights` endpoint with themes, trends, alerts, baseline metrics

**Basic Integration (Existing):**
- `internal/sentiment/client.go` - Go client fetching sentiment data
- `internal/sentiment/scheduler.go` - Telegram notifications (twice daily)
- `internal/features/builder.go` - Sentiment features in FeatureVector:
  - `SentimentScore1h` (feature #30)
  - `SentimentScore24h` (feature #31)
  - `MentionsZScore` (feature #32)
  - `SentimentVelocity` (feature #33)
- `internal/strategy/signal.go` - **Basic filters already exist**:
  ```go
  // Don't go long if sentiment is too negative
  if fv.SentimentScore1h < s.config.SentimentThresholdLong { return false }
  
  // Don't go short if sentiment is too positive
  if fv.SentimentScore1h > s.config.SentimentThresholdShort { return false }
  
  // Reduce size by 50% if sentiment is extreme
  if fv.SentimentScore24h > s.config.SentimentExtremeLimit { return 0.5 }
  ```

**Configuration:**
```yaml
sentiment:
  enabled: false
  url: http://localhost:8000
  sentiment_threshold_long: 0.3
  sentiment_threshold_short: -0.3
```

### ❌ What's NOT Used Yet

**Advanced Insights Endpoint** (`/sentiment/{symbol}/insights`):
- ✅ Built but not consumed by Go bot
- 7-day baseline metrics (z-scores, percentiles, momentum)
- Regime detection (panic, news_driven, conflicted, quiet)
- 9 alert types (sentiment_breakout, attention_spike, security_shock, etc.)
- Theme analysis (regulation, security, adoption, etc.)
- Source diversity & agreement metrics

---

## Problem Statement

**You are correct:** The Go bot currently uses sentiment data only for:
1. **Basic entry filters** (don't long if negative, don't short if positive)
2. **Position sizing** (reduce size if extreme sentiment)
3. **Telegram reports** (twice-daily summaries)

**The bot does NOT use:**
- Advanced insights (alerts, regime, themes, momentum)
- 7-day baseline context (z-scores, percentiles)
- Actionable alerts (security shocks, sentiment breakouts)
- Source diversity signals

---

## Integration Plan

### Phase 1: Validate Sentiment Quality (CURRENT - Do This First)
**Goal:** Ensure sentiment data is reliable before using for trading

#### 1.1 Manual Testing (1-2 days)
```bash
# Test /sentiment endpoint
curl "http://localhost:8000/sentiment/BTCUSDT"

# Test /insights endpoint
curl "http://localhost:8000/sentiment/BTCUSDT/insights?lookback_hours=168"

# Monitor Telegram reports for accuracy
# - Do sentiment spikes correspond to real news events?
# - Are themes detected correctly?
# - Are alerts actionable?
```

**Quality Checklist:**
- [ ] Sentiment spikes align with known news events
- [ ] Negative security/regulation themes match actual incidents
- [ ] Source agreement metric is meaningful
- [ ] Alerts are not too frequent (noise) or too rare (miss events)
- [ ] Momentum signals lead price movements

#### 1.2 Data Quality Metrics (1 day)
Create validation script:
```python
# scripts/validate_sentiment_quality.py
# - Check for data gaps (hours with zero mentions)
# - Verify source diversity (not dominated by one source)
# - Calculate signal-to-noise ratio
# - Compare sentiment vs price correlation
```

#### 1.3 Backtesting Sentiment Signals (2-3 days)
```python
# In backtest engine, add sentiment validation:
# - Does sentiment_zscore_7d > 2.5 predict returns?
# - Does regime="panic" correlate with volatility?
# - Do security/regulation alerts precede price drops?
# - What's the optimal sentiment_threshold_long?
```

---

### Phase 2: Enhanced Entry/Exit Filters (After Validation)
**Goal:** Use insights endpoint for smarter trade filtering

#### 2.1 Add Insights Client to Go Bot
```go
// internal/sentiment/client.go

type InsightData struct {
    Symbol                 string                 `json:"symbol"`
    CurrentSentiment       float64                `json:"current_sentiment"`
    SentimentZScore7d      float64                `json:"sentiment_zscore_7d"`
    MentionsZScore7d       float64                `json:"mentions_zscore_7d"`
    SentimentPercentile7d  float64                `json:"sentiment_percentile_7d"`
    SentimentMomentum6h    float64                `json:"sentiment_momentum_6h"`
    SentimentMomentum24h   float64                `json:"sentiment_momentum_24h"`
    AttentionMomentum      float64                `json:"attention_momentum"`
    Regime                 string                 `json:"regime"`
    RegimeConfidence       float64                `json:"regime_confidence"`
    Alerts                 []Alert                `json:"alerts"`
    RecurringThemes        []string               `json:"recurring_themes"`
    SentimentByTheme       map[string]float64     `json:"sentiment_by_theme"`
    SourceAgreement        float64                `json:"source_agreement"`
}

type Alert struct {
    AlertType        string  `json:"alert_type"`
    Severity         string  `json:"severity"`
    TriggerValue     float64 `json:"trigger_value"`
    Description      string  `json:"description"`
    SuggestedAction  string  `json:"suggested_action"`
}

func (c *Client) FetchInsights(ctx context.Context, symbol string, lookbackHours int) (*InsightData, error) {
    url := fmt.Sprintf("%s/sentiment/%s/insights?lookback_hours=%d", c.baseURL, symbol, lookbackHours)
    // ... HTTP GET and JSON unmarshal
}
```

#### 2.2 Update Strategy Signal Logic
```go
// internal/strategy/signal.go

func (s *Strategy) shouldGoLong(fv *features.FeatureVector, pred *model.Prediction) bool {
    // ... existing checks ...
    
    // NEW: Fetch insights (cached, updated every 5-10 minutes)
    insights := s.sentimentClient.GetInsights(fv.Symbol)
    
    // Block long entries in high-risk regimes
    if insights.Regime == "panic" || insights.Regime == "conflicted" {
        log.Debug().
            Str("symbol", fv.Symbol).
            Str("regime", insights.Regime).
            Msg("blocking long: high-risk regime")
        return false
    }
    
    // Block if security or regulation shock
    for _, alert := range insights.Alerts {
        if alert.AlertType == "security_shock" || alert.AlertType == "regulation_risk" {
            if alert.Severity == "critical" || alert.Severity == "high" {
                log.Warn().
                    Str("symbol", fv.Symbol).
                    Str("alert", alert.AlertType).
                    Str("description", alert.Description).
                    Msg("blocking long: critical alert")
                return false
            }
        }
    }
    
    // Block if source agreement is too low (conflicting narratives)
    if insights.SourceAgreement < 0.3 {
        log.Debug().
            Str("symbol", fv.Symbol).
            Float64("agreement", insights.SourceAgreement).
            Msg("blocking long: low source agreement")
        return false
    }
    
    // Require stronger model signal if sentiment is mixed
    if insights.SentimentZScore7d < 1.0 && pred.ProbUp < s.config.ThresholdUp + 0.05 {
        log.Debug().
            Str("symbol", fv.Symbol).
            Msg("blocking long: weak sentiment + marginal model signal")
        return false
    }
    
    return true
}

func (s *Strategy) shouldExitLong(position *execution.Position, fv *features.FeatureVector) bool {
    insights := s.sentimentClient.GetInsights(fv.Symbol)
    
    // Emergency exit on critical alerts
    for _, alert := range insights.Alerts {
        if alert.Severity == "critical" {
            log.Warn().
                Str("symbol", fv.Symbol).
                Str("alert", alert.AlertType).
                Msg("emergency exit: critical alert")
            return true
        }
    }
    
    // Exit if regime shifts to panic
    if insights.Regime == "panic" && insights.RegimeConfidence > 0.8 {
        log.Info().
            Str("symbol", fv.Symbol).
            Msg("exit: regime shifted to panic")
        return true
    }
    
    // Exit if negative momentum surge
    if insights.SentimentMomentum6h < -0.2 && insights.SentimentMomentum24h < -0.15 {
        log.Info().
            Str("symbol", fv.Symbol).
            Msg("exit: strong negative momentum")
        return true
    }
    
    return false // Default: keep position
}
```

#### 2.3 Update Position Sizing
```go
// internal/risk/manager.go

func (rm *Manager) CalculatePositionSize(ctx context.Context, symbol string, signal string, price float64) (float64, error) {
    // ... existing base size calculation ...
    
    insights := rm.sentimentClient.GetInsights(symbol)
    
    // Reduce size in high-risk regimes
    if insights.Regime == "panic" {
        baseSize *= 0.25 // Trade very small in panic
    } else if insights.Regime == "conflicted" {
        baseSize *= 0.5 // Reduce size when sources disagree
    }
    
    // Boost size on high-confidence bullish signals
    if signal == "long" {
        if insights.SentimentZScore7d > 2.0 && insights.SourceAgreement > 0.7 {
            baseSize *= 1.5 // 50% larger position on strong consensus
        }
    }
    
    // Reduce size if any high-severity alerts
    for _, alert := range insights.Alerts {
        if alert.Severity == "high" || alert.Severity == "critical" {
            baseSize *= 0.5
            break
        }
    }
    
    return baseSize, nil
}
```

---

### Phase 3: Alert-Driven Actions (Advanced)
**Goal:** React to real-time sentiment events

#### 3.1 Alert Monitoring Service
```go
// internal/sentiment/alert_monitor.go

type AlertMonitor struct {
    client       *Client
    alertManager *alerts.Manager
    symbols      []string
    checkInterval time.Duration
}

func (am *AlertMonitor) Start(ctx context.Context) {
    ticker := time.NewTicker(am.checkInterval) // Every 5 minutes
    defer ticker.Stop()
    
    for {
        select {
        case <-ticker.C:
            am.checkAlerts(ctx)
        case <-ctx.Done():
            return
        }
    }
}

func (am *AlertMonitor) checkAlerts(ctx context.Context) {
    for _, symbol := range am.symbols {
        insights, err := am.client.FetchInsights(ctx, symbol, 24)
        if err != nil {
            continue
        }
        
        for _, alert := range insights.Alerts {
            // Only notify on critical/high severity
            if alert.Severity == "critical" || alert.Severity == "high" {
                am.alertManager.Send(alerts.Alert{
                    Type:     alerts.TypeSentimentAlert,
                    Severity: alerts.Severity(alert.Severity),
                    Symbol:   symbol,
                    Title:    fmt.Sprintf("🚨 %s: %s", symbol, alert.AlertType),
                    Message:  fmt.Sprintf("%s\n\n💡 %s", alert.Description, alert.SuggestedAction),
                })
            }
        }
    }
}
```

#### 3.2 Telegram Command for Insights
```go
// internal/alerts/telegram.go

func (m *Manager) handleInsightsCommand(chatID int64, args []string) {
    if len(args) < 1 {
        m.sendMessage(chatID, "Usage: /insights BTCUSDT [lookback_hours]")
        return
    }
    
    symbol := strings.ToUpper(args[0])
    lookbackHours := 24
    if len(args) > 1 {
        if h, err := strconv.Atoi(args[1]); err == nil {
            lookbackHours = h
        }
    }
    
    insights, err := m.sentimentClient.FetchInsights(context.Background(), symbol, lookbackHours)
    if err != nil {
        m.sendMessage(chatID, fmt.Sprintf("❌ Failed to fetch insights: %v", err))
        return
    }
    
    msg := formatInsightsMessage(insights)
    m.sendMessage(chatID, msg)
}

func formatInsightsMessage(insights *sentiment.InsightData) string {
    var b strings.Builder
    
    b.WriteString(fmt.Sprintf("🔍 *%s Sentiment Insights*\n\n", insights.Symbol))
    
    // Current sentiment
    b.WriteString(fmt.Sprintf("📊 *Current Sentiment:* %.2f\n", insights.CurrentSentiment))
    b.WriteString(fmt.Sprintf("📈 *7d Z-Score:* %.2f (Percentile: %.0f%%)\n", 
        insights.SentimentZScore7d, insights.SentimentPercentile7d))
    
    // Momentum
    b.WriteString(fmt.Sprintf("\n⚡ *Momentum*\n"))
    b.WriteString(fmt.Sprintf("  6h: %.3f\n", insights.SentimentMomentum6h))
    b.WriteString(fmt.Sprintf("  24h: %.3f\n", insights.SentimentMomentum24h))
    
    // Regime
    emoji := map[string]string{
        "panic": "🔴", "conflicted": "🟡", "news_driven": "🔵", 
        "quiet": "🟢", "normal": "⚪",
    }[insights.Regime]
    b.WriteString(fmt.Sprintf("\n%s *Regime:* %s (%.0f%% confidence)\n", 
        emoji, insights.Regime, insights.RegimeConfidence*100))
    
    // Alerts
    if len(insights.Alerts) > 0 {
        b.WriteString("\n🚨 *Active Alerts:*\n")
        for _, alert := range insights.Alerts {
            severityEmoji := map[string]string{
                "critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢",
            }[alert.Severity]
            b.WriteString(fmt.Sprintf("%s %s: %s\n", 
                severityEmoji, alert.AlertType, alert.Description))
        }
    }
    
    // Themes
    if len(insights.RecurringThemes) > 0 {
        b.WriteString("\n💬 *Themes:*\n")
        for _, theme := range insights.RecurringThemes {
            sent := insights.SentimentByTheme[theme]
            emoji := "↗️"
            if sent < -0.2 {
                emoji = "↘️"
            } else if sent < 0.2 {
                emoji = "→"
            }
            b.WriteString(fmt.Sprintf("  %s %s: %.2f\n", emoji, theme, sent))
        }
    }
    
    return b.String()
}
```

---

### Phase 4: ML Model Integration (Optional, Long-term)

#### 4.1 Add Insights Features to FeatureVector
```go
// internal/features/builder.go

type FeatureVector struct {
    // ... existing 33 features ...
    
    // NEW: Advanced sentiment features (34-43)
    SentimentZScore7d     float64
    MentionsZScore7d      float64
    SentimentPercentile7d float64
    SentimentMomentum6h   float64
    SentimentMomentum24h  float64
    AttentionMomentum     float64
    RegimeIsPanic         float64 // 1.0 if panic, else 0.0
    RegimeIsConflicted    float64
    HasCriticalAlert      float64
    SourceAgreement       float64
}
```

#### 4.2 Retrain Model
```bash
# scripts/build_features.py
# - Add new columns from /insights endpoint
# - Backfill historical insights data
# - Retrain ONNX model with 43 features instead of 33
# - Validate improved accuracy
```

---

## Configuration Changes

```yaml
sentiment:
  enabled: true  # Enable sentiment integration
  url: http://localhost:8000
  
  # Basic thresholds (already exist)
  sentiment_threshold_long: 0.3
  sentiment_threshold_short: -0.3
  sentiment_extreme_limit: 0.8
  
  # NEW: Insights integration
  insights_enabled: true
  insights_lookback_hours: 24
  insights_cache_duration: 300  # 5 minutes
  
  # NEW: Regime-based filters
  block_long_in_panic: true
  block_long_in_conflicted: true
  reduce_size_in_panic: 0.25
  reduce_size_in_conflicted: 0.5
  
  # NEW: Alert handling
  alert_monitor_enabled: true
  alert_check_interval: 300  # 5 minutes
  block_entry_on_critical_alerts: true
  exit_on_security_shock: true
  
  # NEW: Source diversity
  min_source_agreement_long: 0.3
  min_sources_required: 3
  
  # NEW: Position sizing boosts
  boost_size_on_high_zscore: 1.5  # 50% larger if zscore > 2.0
  boost_threshold_zscore: 2.0
```

---

## Testing Strategy

### Unit Tests
```go
// internal/sentiment/client_test.go
func TestFetchInsights(t *testing.T) { /* ... */ }

// internal/strategy/signal_test.go
func TestBlockLongInPanicRegime(t *testing.T) { /* ... */ }
func TestExitOnSecurityShock(t *testing.T) { /* ... */ }
```

### Integration Tests
```bash
# Test with mock sentiment service
go test -v ./internal/strategy/... -tags=integration

# Test alert monitoring
go test -v ./internal/sentiment/... -run TestAlertMonitor
```

### Live Testing (Paper Trading)
```yaml
# config.paper.yaml
mode: paper
sentiment:
  enabled: true
  insights_enabled: true
  alert_monitor_enabled: true

# Run for 1-2 weeks, monitor:
# - How often regimes block entries
# - How many positions exit early on alerts
# - Impact on P&L vs baseline (no sentiment)
```

---

## Rollout Plan

### Week 1: Validation ✅ **(DO THIS FIRST)**
- [ ] Test /insights endpoint manually for 3-5 symbols
- [ ] Monitor Telegram reports for quality
- [ ] Create data quality validation script
- [ ] Run correlation analysis (sentiment vs price)

### Week 2-3: Basic Integration (If Quality Good)
- [ ] Implement `FetchInsights()` in Go client
- [ ] Add regime-based entry filters
- [ ] Add alert-based exit logic
- [ ] Deploy to paper trading

### Week 4-5: Advanced Features
- [ ] Implement alert monitoring service
- [ ] Add position sizing adjustments
- [ ] Add Telegram `/insights` command
- [ ] Test with live testnet

### Week 6+: Production (If Paper Trading Successful)
- [ ] Gradual rollout to production (25% → 50% → 100%)
- [ ] Monitor P&L impact
- [ ] Tune thresholds based on real data
- [ ] Consider ML model retraining with insights features

---

## Success Metrics

**Sentiment Quality (Phase 1):**
- [ ] >70% of sentiment spikes align with known news
- [ ] Alerts have <20% false positive rate
- [ ] Source diversity metric is stable (not all from one source)
- [ ] Correlation with price movements is statistically significant

**Trading Impact (Phase 2-3):**
- [ ] Reduced drawdown during market panic (regime detection works)
- [ ] Improved win rate on long entries (better timing)
- [ ] Fewer losses on unexpected news (alert-based exits)
- [ ] Position sizing adjustments increase risk-adjusted returns

**Long-term Goals:**
- [ ] 10-20% improvement in Sharpe ratio
- [ ] 30%+ reduction in max drawdown
- [ ] Profitable even without ML model (sentiment-only strategy)

---

## Risks & Mitigation

### Risk 1: Sentiment Data Quality is Poor
**Mitigation:**
- Start with Phase 1 validation
- Don't integrate until quality is proven
- Use multiple sources (already done)
- Monitor data gaps and stale data

### Risk 2: Alerts are Too Noisy
**Mitigation:**
- Tune thresholds (zscore > 2.5 is conservative)
- Only act on critical/high severity
- Add cooldown period (don't react to same alert twice in 1h)

### Risk 3: Regime Detection is Inaccurate
**Mitigation:**
- Start with conservative actions (don't block ALL entries)
- Only reduce position size initially
- Monitor regime transition frequency
- Add manual override in config

### Risk 4: Performance Degradation
**Mitigation:**
- Cache insights (5-10 minute TTL)
- Async fetching (don't block trading loop)
- Fallback to basic sentiment if /insights fails
- Set timeouts (max 2s for insights request)

---

## Open Questions

1. **Should insights fetch be synchronous or async?**
   - Sync: Simple, but may add latency to entry decisions
   - Async: Fast, but need to handle stale data

2. **How often should we poll /insights?**
   - Every tick? (Expensive, 1 request per symbol per minute)
   - Every 5 minutes? (Cached, good balance)
   - On-demand? (Only when considering entry/exit)

3. **Should we retrain ML model with insights features?**
   - Pro: Model learns to use sentiment context
   - Con: Need historical backfill, more complex pipeline

4. **What's the minimum data quality threshold?**
   - 50% correlation with price? 70%? 80%?
   - How many false alerts are acceptable?

---

## Next Steps (Immediate)

1. **Manual Quality Check (You Do This):**
   ```bash
   # Monitor for 2-3 days:
   curl "http://localhost:8000/sentiment/BTCUSDT/insights?lookback_hours=168" | jq
   curl "http://localhost:8000/sentiment/ETHUSDT/insights?lookback_hours=168" | jq
   
   # Check Telegram reports
   # Compare alerts to real events (check crypto news sites)
   ```

2. **Create Validation Script (I Can Help):**
   ```python
   # scripts/validate_sentiment.py
   # Run this daily for 1 week, review output
   ```

3. **Decision Point:**
   - **If quality is good:** Proceed to Phase 2 (Go integration)
   - **If quality is mediocre:** Tune sentiment thresholds, add more sources
   - **If quality is poor:** Fix data collection issues first

---

## Summary

**Current State:**
- ✅ Sentiment data is collected and analyzed
- ✅ Basic filters exist (threshold-based)
- ✅ Telegram reporting works
- ❌ **Advanced insights are NOT used for trading**

**Recommendation:**
1. **Validate sentiment quality first** (1-2 weeks)
2. If good, integrate insights for entry/exit filters (2-3 weeks)
3. Add alert monitoring and dynamic position sizing (2-3 weeks)
4. Optional: Retrain ML model with insights features (4-6 weeks)

**Next Action:**
- Save this plan ✅
- **You:** Manually test sentiment quality for 3-5 days
- **Me:** Create validation scripts if needed
- **Decision:** Meet again after quality check to proceed or pivot
