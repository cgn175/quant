# Historical Sentiment Data Usage & Strategy

## Current State

### What Gets Backfilled on First Run
- **Trigger**: On startup, if `sentiment_db.has_any_data()` returns `False`
- **Symbols**: `DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]`
- **Time Range**: Last 7 days
- **Data Saved**: **Daily aggregates only** (`sentiment_daily` table)
- **Limitation**: `/insights` endpoint reads **hourly** data, so first-run trend detection is weak

### Current Usage of Historical Data

#### 1. `/sentiment/{symbol}/insights` Endpoint
```python
# Gets hourly data (up to 168h = 7 days)
hourly_data = await sentiment_db.get_hourly_sentiment(symbol, hours=lookback_hours)

# Used for:
- Trend detection (comparing recent 24h vs previous 24h)
- Anomaly detection (z-score vs all historical scores)
- Confidence intervals (95% CI from recent scores)
- Volatility calculation (stdev of recent scores)
```

**Problem**: If DB only has daily backfill, hourly query returns little/no data on first run.

#### 2. `/sentiment/{symbol}` Endpoint
```python
# Uses 24h in-memory post_history for:
- mentions_zscore (anomaly detection)
- velocity (sentiment rate-of-change)

# Problem: Only 24h window, not using 7-day DB history
```

#### 3. Persisted Hourly Data Issues
Current `compute_sentiment()` stores:
- `mentions_count = len(posts_24h)` ← **24h rolling, not hourly**
- `score_positive/negative/neutral` ← computed from **all posts, not just that hour**

This makes historical analysis unreliable.

---

## Recommended Improvements (Priority Order)

### 🔴 **P0: Fix Hourly Sentiment Persistence** (Issue: `quant-8ac`)
**Problem**: Hourly rows don't represent actual hours, breaking trend analysis.

**Solution**:
```python
# Instead of storing 24h rolling counts:
mentions_count = len(posts_24h)  # ❌ WRONG

# Store true hourly data:
hour_ago = now - timedelta(hours=1)
posts_this_hour = [p for p in posts if p.timestamp >= hour_ago]
mentions_count = len(posts_this_hour)  # ✅ CORRECT

# Use hour-truncated timestamps:
hour_bucket = now.replace(minute=0, second=0, microsecond=0)
```

**Impact**: Enables accurate historical trend analysis over 7 days.

---

### 🟡 **P1: Backfill Hourly Data** (Issue: `quant-9xe`)
**Problem**: Backfill only writes daily, but insights reads hourly.

**Solution**:
```python
async def backfill_symbol_history(symbol: str, cutoff: datetime):
    # ... fetch posts ...
    
    # Create hourly buckets (not just daily)
    hourly_buckets: dict[str, dict] = {}
    for post, sent in zip(posts, sentiments):
        if post.timestamp < cutoff:
            continue
        
        # Bucket by hour
        hour_key = post.timestamp.replace(
            minute=0, second=0, microsecond=0
        ).isoformat()
        
        bucket = hourly_buckets.setdefault(hour_key, {...})
        # ... accumulate ...
    
    # Save both hourly and daily
    for hour_key, bucket in hourly_buckets.items():
        await sentiment_db.save_hourly_sentiment(...)
    
    # Also roll up to daily for long-term storage
    for date_key, bucket in daily_buckets.items():
        await sentiment_db.save_daily_sentiment(...)
```

**Impact**: First-run trend detection works properly with 7-day context.

---

### 🟡 **P1: Use 7-Day DB for Z-Score/Velocity** (Issue: `quant-suy`)
**Problem**: Currently uses 24h in-memory data, ignoring 7-day DB history.

**Solution**:
```python
async def compute_mentions_zscore_from_db(
    symbol: str, 
    current_mentions: int
) -> float:
    """Calculate z-score using 7-day DB history."""
    history = await sentiment_db.get_mention_history(symbol, hours=168)
    
    if len(history) < 10:
        return 0.0
    
    hourly_counts = [row["count"] for row in history]
    mean = statistics.mean(hourly_counts)
    stdev = statistics.stdev(hourly_counts)
    
    if stdev == 0:
        return 0.0
    
    return (current_mentions - mean) / stdev

async def compute_velocity_from_db(symbol: str) -> float:
    """Calculate velocity using 7-day DB history."""
    history = await sentiment_db.get_hourly_sentiment(symbol, hours=24)
    
    if len(history) < 10:
        return 0.0
    
    recent_scores = [
        row["score_positive"] - row["score_negative"] 
        for row in history[-6:]  # Last 6 hours
    ]
    older_scores = [
        row["score_positive"] - row["score_negative"]
        for row in history[-24:-6]  # Previous 18 hours
    ]
    
    if not recent_scores or not older_scores:
        return 0.0
    
    return statistics.mean(recent_scores) - statistics.mean(older_scores)
```

**Impact**: Anomaly detection becomes meaningful over 7-day baseline.

---

### 🟢 **P2: Add 7-Day Baseline Metrics** (Issue: `quant-3y1`)
Extend `/insights` response with relative metrics:

```python
@dataclass
class BaselineMetrics:
    """7-day context metrics for trading decisions."""
    
    # Relative position
    sentiment_zscore_7d: float  # How extreme vs 7d baseline
    mentions_zscore_7d: float   # Attention anomaly
    sentiment_percentile_7d: float  # 0-100, more robust than z-score
    
    # Momentum
    sentiment_momentum_6h: float   # Recent vs 6h ago
    sentiment_momentum_24h: float  # Recent vs 24h ago
    attention_momentum: float      # Mentions rate-of-change
    
    # Regime
    regime: str  # "quiet", "news-driven", "conflicted", "panic"
    regime_confidence: float
```

**Usage in Trading Strategy**:
```python
# Entry filter example
if (
    insights.signal == "bullish" 
    and insights.sentiment_zscore_7d > 1.5  # Above normal
    and insights.mentions_zscore_7d > 2.0   # Unusual attention
    and insights.source_agreement > 0.7     # Sources agree
    and insights.volatility < 0.25          # Not too volatile
):
    # High-confidence buy signal
    position_size = base_size * insights.confidence
```

---

### 🟢 **P2: Add Alert Conditions** (Issue: `quant-sn9`)
Implement specific tradable alerts:

```python
@dataclass
class SentimentAlert:
    """Alert condition based on 7-day context."""
    
    alert_type: str  # Type of alert
    severity: str    # "low", "medium", "high", "critical"
    trigger_value: float
    threshold: float
    description: str
    suggested_action: str

# Alert types:
ALERT_TYPES = {
    "sentiment_breakout": {
        "condition": lambda: sentiment_zscore_7d > 2.5,
        "action": "Consider entry if confirmed by price",
    },
    "attention_spike": {
        "condition": lambda: mentions_zscore_7d > 3.0,
        "action": "Monitor for significant news/events",
    },
    "agreement_collapse": {
        "condition": lambda: source_agreement < 0.3 and prev_agreement > 0.7,
        "action": "Reduce position size, conflicting narratives",
    },
    "security_shock": {
        "condition": lambda: (
            "security" in themes 
            and sentiment_by_theme["security"] < -0.4
            and mentions_zscore_7d > 2.0
        ),
        "action": "Consider exit, security risk elevated",
    },
    "regulation_risk": {
        "condition": lambda: (
            "regulation" in themes
            and sentiment_by_theme["regulation"] < -0.3
            and trend_direction == "deteriorating"
        ),
        "action": "Reduce exposure, regulatory headwinds",
    },
}
```

---

## Trading Strategy Integration

### Entry Signals (from `/insights`)
```python
# Strong entry
if (
    signal == "strong_bullish"
    and confidence > 0.7
    and sentiment_zscore_7d > 1.5
    and mentions_zscore_7d > 2.0
    and risk_level == "low"
):
    enter_long(size=max_size)

# Moderate entry
elif (
    signal == "bullish"
    and confidence > 0.5
    and sentiment_momentum_24h > 0.1
    and source_agreement > 0.6
):
    enter_long(size=base_size)
```

### Exit Signals
```python
# Emergency exit
if alert_type == "security_shock" and severity == "critical":
    exit_all_positions()

# Normal exit
if (
    signal == "bearish"
    or sentiment_momentum_24h < -0.15
    or agreement_collapse_detected
):
    exit_positions(percentage=50)
```

### Position Sizing
```python
# Scale size by confidence and volatility
base_size = account_size * risk_per_trade

adjusted_size = base_size * (
    insights.confidence
    * (1.0 - insights.volatility)  # Reduce in high vol
    * min(2.0, 1.0 + insights.sentiment_zscore_7d / 2.0)  # Boost on extremes
)
```

### Risk Management
```python
# Dynamic stop based on volatility and regime
if insights.regime == "panic":
    stop_distance = atr * 2.0  # Wider stops
elif insights.volatility > 0.3:
    stop_distance = atr * 1.5
else:
    stop_distance = atr * 1.0
```

---

## Visualization Opportunities

### 1. Sentiment Timeline (7 days)
```
Sentiment Score
   0.5 |                    ●●●
   0.3 |           ●●●   ●●
   0.1 |     ●●●●
  -0.1 |  ●●●
  -0.3 |
       +--------------------
       Day1  Day3  Day5  Day7
       
Current: 0.45 (↗️ improving)
Z-score: 2.1 (unusual)
```

### 2. Mentions Heatmap
```
Hour | Mentions | Z-score
-----|----------|--------
00:00|    45   |   0.2
01:00|    52   |   0.5
02:00|   180   |   3.5  🔴 SPIKE
03:00|   210   |   4.2  🔴 SPIKE
04:00|    89   |   1.1
...
```

### 3. Source Agreement Over Time
```
Agreement Score
  1.0 |●●●●●●●
  0.8 |        ●●●●●
  0.6 |              ●●
  0.4 |                ●●  ⚠️ Conflicting
  0.2 |
      +--------------------
      Day1      Day4    Day7
```

### 4. Theme Evolution
```
Theme         | 7d Avg | 24h Avg | Trend
--------------|--------|---------|-------
adoption      |  0.35  |  0.52   | ↗️ +49%
technology    |  0.28  |  0.31   | → +11%
regulation    | -0.12  | -0.38   | ↘️ -217%
security      |  0.05  | -0.45   | 🔴 SHOCK
```

---

## Implementation Roadmap

### Phase 1: Fix Data Integrity (Week 1)
- [ ] Fix hourly persistence (`quant-8ac`)
- [ ] Backfill hourly data (`quant-9xe`)
- [ ] Use DB for z-score/velocity (`quant-suy`)
- [ ] Test with 7-day historical data

### Phase 2: Enhanced Metrics (Week 2)
- [ ] Add 7-day baseline metrics (`quant-3y1`)
- [ ] Compute percentiles, momentum
- [ ] Add regime detection
- [ ] Update `/insights` response model

### Phase 3: Trading Integration (Week 3)
- [ ] Implement alert conditions (`quant-sn9`)
- [ ] Create entry/exit filters
- [ ] Add position sizing logic
- [ ] Build Telegram alerts for critical conditions

### Phase 4: Validation (Week 4)
- [ ] Backtest sentiment signals vs returns
- [ ] Measure signal effectiveness per symbol
- [ ] Optimize thresholds
- [ ] Document winning patterns

---

## Performance Considerations

### Database Queries
- **Hourly sentiment (7d)**: ~168 rows per symbol
- **Mention history (7d)**: ~168 rows per symbol
- **Query time**: <20ms with indexes

### Memory Usage
- Remove `post_history` in-memory dict (saves ~500MB)
- Keep only current hour in memory
- Rely on DB for all historical queries

### API Latency
- Current `/insights`: 1-2s (fetching posts dominates)
- After optimization: +50-100ms for 7-day metrics
- Negligible impact on user experience

---

## Testing Strategy

### Unit Tests
```python
def test_hourly_bucketing():
    """Verify hour-specific aggregation."""
    # Create posts across 3 hours
    # Verify each hour has correct counts
    
def test_7day_zscore():
    """Test z-score calculation with 7d history."""
    # Generate normal baseline + spike
    # Verify anomaly detection
    
def test_momentum_calculation():
    """Test 6h and 24h momentum."""
    # Generate improving trend
    # Verify positive momentum
```

### Integration Tests
```bash
# Test backfill
python3 -m pytest test_backfill.py -v

# Test insights with historical data
curl "http://localhost:8000/sentiment/BTCUSDT/insights?lookback_hours=168"

# Verify DB structure
sqlite3 sentiment.db "SELECT COUNT(*) FROM sentiment_hourly WHERE symbol='BTCUSDT';"
```

---

## Key Metrics to Track

### System Health
- Backfill success rate
- Hourly persistence latency
- DB size growth rate
- API response times

### Signal Quality
- Alert precision (true positives / total alerts)
- Signal-to-noise ratio (significant moves / total signals)
- Lead time (hours before price movement)
- Correlation with returns

### Trading Performance
- Win rate on sentiment entries
- Average return per signal type
- Drawdown during "panic" regime
- P&L by confidence level

---

## Future Enhancements

### Short Term (1-2 months)
- Cross-symbol correlation analysis
- Sector sentiment aggregation
- Whale wallet tracking integration
- Real-time WebSocket streaming

### Medium Term (3-6 months)
- Machine learning for theme clustering
- Sentiment-return predictive models
- Custom weighting per source/symbol
- Multi-timeframe analysis (1h, 4h, 1d)

### Long Term (6-12 months)
- Portfolio-level sentiment optimization
- Automated strategy parameter tuning
- Cross-asset sentiment arbitrage
- Alternative data integration (on-chain, social)

---

## Related Issues
- `quant-8ac`: Fix hourly sentiment persistence (P0)
- `quant-9xe`: Backfill hourly data (P1)
- `quant-suy`: Use 7-day DB history (P1)
- `quant-3y1`: Add baseline metrics (P2)
- `quant-sn9`: Add alert conditions (P2)

## Related Documentation
- [Insights Endpoint Documentation](./INSIGHTS_ENDPOINT.md)
- [Sentiment Implementation Summary](./SENTIMENT_IMPLEMENTATION.md)
- [New APIs Reference](./SENTIMENT_NEW_APIS.md)
