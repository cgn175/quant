"""
Unit tests for 7-day baseline metrics and alerts.
"""

import pytest
from datetime import datetime, timedelta, timezone
from insights import (
    InsightsGenerator, 
    BaselineMetrics,
    SentimentAlert,
    ThemeAnalysis,
    SourceDiversity,
    TrendAnalysis,
)


@pytest.fixture
def insights_gen():
    return InsightsGenerator()


@pytest.fixture
def historical_data_7d():
    """Generate 7 days of historical sentiment and mentions data."""
    now = datetime.now(timezone.utc)
    
    # Normal baseline with some variation
    historical_scores = [
        (now - timedelta(hours=i), 0.2 + (i % 10) * 0.02)
        for i in range(168)  # 7 days
    ]
    
    historical_mentions = [
        (now - timedelta(hours=i), 50 + (i % 8) * 5)
        for i in range(168)
    ]
    
    return historical_scores, historical_mentions


@pytest.fixture
def source_diversity_high():
    return SourceDiversity(
        total_sources=6,
        active_sources=["reddit", "newsapi", "coingecko"],
        source_types={"social": 2, "news": 3, "market_data": 1},
        source_agreement=0.8,
        dominant_source="newsapi",
        coverage_score=0.7,
    )


@pytest.fixture
def source_diversity_low():
    return SourceDiversity(
        total_sources=3,
        active_sources=["reddit"],
        source_types={"social": 1},
        source_agreement=0.25,
        dominant_source="reddit",
        coverage_score=0.3,
    )


def test_compute_baseline_metrics_normal(insights_gen, historical_data_7d, source_diversity_high):
    """Test baseline metrics with normal data."""
    historical_scores, historical_mentions = historical_data_7d
    
    metrics = insights_gen.compute_baseline_metrics(
        symbol="BTCUSDT",
        current_score=0.25,  # Around the mean
        current_mentions=55,  # Around the mean
        historical_scores=historical_scores,
        historical_mentions=historical_mentions,
        source_diversity=source_diversity_high,
    )
    
    assert isinstance(metrics, BaselineMetrics)
    assert abs(metrics.sentiment_zscore_7d) < 1.5  # Close to mean (relaxed threshold)
    assert abs(metrics.mentions_zscore_7d) < 1.5
    assert 20.0 <= metrics.sentiment_percentile_7d <= 80.0
    assert metrics.regime in ["normal", "quiet"]


def test_compute_baseline_metrics_anomaly(insights_gen, historical_data_7d, source_diversity_high):
    """Test baseline metrics with anomalous current values."""
    historical_scores, historical_mentions = historical_data_7d
    
    metrics = insights_gen.compute_baseline_metrics(
        symbol="BTCUSDT",
        current_score=0.8,  # Very high
        current_mentions=200,  # Very high
        historical_scores=historical_scores,
        historical_mentions=historical_mentions,
        source_diversity=source_diversity_high,
    )
    
    assert metrics.sentiment_zscore_7d > 2.0  # Anomaly
    assert metrics.mentions_zscore_7d > 2.0
    assert metrics.sentiment_percentile_7d > 90.0
    assert metrics.regime in ["news_driven"]


def test_compute_baseline_metrics_insufficient_data(insights_gen, source_diversity_high):
    """Test baseline metrics with insufficient historical data."""
    # Only 10 hours of data
    now = datetime.now(timezone.utc)
    historical_scores = [
        (now - timedelta(hours=i), 0.2)
        for i in range(10)
    ]
    historical_mentions = [
        (now - timedelta(hours=i), 50)
        for i in range(10)
    ]
    
    metrics = insights_gen.compute_baseline_metrics(
        symbol="BTCUSDT",
        current_score=0.25,
        current_mentions=55,
        historical_scores=historical_scores,
        historical_mentions=historical_mentions,
        source_diversity=source_diversity_high,
    )
    
    assert metrics.regime == "insufficient_data"
    assert metrics.sentiment_zscore_7d == 0.0


def test_momentum_calculation(insights_gen, source_diversity_high):
    """Test momentum calculations (6h and 24h)."""
    now = datetime.now(timezone.utc)
    
    # Create improving trend
    historical_scores = []
    for i in range(168):
        # Recent 24h is higher than older data
        if i < 24:
            score = 0.4  # Recent
        elif i < 48:
            score = 0.2  # Older
        else:
            score = 0.2
        historical_scores.append((now - timedelta(hours=i), score))
    
    historical_mentions = [
        (now - timedelta(hours=i), 50)
        for i in range(168)
    ]
    
    metrics = insights_gen.compute_baseline_metrics(
        symbol="BTCUSDT",
        current_score=0.4,
        current_mentions=50,
        historical_scores=historical_scores,
        historical_mentions=historical_mentions,
        source_diversity=source_diversity_high,
    )
    
    assert metrics.sentiment_momentum_24h > 0.15  # Positive momentum
    assert metrics.sentiment_momentum_6h >= 0.0


def test_attention_momentum(insights_gen, source_diversity_high):
    """Test attention momentum calculation."""
    now = datetime.now(timezone.utc)
    
    historical_scores = [
        (now - timedelta(hours=i), 0.2)
        for i in range(168)
    ]
    
    # Recent mentions are much higher
    historical_mentions = []
    for i in range(168):
        if i < 6:
            count = 150  # Recent spike
        elif i < 12:
            count = 50  # Older baseline
        else:
            count = 50
        historical_mentions.append((now - timedelta(hours=i), count))
    
    metrics = insights_gen.compute_baseline_metrics(
        symbol="BTCUSDT",
        current_score=0.2,
        current_mentions=150,
        historical_scores=historical_scores,
        historical_mentions=historical_mentions,
        source_diversity=source_diversity_high,
    )
    
    assert metrics.attention_momentum > 1.0  # Significant increase


def test_regime_detection_panic(insights_gen):
    """Test panic regime detection."""
    regime, confidence = insights_gen._detect_regime(
        mentions_zscore=2.5,  # High mentions
        source_agreement=0.35,  # Low agreement
        volatility=0.4,  # High volatility
    )
    
    assert regime == "panic"
    assert confidence > 0.8


def test_regime_detection_news_driven(insights_gen):
    """Test news-driven regime detection."""
    regime, confidence = insights_gen._detect_regime(
        mentions_zscore=2.0,  # High mentions
        source_agreement=0.7,  # High agreement
        volatility=0.15,
    )
    
    assert regime == "news_driven"
    assert confidence > 0.7


def test_regime_detection_quiet(insights_gen):
    """Test quiet regime detection."""
    regime, confidence = insights_gen._detect_regime(
        mentions_zscore=-0.6,  # Low mentions
        source_agreement=0.75,  # High agreement
        volatility=0.1,
    )
    
    assert regime == "quiet"
    assert confidence > 0.7


def test_generate_alerts_sentiment_breakout(insights_gen):
    """Test sentiment breakout alert generation."""
    baseline_metrics = BaselineMetrics(
        sentiment_zscore_7d=3.5,  # High
        mentions_zscore_7d=1.0,
        sentiment_percentile_7d=95.0,
        sentiment_momentum_6h=0.1,
        sentiment_momentum_24h=0.1,
        attention_momentum=0.0,
        regime="normal",
        regime_confidence=0.5,
    )
    
    themes = ThemeAnalysis(
        top_keywords=[],
        recurring_themes=[],
        sentiment_by_theme={},
    )
    
    trend = TrendAnalysis(
        trend_direction="improving",
        trend_strength=0.5,
        anomaly_detected=False,
        anomaly_description=None,
        confidence_interval=(0.2, 0.4),
        volatility=0.1,
    )
    
    source_diversity = SourceDiversity(
        total_sources=5,
        active_sources=["reddit", "newsapi"],
        source_types={"social": 1, "news": 4},
        source_agreement=0.7,
        dominant_source="newsapi",
        coverage_score=0.6,
    )
    
    alerts = insights_gen.generate_alerts(
        "BTCUSDT", baseline_metrics, themes, trend, source_diversity
    )
    
    assert len(alerts) > 0
    assert any(a.alert_type == "sentiment_breakout" for a in alerts)
    breakout_alert = next(a for a in alerts if a.alert_type == "sentiment_breakout")
    assert breakout_alert.severity == "high"


def test_generate_alerts_attention_spike(insights_gen):
    """Test attention spike alert generation."""
    baseline_metrics = BaselineMetrics(
        sentiment_zscore_7d=0.5,
        mentions_zscore_7d=4.5,  # Very high
        sentiment_percentile_7d=60.0,
        sentiment_momentum_6h=0.0,
        sentiment_momentum_24h=0.0,
        attention_momentum=2.0,
        regime="news_driven",
        regime_confidence=0.8,
    )
    
    themes = ThemeAnalysis(
        top_keywords=[],
        recurring_themes=[],
        sentiment_by_theme={},
    )
    
    trend = TrendAnalysis(
        trend_direction="stable",
        trend_strength=0.0,
        anomaly_detected=False,
        anomaly_description=None,
        confidence_interval=(0.2, 0.3),
        volatility=0.2,
    )
    
    source_diversity = SourceDiversity(
        total_sources=6,
        active_sources=["reddit", "newsapi", "cryptopanic"],
        source_types={"social": 2, "news": 4},
        source_agreement=0.6,
        dominant_source="newsapi",
        coverage_score=0.7,
    )
    
    alerts = insights_gen.generate_alerts(
        "BTCUSDT", baseline_metrics, themes, trend, source_diversity
    )
    
    assert any(a.alert_type == "attention_spike" for a in alerts)
    spike_alert = next(a for a in alerts if a.alert_type == "attention_spike")
    assert spike_alert.severity == "critical"


def test_generate_alerts_security_shock(insights_gen):
    """Test security shock alert generation."""
    baseline_metrics = BaselineMetrics(
        sentiment_zscore_7d=0.0,
        mentions_zscore_7d=2.5,  # High attention
        sentiment_percentile_7d=50.0,
        sentiment_momentum_6h=0.0,
        sentiment_momentum_24h=0.0,
        attention_momentum=1.0,
        regime="normal",
        regime_confidence=0.5,
    )
    
    themes = ThemeAnalysis(
        top_keywords=[("hack", 25), ("breach", 15)],
        recurring_themes=["security"],
        sentiment_by_theme={"security": -0.6},  # Very negative
    )
    
    trend = TrendAnalysis(
        trend_direction="deteriorating",
        trend_strength=0.6,
        anomaly_detected=True,
        anomaly_description="Negative sentiment spike",
        confidence_interval=(-0.3, 0.0),
        volatility=0.3,
    )
    
    source_diversity = SourceDiversity(
        total_sources=5,
        active_sources=["reddit", "newsapi", "cryptopanic"],
        source_types={"social": 2, "news": 3},
        source_agreement=0.8,
        dominant_source="newsapi",
        coverage_score=0.6,
    )
    
    alerts = insights_gen.generate_alerts(
        "BTCUSDT", baseline_metrics, themes, trend, source_diversity
    )
    
    assert any(a.alert_type == "security_shock" for a in alerts)
    security_alert = next(a for a in alerts if a.alert_type == "security_shock")
    assert security_alert.severity == "critical"


def test_generate_alerts_regime_panic(insights_gen):
    """Test panic regime alert generation."""
    baseline_metrics = BaselineMetrics(
        sentiment_zscore_7d=-0.5,
        mentions_zscore_7d=3.0,
        sentiment_percentile_7d=30.0,
        sentiment_momentum_6h=-0.2,
        sentiment_momentum_24h=-0.3,
        attention_momentum=2.0,
        regime="panic",
        regime_confidence=0.9,
    )
    
    themes = ThemeAnalysis(
        top_keywords=[],
        recurring_themes=[],
        sentiment_by_theme={},
    )
    
    trend = TrendAnalysis(
        trend_direction="deteriorating",
        trend_strength=0.7,
        anomaly_detected=True,
        anomaly_description="High volatility",
        confidence_interval=(-0.4, 0.0),
        volatility=0.4,
    )
    
    source_diversity = SourceDiversity(
        total_sources=5,
        active_sources=["reddit", "twitter", "newsapi"],
        source_types={"social": 2, "news": 3},
        source_agreement=0.25,  # Low
        dominant_source="reddit",
        coverage_score=0.5,
    )
    
    alerts = insights_gen.generate_alerts(
        "BTCUSDT", baseline_metrics, themes, trend, source_diversity
    )
    
    assert any(a.alert_type == "regime_panic" for a in alerts)
    panic_alert = next(a for a in alerts if a.alert_type == "regime_panic")
    assert panic_alert.severity == "critical"


def test_generate_alerts_momentum_surge(insights_gen):
    """Test momentum surge alert generation."""
    baseline_metrics = BaselineMetrics(
        sentiment_zscore_7d=1.5,
        mentions_zscore_7d=1.0,
        sentiment_percentile_7d=80.0,
        sentiment_momentum_6h=0.25,  # Strong
        sentiment_momentum_24h=0.20,  # Strong
        attention_momentum=0.5,
        regime="news_driven",
        regime_confidence=0.8,
    )
    
    themes = ThemeAnalysis(
        top_keywords=[("adoption", 20), ("partnership", 15)],
        recurring_themes=["adoption", "innovation"],
        sentiment_by_theme={"adoption": 0.6, "innovation": 0.5},
    )
    
    trend = TrendAnalysis(
        trend_direction="improving",
        trend_strength=0.8,
        anomaly_detected=False,
        anomaly_description=None,
        confidence_interval=(0.3, 0.5),
        volatility=0.15,
    )
    
    source_diversity = SourceDiversity(
        total_sources=7,
        active_sources=["reddit", "newsapi", "coingecko", "cryptopanic"],
        source_types={"social": 2, "news": 4, "market_data": 1},
        source_agreement=0.75,
        dominant_source="newsapi",
        coverage_score=0.8,
    )
    
    alerts = insights_gen.generate_alerts(
        "BTCUSDT", baseline_metrics, themes, trend, source_diversity
    )
    
    assert any(a.alert_type == "momentum_surge" for a in alerts)
    momentum_alert = next(a for a in alerts if a.alert_type == "momentum_surge")
    assert momentum_alert.severity == "medium"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
