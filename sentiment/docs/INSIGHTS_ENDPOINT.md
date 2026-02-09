# Sentiment Insights Endpoint

## Overview

The `/sentiment/{symbol}/insights` endpoint provides **actionable intelligence** from aggregated sentiment data across multiple news sources. Unlike simple sentiment scores, this endpoint delivers:

- **Theme Extraction**: Key topics and keywords driving the sentiment
- **Source Diversity Analysis**: Coverage metrics and source agreement
- **Trend Detection**: Direction, strength, and anomaly alerts
- **Actionable Recommendations**: Clear trading signals with confidence levels

## Endpoint

```
GET /sentiment/{symbol}/insights?lookback_hours=24
```

### Parameters

- `symbol` (path, required): Trading symbol (e.g., `BTCUSDT`)
- `lookback_hours` (query, optional): Hours of historical data to analyze (default: 24, max: 168)

### Response Model

```json
{
  "symbol": "BTCUSDT",
  "timestamp": "2024-02-09T16:30:00Z",
  "current_sentiment": 0.35,
  
  "top_keywords": [
    ["adoption", 15],
    ["upgrade", 12],
    ["institutional", 10]
  ],
  "recurring_themes": ["adoption", "technology", "regulation"],
  "sentiment_by_theme": {
    "adoption": 0.45,
    "technology": 0.38,
    "regulation": -0.15
  },
  
  "total_sources": 6,
  "active_sources": ["reddit", "newsapi", "coingecko", "cryptopanic", "marketaux", "finnhub"],
  "source_types": {
    "social": 1,
    "news": 4,
    "market_data": 1
  },
  "source_agreement": 0.78,
  "dominant_source": "newsapi",
  "coverage_score": 0.67,
  
  "trend_direction": "improving",
  "trend_strength": 0.65,
  "anomaly_detected": false,
  "anomaly_description": null,
  "confidence_interval": [0.28, 0.42],
  "volatility": 0.12,
  
  "signal": "bullish",
  "confidence": 0.72,
  "reasoning": [
    "Strong positive sentiment (0.35)",
    "Sentiment improving (strength: 0.65)",
    "High source diversity (6 sources)",
    "High source agreement (0.78)"
  ],
  "risk_level": "medium",
  "suggested_action": "buy"
}
```

## Response Fields

### Theme Analysis

| Field | Type | Description |
|-------|------|-------------|
| `top_keywords` | `List[Tuple[str, int]]` | Top 10 keywords by frequency |
| `recurring_themes` | `List[str]` | Detected themes (regulation, technology, adoption, market_movement, security, innovation) |
| `sentiment_by_theme` | `Dict[str, float]` | Average sentiment score per theme (-1.0 to 1.0) |

### Source Diversity

| Field | Type | Description |
|-------|------|-------------|
| `total_sources` | `int` | Number of unique sources |
| `active_sources` | `List[str]` | List of source names |
| `source_types` | `Dict[str, int]` | Count per type (social/news/market_data) |
| `source_agreement` | `float` | How aligned sources are (0-1, higher = more agreement) |
| `dominant_source` | `str\|null` | Source with most mentions |
| `coverage_score` | `float` | Diversity of coverage (0-1) |

### Trend Analysis

| Field | Type | Description |
|-------|------|-------------|
| `trend_direction` | `str` | "improving", "deteriorating", "stable", or "insufficient_data" |
| `trend_strength` | `float` | Strength of trend (0-1) |
| `anomaly_detected` | `bool` | Whether an unusual pattern was detected |
| `anomaly_description` | `str\|null` | Description of the anomaly |
| `confidence_interval` | `Tuple[float, float]` | 95% confidence interval for sentiment |
| `volatility` | `float` | Standard deviation of recent sentiment |

### Recommendation

| Field | Type | Description |
|-------|------|-------------|
| `signal` | `str` | "strong_bullish", "bullish", "neutral", "bearish", "strong_bearish", "mixed" |
| `confidence` | `float` | Confidence in recommendation (0-1) |
| `reasoning` | `List[str]` | Human-readable explanations |
| `risk_level` | `str` | "low", "medium", "high" |
| `suggested_action` | `str` | "buy", "hold", "sell", "wait" |

## Usage Examples

### Basic Query

```bash
curl "http://localhost:8000/sentiment/BTCUSDT/insights"
```

### Extended Lookback

```bash
# Analyze 7 days of data
curl "http://localhost:8000/sentiment/BTCUSDT/insights?lookback_hours=168"
```

### Python Client

```python
import requests

response = requests.get(
    "http://localhost:8000/sentiment/BTCUSDT/insights",
    params={"lookback_hours": 48}
)

insights = response.json()

print(f"Signal: {insights['signal']}")
print(f"Confidence: {insights['confidence']:.2%}")
print(f"Action: {insights['suggested_action']}")
print(f"\nReasons:")
for reason in insights['reasoning']:
    print(f"  - {reason}")
```

### Go Client Integration

```go
type InsightReport struct {
    Symbol           string            `json:"symbol"`
    Timestamp        time.Time         `json:"timestamp"`
    CurrentSentiment float64           `json:"current_sentiment"`
    
    // Theme analysis
    TopKeywords       [][]interface{}  `json:"top_keywords"`
    RecurringThemes   []string         `json:"recurring_themes"`
    SentimentByTheme  map[string]float64 `json:"sentiment_by_theme"`
    
    // Source diversity
    TotalSources     int              `json:"total_sources"`
    ActiveSources    []string         `json:"active_sources"`
    SourceTypes      map[string]int   `json:"source_types"`
    SourceAgreement  float64          `json:"source_agreement"`
    DominantSource   *string          `json:"dominant_source"`
    CoverageScore    float64          `json:"coverage_score"`
    
    // Trend analysis
    TrendDirection      string   `json:"trend_direction"`
    TrendStrength       float64  `json:"trend_strength"`
    AnomalyDetected     bool     `json:"anomaly_detected"`
    AnomalyDescription  *string  `json:"anomaly_description"`
    ConfidenceInterval  [2]float64 `json:"confidence_interval"`
    Volatility          float64  `json:"volatility"`
    
    // Recommendation
    Signal          string   `json:"signal"`
    Confidence      float64  `json:"confidence"`
    Reasoning       []string `json:"reasoning"`
    RiskLevel       string   `json:"risk_level"`
    SuggestedAction string   `json:"suggested_action"`
}

func FetchInsights(symbol string, lookbackHours int) (*InsightReport, error) {
    url := fmt.Sprintf("%s/sentiment/%s/insights?lookback_hours=%d", 
        baseURL, symbol, lookbackHours)
    
    resp, err := http.Get(url)
    if err != nil {
        return nil, err
    }
    defer resp.Body.Close()
    
    var report InsightReport
    if err := json.NewDecoder(resp.Body).Decode(&report); err != nil {
        return nil, err
    }
    
    return &report, nil
}
```

## Interpretation Guide

### Signals

- **strong_bullish**: High confidence positive outlook → Consider buying
- **bullish**: Moderate positive outlook → Consider buying or holding
- **neutral**: No clear direction → Hold current position
- **bearish**: Moderate negative outlook → Consider selling or holding
- **strong_bearish**: High confidence negative outlook → Consider selling
- **mixed**: Conflicting signals → Wait for clearer signals

### Confidence Levels

- **> 0.7**: High confidence - multiple confirming factors
- **0.5 - 0.7**: Moderate confidence - some supporting evidence
- **< 0.5**: Low confidence - weak or conflicting signals

### Risk Levels

- **low**: Low volatility, high source agreement, clear trend
- **medium**: Moderate volatility or mixed signals
- **high**: High volatility, low source agreement, or anomalies detected

### Anomalies

When `anomaly_detected` is `true`:
- Sentiment is >2 standard deviations from historical mean
- Indicates unusual market conditions
- Exercise caution regardless of signal direction
- May precede significant price movements

### Source Agreement

- **> 0.7**: High consensus across sources (reliable signal)
- **0.4 - 0.7**: Moderate agreement (validate with other data)
- **< 0.4**: Low agreement (conflicting narratives, high uncertainty)

## Algorithm Details

### Theme Extraction

1. Tokenize all post text
2. Filter stopwords and crypto-specific noise
3. Count keyword frequencies
4. Match regex patterns for high-level themes:
   - `regulation`: SEC, government, ban, legal
   - `technology`: upgrade, fork, protocol, scaling
   - `adoption`: institutional, partner, mainstream
   - `market_movement`: pump, dump, rally, crash
   - `security`: hack, breach, vulnerability
   - `innovation`: breakthrough, development, launch

### Source Diversity

- **Coverage Score**: `active_sources / total_available_sources`
- **Agreement**: Inverse variance of per-source average sentiments
- **Source Types**: Classify as social/news/market_data

### Trend Detection

1. Compare recent 24h average vs. previous 24h
2. Calculate delta to determine direction
3. Normalize delta to 0-1 range for strength
4. Compute volatility as standard deviation
5. Detect anomalies via z-score (>2 std devs)

### Recommendation Generation

Combines multiple factors:
- Current sentiment score
- Trend direction and strength
- Source diversity and agreement
- Detected themes and anomalies
- Volatility

Each factor adds to confidence or risk, final signal determined by net score.

## Performance

| Operation | Latency | Notes |
|-----------|---------|-------|
| Fetch insights (24h) | 1-2s | Depends on source availability |
| Fetch insights (168h) | 2-3s | More data to process |
| Theme extraction | 50-100ms | Per 100 posts |
| Trend analysis | 10-20ms | With 168 hourly data points |

## Error Handling

### 404 - No Data Available

```json
{
  "detail": "No sentiment data available for BTCUSDT in the last 24 hours"
}
```

**Causes**:
- Symbol not tracked by any source
- All sources failed to fetch data
- Lookback window too narrow

**Solutions**:
- Try a longer `lookback_hours` window
- Check if symbol is spelled correctly
- Verify sentiment service has API keys configured

### 500 - Internal Error

```json
{
  "detail": "Error message"
}
```

**Causes**:
- Database connection issues
- Model inference failure
- Insufficient historical data

**Solutions**:
- Check sentiment service logs
- Ensure database is accessible
- Verify model is loaded

## Best Practices

1. **Use appropriate lookback windows**:
   - 24h for recent developments
   - 72h for short-term trends
   - 168h (7 days) for comprehensive analysis

2. **Don't trade on insights alone**:
   - Combine with technical analysis
   - Consider market conditions
   - Validate with price action

3. **Pay attention to confidence and risk**:
   - Low confidence + high risk = wait
   - High confidence + low risk = act
   - Anomalies = proceed with caution

4. **Monitor source diversity**:
   - Low coverage (<3 sources) = unreliable
   - High agreement + high coverage = strong signal
   - Low agreement = conflicting narratives

5. **Check recurring themes**:
   - Negative themes (security, regulation) = risk
   - Positive themes (adoption, innovation) = opportunity
   - Mixed themes = uncertainty

## Testing

```bash
cd sentiment
python3 -m pytest test_insights.py -v
```

Tests cover:
- Theme extraction
- Source diversity analysis
- Trend detection (stable, improving, deteriorating)
- Anomaly detection
- Recommendation generation (bullish, bearish, mixed)
- Full report generation

## Future Enhancements

- [ ] Machine learning-based theme clustering
- [ ] Sentiment correlation with price movements
- [ ] Multi-symbol correlation analysis
- [ ] Custom weighting per source/theme
- [ ] Historical insight performance tracking
- [ ] WebSocket streaming for real-time insights
