# How Sentiment Negotiates Trends

## Overview

The sentiment system uses a multi-layered approach to detect and interpret sentiment trends, combining statistical analysis, anomaly detection, and contextual reasoning to generate actionable recommendations.

---

## 1. Trend Detection Algorithm

### Core Method: `detect_trends_and_anomalies()`

Located in `sentiment/insights.py`, this method analyzes historical sentiment scores to determine trend direction and strength.

### Input Data
```python
def detect_trends_and_anomalies(
    symbol: str,
    current_score: float,
    historical_scores: List[Tuple[datetime, float]],  # Time-series data
    current_mentions: int,
    historical_mentions: List[Tuple[datetime, int]],
)
```

### Algorithm Steps

#### Step 1: Data Preparation
```python
# Sort by timestamp (oldest to newest)
sorted_scores = sorted(historical_scores, key=lambda x: x[0])

# Split into time windows
recent_scores = [score for _, score in sorted_scores[-24:]]    # Last 24 hours
older_scores = [score for _, score in sorted_scores[-48:-24]]  # Previous 24 hours
```

#### Step 2: Calculate Averages
```python
recent_avg = statistics.mean(recent_scores)
older_avg = statistics.mean(older_scores)
delta = recent_avg - older_avg
```

#### Step 3: Determine Trend Direction
```python
if abs(delta) < 0.05:
    trend_direction = "stable"
    trend_strength = 0.0
elif delta > 0:
    trend_direction = "improving"
    trend_strength = min(1.0, delta / 0.5)  # Normalize to 0-1
else:
    trend_direction = "deteriorating"
    trend_strength = min(1.0, abs(delta) / 0.5)
```

**Thresholds:**
- **Stable**: Delta < 0.05 (less than 5% change)
- **Improving**: Delta > 0 (positive change)
- **Deteriorating**: Delta < 0 (negative change)

**Strength Calculation:**
- Normalized by dividing by 0.5
- Capped at 1.0 maximum
- Example: delta of 0.25 = strength of 0.5 (50%)

---

## 2. Anomaly Detection

### Z-Score Based Detection

```python
# Calculate z-score for current sentiment
mean = statistics.mean(all_historical_scores)
stdev = statistics.stdev(all_historical_scores)

z_score = (current_score - mean) / stdev
anomaly_detected = abs(z_score) > 2.0  # 2 standard deviations
```

**Interpretation:**
- **|z-score| > 2.0**: Anomaly detected (unusual sentiment)
- **z-score > 0**: Unusually positive
- **z-score < 0**: Unusually negative

### Example
- If historical scores average 0.1 with stdev 0.15
- Current score of 0.5 would give z-score = (0.5 - 0.1) / 0.15 = 2.67
- This triggers an anomaly alert: "Unusually positive sentiment"

---

## 3. Volatility Calculation

```python
volatility = statistics.stdev(recent_scores)
```

**Purpose:**
- Measures sentiment stability
- High volatility = unpredictable, conflicting signals
- Low volatility = consistent, stable sentiment

---

## 4. Confidence Intervals (95%)

```python
mean = statistics.mean(recent_scores)
stdev = statistics.stdev(recent_scores)
margin = 1.96 * stdev / (len(recent_scores) ** 0.5)  # Standard error
confidence_interval = (mean - margin, mean + margin)
```

**Interpretation:**
- 95% confidence that true sentiment lies within this range
- Narrower interval = more confident in the measurement
- Wider interval = more uncertainty

---

## 5. Trend Integration into Recommendations

### Method: `generate_recommendation()`

The system integrates trend analysis with current sentiment to generate signals.

### Base Signal from Current Sentiment

```python
if current_score > 0.3:
    signal_base = "bullish"
    reasoning.append("Strong positive sentiment")
elif current_score > 0.1:
    signal_base = "bullish"
    reasoning.append("Moderate positive sentiment")
elif current_score < -0.3:
    signal_base = "bearish"
    reasoning.append("Strong negative sentiment")
elif current_score < -0.1:
    signal_base = "bearish"
    reasoning.append("Moderate negative sentiment")
else:
    signal_base = "neutral"
```

### Trend Adjustment Logic

```python
if trend.trend_direction == "improving":
    reasoning.append(f"Sentiment improving (strength: {trend.trend_strength:.2f})")
    confidence_factors.append(trend.trend_strength * 0.3)
    
    # Conflict resolution
    if signal_base == "bearish":
        signal_base = "neutral"  # Override bearish if trend is improving
        reasoning.append("⚠️ Mixed signals: negative sentiment but improving trend")

elif trend.trend_direction == "deteriorating":
    reasoning.append(f"Sentiment deteriorating (strength: {trend.trend_strength:.2f})")
    confidence_factors.append(trend.trend_strength * 0.3)
    
    # Conflict resolution
    if signal_base == "bullish":
        signal_base = "neutral"  # Override bullish if trend is deteriorating
        reasoning.append("⚠️ Mixed signals: positive sentiment but deteriorating trend")
```

---

## 6. Conflict Resolution Strategy

The system handles contradicting signals intelligently:

| Current Sentiment | Trend Direction | Final Signal | Reasoning |
|------------------|-----------------|--------------|-----------|
| Bearish (-0.4) | Improving (+0.3) | **Neutral** | "Negative sentiment but improving trend" |
| Bullish (+0.4) | Deteriorating (-0.3) | **Neutral** | "Positive sentiment but deteriorating trend" |
| Bullish (+0.4) | Improving (+0.3) | **Strong Bullish** | Both align positively |
| Bearish (-0.4) | Deteriorating (-0.3) | **Strong Bearish** | Both align negatively |
| Neutral (0.1) | Improving (+0.2) | **Bullish** | Trend drives the signal |

---

## 7. Confidence Calculation

```python
# Aggregate confidence factors
confidence = sum(confidence_factors)
confidence = min(1.0, confidence)  # Cap at 100%
confidence = max(0.1, confidence)  # Floor at 10%
```

**Confidence Factors (weighted):**
- Strong sentiment: +0.3
- Moderate sentiment: +0.2
- Trend strength: +0.3 × trend_strength
- High source diversity: +0.2
- Low volatility: +0.1
- Anomaly detected: -0.2

---

## 8. Final Signal Generation

```python
# Upgrade/downgrade signals based on confidence
if signal_base == "bullish" and confidence > 0.7:
    final_signal = "strong_bullish"
elif signal_base == "bearish" and confidence > 0.7:
    final_signal = "strong_bearish"
elif confidence < 0.3:
    final_signal = "mixed"  # Low confidence means unclear
else:
    final_signal = signal_base
```

---

## 9. Example Scenarios

### Scenario 1: Strong Uptrend

**Input:**
- Current score: 0.45
- Historical avg (24h ago): 0.15
- Delta: +0.30
- Volatility: 0.08

**Output:**
```json
{
  "trend_direction": "improving",
  "trend_strength": 0.6,
  "signal": "strong_bullish",
  "confidence": 0.8,
  "reasoning": [
    "Strong positive sentiment (0.45)",
    "Sentiment improving (strength: 0.60)",
    "High source diversity (7 sources)",
    "Low volatility suggests stability"
  ],
  "suggested_action": "buy"
}
```

### Scenario 2: Mixed Signals

**Input:**
- Current score: -0.25 (bearish)
- Trend: improving (+0.35 strength)
- Volatility: 0.15 (high)

**Output:**
```json
{
  "trend_direction": "improving",
  "trend_strength": 0.7,
  "signal": "neutral",
  "confidence": 0.4,
  "reasoning": [
    "Moderate negative sentiment (-0.25)",
    "Sentiment improving (strength: 0.70)",
    "⚠️ Mixed signals: negative sentiment but improving trend",
    "High volatility (0.15) indicates uncertainty"
  ],
  "suggested_action": "wait",
  "risk_level": "medium"
}
```

### Scenario 3: Strong Downtrend

**Input:**
- Current score: -0.55
- Historical avg: -0.20
- Delta: -0.35
- Anomaly: z-score = -2.8

**Output:**
```json
{
  "trend_direction": "deteriorating",
  "trend_strength": 0.7,
  "signal": "strong_bearish",
  "confidence": 0.85,
  "anomaly_detected": true,
  "anomaly_description": "Unusually negative sentiment (z-score: -2.80)",
  "reasoning": [
    "Strong negative sentiment (-0.55)",
    "Sentiment deteriorating (strength: 0.70)",
    "Anomaly detected: extreme negativity",
    "⚠️ Panic regime detected"
  ],
  "suggested_action": "sell",
  "risk_level": "high"
}
```

---

## 10. Key Design Principles

1. **Layered Analysis**: Combines current state, historical trends, and anomaly detection
2. **Conflict Resolution**: Explicitly handles contradicting signals
3. **Confidence Transparency**: Shows why confidence is high or low
4. **Context-Aware**: Considers source diversity, volatility, and market regime
5. **Human-Readable**: Provides reasoning in plain English

---

## 11. Data Flow Diagram

```
Historical Scores (48h)
         ↓
    [Sort & Split]
         ↓
┌────────────────────┐
│  Recent (24h)      │
│  Older (24-48h)    │
└────────────────────┘
         ↓
   [Calculate Δ]
         ↓
┌────────────────────┐
│  Trend Direction   │
│  Trend Strength    │
│  Volatility        │
└────────────────────┘
         ↓
   [Z-Score Test]
         ↓
┌────────────────────┐
│  Anomaly Detection │
└────────────────────┘
         ↓
[Combine with Current Sentiment]
         ↓
┌────────────────────┐
│  Generate Signal   │
│  + Reasoning       │
│  + Confidence      │
│  + Action          │
└────────────────────┘
         ↓
   [Return to User]
```

---

## 12. Code Locations

- **Trend Detection**: `sentiment/insights.py:detect_trends_and_anomalies()`
- **Recommendation**: `sentiment/insights.py:generate_recommendation()`
- **Integration**: `sentiment/insights.py:generate_insights()`
- **API Endpoint**: `sentiment/main.py:/insights/{symbol}`
- **Telegram Display**: `internal/alerts/telegram.go:handleMarketsNewsCommand()`

---

## Summary

The sentiment system negotiates trends by:
1. **Comparing** recent vs older sentiment averages
2. **Detecting** anomalies using z-scores
3. **Measuring** volatility for uncertainty
4. **Integrating** trends with current sentiment
5. **Resolving** conflicts between signals
6. **Generating** confidence-weighted recommendations
7. **Explaining** the reasoning in human terms

This approach ensures users understand not just *what* the sentiment is, but *why* the recommendation makes sense given the trend context.
