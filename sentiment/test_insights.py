"""
Unit tests for sentiment insights module.
"""

import pytest
from datetime import datetime, timedelta, timezone
from insights import InsightsGenerator, ThemeAnalysis, SourceDiversity, TrendAnalysis, Recommendation
from fetchers.base import Post


@pytest.fixture
def insights_gen():
    return InsightsGenerator()


@pytest.fixture
def sample_posts():
    """Create sample posts for testing."""
    now = datetime.now(timezone.utc)
    posts = [
        Post(
            text="Bitcoin ETF approved! Huge adoption milestone for crypto regulation",
            source="newsapi",
            symbol="BTCUSDT",
            timestamp=now - timedelta(hours=1),
            score=100
        ),
        Post(
            text="Major security breach at exchange - users warned about potential hack",
            source="reddit",
            symbol="BTCUSDT",
            timestamp=now - timedelta(hours=2),
            score=50
        ),
        Post(
            text="New protocol upgrade launching next week with improved scaling",
            source="cryptopanic",
            symbol="BTCUSDT",
            timestamp=now - timedelta(hours=3),
            score=75
        ),
        Post(
            text="Institutional adoption growing as major bank partners with crypto firm",
            source="marketaux",
            symbol="BTCUSDT",
            timestamp=now - timedelta(hours=4),
            score=120
        ),
    ]
    
    sentiments = [
        {"positive": 0.8, "negative": 0.1, "neutral": 0.1},
        {"positive": 0.1, "negative": 0.8, "neutral": 0.1},
        {"positive": 0.7, "negative": 0.2, "neutral": 0.1},
        {"positive": 0.75, "negative": 0.15, "neutral": 0.1},
    ]
    
    return [(post, sent["positive"] - sent["negative"]) for post, sent in zip(posts, sentiments)], sentiments


def test_extract_themes(insights_gen, sample_posts):
    """Test theme extraction from posts."""
    posts_with_scores, sentiments = sample_posts
    
    themes = insights_gen.extract_themes(posts_with_scores, sentiments)
    
    assert isinstance(themes, ThemeAnalysis)
    assert len(themes.top_keywords) > 0
    assert len(themes.recurring_themes) > 0
    
    # Check that known themes are detected
    detected_theme_set = set(themes.recurring_themes)
    expected_themes = {"regulation", "adoption", "security", "technology"}
    assert len(detected_theme_set & expected_themes) >= 2  # At least 2 themes detected
    
    # Check sentiment by theme
    assert isinstance(themes.sentiment_by_theme, dict)
    if "security" in themes.sentiment_by_theme:
        # Security theme should be negative
        assert themes.sentiment_by_theme["security"] < 0


def test_analyze_source_diversity(insights_gen, sample_posts):
    """Test source diversity analysis."""
    posts_with_scores, sentiments = sample_posts
    
    diversity = insights_gen.analyze_source_diversity(posts_with_scores, sentiments)
    
    assert isinstance(diversity, SourceDiversity)
    assert diversity.total_sources == 4
    assert len(diversity.active_sources) == 4
    assert "reddit" in diversity.active_sources
    assert "newsapi" in diversity.active_sources
    
    # Check source types
    assert diversity.source_types.get("social", 0) >= 1
    assert diversity.source_types.get("news", 0) >= 1
    
    # Agreement should be between 0 and 1
    assert 0.0 <= diversity.source_agreement <= 1.0
    
    # Coverage score should be reasonable
    assert 0.0 <= diversity.coverage_score <= 1.0
    assert diversity.coverage_score > 0.2  # Should have decent coverage with 4 sources


def test_detect_trends_stable(insights_gen):
    """Test trend detection with stable sentiment."""
    symbol = "BTCUSDT"
    current_score = 0.2
    
    # Generate stable historical data
    now = datetime.now(timezone.utc)
    historical_scores = [
        (now - timedelta(hours=i), 0.2 + (i % 3 - 1) * 0.01)  # Small fluctuations around 0.2
        for i in range(48)
    ]
    historical_mentions = [
        (now - timedelta(hours=i), 100 + (i % 5) * 5)
        for i in range(48)
    ]
    
    trend = insights_gen.detect_trends_and_anomalies(
        symbol, current_score, historical_scores, 100, historical_mentions
    )
    
    assert isinstance(trend, TrendAnalysis)
    assert trend.trend_direction == "stable"
    assert trend.trend_strength < 0.3  # Low strength for stable trend
    assert not trend.anomaly_detected
    assert trend.volatility < 0.1  # Low volatility


def test_detect_trends_improving(insights_gen):
    """Test trend detection with improving sentiment."""
    symbol = "BTCUSDT"
    current_score = 0.5
    
    # Generate improving trend
    now = datetime.now(timezone.utc)
    historical_scores = [
        (now - timedelta(hours=i), 0.1 + (48 - i) * 0.008)  # Gradually improving
        for i in range(48)
    ]
    historical_mentions = [
        (now - timedelta(hours=i), 100)
        for i in range(48)
    ]
    
    trend = insights_gen.detect_trends_and_anomalies(
        symbol, current_score, historical_scores, 100, historical_mentions
    )
    
    assert trend.trend_direction == "improving"
    assert trend.trend_strength > 0.3


def test_detect_anomaly(insights_gen):
    """Test anomaly detection."""
    symbol = "BTCUSDT"
    current_score = 0.8  # Very high score
    
    # Generate normal historical data with slight variation
    now = datetime.now(timezone.utc)
    historical_scores = [
        (now - timedelta(hours=i), 0.2 + (i % 3) * 0.01)  # Stable around 0.2 with small variation
        for i in range(48)
    ]
    historical_mentions = [
        (now - timedelta(hours=i), 100)
        for i in range(48)
    ]
    
    trend = insights_gen.detect_trends_and_anomalies(
        symbol, current_score, historical_scores, 100, historical_mentions
    )
    
    assert trend.anomaly_detected
    assert trend.anomaly_description is not None
    assert "unusually positive" in trend.anomaly_description.lower()


def test_generate_recommendation_bullish(insights_gen):
    """Test recommendation generation for bullish scenario."""
    current_score = 0.4
    
    trend = TrendAnalysis(
        trend_direction="improving",
        trend_strength=0.7,
        anomaly_detected=False,
        anomaly_description=None,
        confidence_interval=(0.3, 0.5),
        volatility=0.1,
    )
    
    source_diversity = SourceDiversity(
        total_sources=6,
        active_sources=["reddit", "newsapi", "coingecko"],
        source_types={"social": 2, "news": 3, "market_data": 1},
        source_agreement=0.8,
        dominant_source="newsapi",
        coverage_score=0.7,
    )
    
    themes = ThemeAnalysis(
        top_keywords=[("adoption", 10), ("upgrade", 8)],
        recurring_themes=["adoption", "technology"],
        sentiment_by_theme={"adoption": 0.5, "technology": 0.4},
    )
    
    rec = insights_gen.generate_recommendation(
        current_score, trend, source_diversity, themes
    )
    
    assert isinstance(rec, Recommendation)
    assert rec.signal in ["bullish", "strong_bullish"]
    assert rec.confidence > 0.5
    assert rec.suggested_action in ["buy", "hold"]
    assert rec.risk_level in ["low", "medium"]
    assert len(rec.reasoning) > 0


def test_generate_recommendation_bearish(insights_gen):
    """Test recommendation generation for bearish scenario."""
    current_score = -0.4
    
    trend = TrendAnalysis(
        trend_direction="deteriorating",
        trend_strength=0.7,
        anomaly_detected=False,
        anomaly_description=None,
        confidence_interval=(-0.5, -0.3),
        volatility=0.15,
    )
    
    source_diversity = SourceDiversity(
        total_sources=5,
        active_sources=["reddit", "newsapi", "cryptopanic"],
        source_types={"social": 2, "news": 3},
        source_agreement=0.75,
        dominant_source="reddit",
        coverage_score=0.6,
    )
    
    themes = ThemeAnalysis(
        top_keywords=[("hack", 15), ("breach", 10)],
        recurring_themes=["security", "regulation"],
        sentiment_by_theme={"security": -0.6, "regulation": -0.3},
    )
    
    rec = insights_gen.generate_recommendation(
        current_score, trend, source_diversity, themes
    )
    
    assert rec.signal in ["bearish", "strong_bearish"]
    assert rec.confidence > 0.4
    assert rec.suggested_action in ["sell", "hold"]
    assert len(rec.reasoning) > 0


def test_generate_recommendation_mixed(insights_gen):
    """Test recommendation generation for mixed signals."""
    current_score = 0.3  # Positive
    
    trend = TrendAnalysis(
        trend_direction="deteriorating",  # Negative trend
        trend_strength=0.6,
        anomaly_detected=False,
        anomaly_description=None,
        confidence_interval=(0.2, 0.4),
        volatility=0.25,  # High volatility
    )
    
    source_diversity = SourceDiversity(
        total_sources=3,  # Low source count
        active_sources=["reddit", "newsapi"],
        source_types={"social": 1, "news": 2},
        source_agreement=0.3,  # Low agreement
        dominant_source="reddit",
        coverage_score=0.3,
    )
    
    themes = ThemeAnalysis(
        top_keywords=[("mixed", 10)],
        recurring_themes=[],
        sentiment_by_theme={},
    )
    
    rec = insights_gen.generate_recommendation(
        current_score, trend, source_diversity, themes
    )
    
    # Should detect conflicting signals
    assert rec.signal in ["mixed", "neutral"]
    assert rec.suggested_action in ["wait", "hold"]
    assert rec.risk_level == "high"


def test_generate_full_report(insights_gen, sample_posts):
    """Test full report generation."""
    posts_with_scores, sentiments = sample_posts
    symbol = "BTCUSDT"
    current_score = 0.3
    
    now = datetime.now(timezone.utc)
    historical_scores = [
        (now - timedelta(hours=i), 0.2 + i * 0.01)
        for i in range(48)
    ]
    historical_mentions = [
        (now - timedelta(hours=i), 100)
        for i in range(48)
    ]
    
    report = insights_gen.generate_report(
        symbol=symbol,
        posts=posts_with_scores,
        sentiments=sentiments,
        current_score=current_score,
        historical_scores=historical_scores,
        historical_mentions=historical_mentions,
    )
    
    # Verify all components are present
    assert report.symbol == symbol
    assert isinstance(report.timestamp, datetime)
    assert report.current_sentiment == current_score
    assert isinstance(report.themes, ThemeAnalysis)
    assert isinstance(report.source_diversity, SourceDiversity)
    assert isinstance(report.trend, TrendAnalysis)
    assert isinstance(report.recommendation, Recommendation)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
