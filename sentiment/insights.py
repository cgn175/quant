"""
Sentiment insights generation module.

Provides advanced analytics beyond raw sentiment scores:
- Theme extraction from news content
- Source diversity analysis
- Anomaly detection
- Actionable recommendations
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import statistics


@dataclass
class ThemeAnalysis:
    """Extracted themes and keywords from news content."""
    
    top_keywords: List[Tuple[str, int]]  # (keyword, frequency)
    recurring_themes: List[str]  # High-level themes
    sentiment_by_theme: Dict[str, float]  # Theme -> avg sentiment


@dataclass
class SourceDiversity:
    """Metrics about source coverage and agreement."""
    
    total_sources: int
    active_sources: List[str]
    source_types: Dict[str, int]  # social/news/market -> count
    source_agreement: float  # 0-1, how aligned sources are
    dominant_source: Optional[str]  # Source with most mentions
    coverage_score: float  # 0-1, diversity of coverage


@dataclass
class TrendAnalysis:
    """Sentiment trend patterns and anomalies."""
    
    trend_direction: str  # "improving", "deteriorating", "stable"
    trend_strength: float  # 0-1
    anomaly_detected: bool
    anomaly_description: Optional[str]
    confidence_interval: Tuple[float, float]  # (lower, upper) bounds
    volatility: float  # Standard deviation of recent scores


@dataclass
class Recommendation:
    """Actionable trading signal based on sentiment."""
    
    signal: str  # "strong_bullish", "bullish", "neutral", "bearish", "strong_bearish", "mixed"
    confidence: float  # 0-1
    reasoning: List[str]  # Human-readable explanations
    risk_level: str  # "low", "medium", "high"
    suggested_action: str  # "buy", "hold", "sell", "wait"


@dataclass
class InsightReport:
    """Complete sentiment intelligence report."""
    
    symbol: str
    timestamp: datetime
    current_sentiment: float
    themes: ThemeAnalysis
    source_diversity: SourceDiversity
    trend: TrendAnalysis
    recommendation: Recommendation


class InsightsGenerator:
    """Generate actionable insights from sentiment data."""
    
    # Common crypto/finance keywords to filter out noise
    STOPWORDS = {
        "bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency",
        "coin", "token", "blockchain", "trading", "price", "market",
        "buy", "sell", "hodl", "moon", "the", "and", "or", "is", "to",
        "for", "of", "in", "on", "at", "with", "by", "from", "as", "a"
    }
    
    # Theme patterns for categorization
    THEME_PATTERNS = {
        "regulation": r"\b(regulat|sec|government|ban|legal|law)\w*\b",
        "technology": r"\b(upgrade|fork|update|protocol|network|scaling|layer)\w*\b",
        "adoption": r"\b(adopt|accept|partner|integration|mainstream|institution)\w*\b",
        "market_movement": r"\b(pump|dump|rally|crash|surge|plunge|spike|drop)\w*\b",
        "security": r"\b(hack|breach|security|vulnerability|exploit|scam)\w*\b",
        "innovation": r"\b(innovation|breakthrough|development|launch|release)\w*\b",
    }
    
    # Source type classification
    SOURCE_TYPES = {
        "social": ["reddit", "twitter"],
        "news": ["newsapi", "marketaux", "finnhub", "fmp", "cryptopanic"],
        "market_data": ["coingecko", "coinmarketcap"],
    }
    
    def extract_themes(
        self, posts: List[tuple], sentiments: List[Dict[str, float]]
    ) -> ThemeAnalysis:
        """Extract key themes from post content.
        
        Args:
            posts: List of (Post, sentiment_score) tuples
            sentiments: List of sentiment dicts from FinBERT
            
        Returns:
            ThemeAnalysis with keywords and themes
        """
        # Extract all words from posts
        all_text = " ".join(post.text.lower() for post, _ in posts)
        words = re.findall(r'\b[a-z]{3,}\b', all_text)
        
        # Filter stopwords and count
        filtered_words = [w for w in words if w not in self.STOPWORDS]
        word_counts = Counter(filtered_words)
        top_keywords = word_counts.most_common(10)
        
        # Match theme patterns
        detected_themes = []
        theme_sentiments = defaultdict(list)
        
        for theme, pattern in self.THEME_PATTERNS.items():
            theme_regex = re.compile(pattern, re.IGNORECASE)
            matches = 0
            
            for (post, _), sent in zip(posts, sentiments):
                if theme_regex.search(post.text):
                    matches += 1
                    score = sent["positive"] - sent["negative"]
                    theme_sentiments[theme].append(score)
            
            if matches > 0:
                detected_themes.append(theme)
        
        # Calculate average sentiment per theme
        sentiment_by_theme = {
            theme: statistics.mean(scores) if scores else 0.0
            for theme, scores in theme_sentiments.items()
        }
        
        return ThemeAnalysis(
            top_keywords=top_keywords,
            recurring_themes=detected_themes,
            sentiment_by_theme=sentiment_by_theme,
        )
    
    def analyze_source_diversity(
        self, posts: List[tuple], sentiments: List[Dict[str, float]]
    ) -> SourceDiversity:
        """Analyze diversity and agreement across sources.
        
        Args:
            posts: List of (Post, sentiment_score) tuples
            sentiments: List of sentiment dicts
            
        Returns:
            SourceDiversity metrics
        """
        sources_used = set()
        source_mentions = Counter()
        source_sentiments = defaultdict(list)
        source_type_counts = defaultdict(int)
        
        for (post, _), sent in zip(posts, sentiments):
            sources_used.add(post.source)
            source_mentions[post.source] += 1
            score = sent["positive"] - sent["negative"]
            source_sentiments[post.source].append(score)
            
            # Categorize source type
            for source_type, source_list in self.SOURCE_TYPES.items():
                if post.source in source_list:
                    source_type_counts[source_type] += 1
                    break
        
        total_sources = len(sources_used)
        
        # Calculate source agreement (inverse of variance across sources)
        if len(source_sentiments) > 1:
            source_avg_sentiments = [
                statistics.mean(scores) for scores in source_sentiments.values()
            ]
            variance = statistics.variance(source_avg_sentiments)
            agreement = max(0.0, 1.0 - variance)  # Lower variance = higher agreement
        else:
            agreement = 1.0
        
        # Find dominant source
        dominant_source = source_mentions.most_common(1)[0][0] if source_mentions else None
        
        # Coverage score based on source diversity
        max_sources = len(self.SOURCE_TYPES["social"]) + len(self.SOURCE_TYPES["news"]) + len(self.SOURCE_TYPES["market_data"])
        coverage_score = min(1.0, total_sources / max_sources)
        
        return SourceDiversity(
            total_sources=total_sources,
            active_sources=sorted(sources_used),
            source_types=dict(source_type_counts),
            source_agreement=round(agreement, 4),
            dominant_source=dominant_source,
            coverage_score=round(coverage_score, 4),
        )
    
    def detect_trends_and_anomalies(
        self,
        symbol: str,
        current_score: float,
        historical_scores: List[Tuple[datetime, float]],
        current_mentions: int,
        historical_mentions: List[Tuple[datetime, int]],
    ) -> TrendAnalysis:
        """Detect sentiment trends and anomalies.
        
        Args:
            symbol: Trading symbol
            current_score: Current sentiment score
            historical_scores: List of (timestamp, score) tuples
            current_mentions: Current mention count
            historical_mentions: List of (timestamp, count) tuples
            
        Returns:
            TrendAnalysis with trends and anomalies
        """
        if len(historical_scores) < 5:
            return TrendAnalysis(
                trend_direction="insufficient_data",
                trend_strength=0.0,
                anomaly_detected=False,
                anomaly_description=None,
                confidence_interval=(current_score, current_score),
                volatility=0.0,
            )
        
        # Sort by timestamp to ensure correct ordering (oldest to newest)
        sorted_scores = sorted(historical_scores, key=lambda x: x[0])
        
        # Extract recent scores (last 24) and older scores (previous 24)
        recent_scores = [score for _, score in sorted_scores[-24:]]  # Last 24 hours
        older_scores = [score for _, score in sorted_scores[-48:-24]] if len(sorted_scores) >= 48 else recent_scores
        
        recent_avg = statistics.mean(recent_scores)
        older_avg = statistics.mean(older_scores) if older_scores else recent_avg
        
        # Determine trend direction
        delta = recent_avg - older_avg
        if abs(delta) < 0.05:
            trend_direction = "stable"
            trend_strength = 0.0
        elif delta > 0:
            trend_direction = "improving"
            trend_strength = min(1.0, delta / 0.5)  # Normalize to 0-1
        else:
            trend_direction = "deteriorating"
            trend_strength = min(1.0, abs(delta) / 0.5)
        
        # Calculate volatility
        volatility = statistics.stdev(recent_scores) if len(recent_scores) > 1 else 0.0
        
        # Anomaly detection: check if current score is >2 std devs from mean
        all_historical_scores = [score for _, score in sorted_scores]
        if len(all_historical_scores) > 10:
            mean = statistics.mean(all_historical_scores)
            stdev = statistics.stdev(all_historical_scores)
            
            if stdev > 0:
                z_score = (current_score - mean) / stdev
                anomaly_detected = abs(z_score) > 2.0
                
                if anomaly_detected:
                    if z_score > 0:
                        anomaly_description = f"Unusually positive sentiment (z-score: {z_score:.2f})"
                    else:
                        anomaly_description = f"Unusually negative sentiment (z-score: {z_score:.2f})"
                else:
                    anomaly_description = None
            else:
                anomaly_detected = False
                anomaly_description = None
        else:
            anomaly_detected = False
            anomaly_description = None
        
        # Confidence interval (95%)
        if len(recent_scores) > 2:
            mean = statistics.mean(recent_scores)
            stdev = statistics.stdev(recent_scores)
            margin = 1.96 * stdev / (len(recent_scores) ** 0.5)  # 95% CI
            confidence_interval = (mean - margin, mean + margin)
        else:
            confidence_interval = (current_score, current_score)
        
        return TrendAnalysis(
            trend_direction=trend_direction,
            trend_strength=round(trend_strength, 4),
            anomaly_detected=anomaly_detected,
            anomaly_description=anomaly_description,
            confidence_interval=(round(confidence_interval[0], 4), round(confidence_interval[1], 4)),
            volatility=round(volatility, 4),
        )
    
    def generate_recommendation(
        self,
        current_score: float,
        trend: TrendAnalysis,
        source_diversity: SourceDiversity,
        themes: ThemeAnalysis,
    ) -> Recommendation:
        """Generate actionable trading recommendation.
        
        Args:
            current_score: Current sentiment score
            trend: Trend analysis results
            source_diversity: Source diversity metrics
            themes: Theme analysis results
            
        Returns:
            Recommendation with signal and reasoning
        """
        reasoning = []
        confidence_factors = []
        risk_factors = []
        
        # Analyze current sentiment
        if current_score > 0.3:
            signal_base = "bullish"
            reasoning.append(f"Strong positive sentiment ({current_score:.2f})")
            confidence_factors.append(0.3)
        elif current_score > 0.1:
            signal_base = "bullish"
            reasoning.append(f"Moderate positive sentiment ({current_score:.2f})")
            confidence_factors.append(0.2)
        elif current_score < -0.3:
            signal_base = "bearish"
            reasoning.append(f"Strong negative sentiment ({current_score:.2f})")
            confidence_factors.append(0.3)
        elif current_score < -0.1:
            signal_base = "bearish"
            reasoning.append(f"Moderate negative sentiment ({current_score:.2f})")
            confidence_factors.append(0.2)
        else:
            signal_base = "neutral"
            reasoning.append(f"Neutral sentiment ({current_score:.2f})")
            confidence_factors.append(0.1)
        
        # Factor in trend
        if trend.trend_direction == "improving":
            reasoning.append(f"Sentiment improving (strength: {trend.trend_strength:.2f})")
            confidence_factors.append(trend.trend_strength * 0.3)
            if signal_base == "bearish":
                signal_base = "neutral"  # Contradicting signals
                reasoning.append("⚠️ Mixed signals: negative sentiment but improving trend")
        elif trend.trend_direction == "deteriorating":
            reasoning.append(f"Sentiment deteriorating (strength: {trend.trend_strength:.2f})")
            confidence_factors.append(trend.trend_strength * 0.3)
            if signal_base == "bullish":
                signal_base = "neutral"  # Contradicting signals
                reasoning.append("⚠️ Mixed signals: positive sentiment but deteriorating trend")
        
        # Check source diversity
        if source_diversity.coverage_score > 0.6:
            reasoning.append(f"High source diversity ({source_diversity.total_sources} sources)")
            confidence_factors.append(0.2)
        elif source_diversity.coverage_score < 0.3:
            reasoning.append(f"Low source diversity ({source_diversity.total_sources} sources)")
            risk_factors.append(0.2)
        
        if source_diversity.source_agreement > 0.7:
            reasoning.append(f"High source agreement ({source_diversity.source_agreement:.2f})")
            confidence_factors.append(0.2)
        elif source_diversity.source_agreement < 0.4:
            reasoning.append(f"Low source agreement - conflicting signals")
            signal_base = "mixed"
            risk_factors.append(0.3)
        
        # Anomaly check
        if trend.anomaly_detected:
            reasoning.append(f"⚠️ Anomaly: {trend.anomaly_description}")
            risk_factors.append(0.3)
        
        # Volatility check
        if trend.volatility > 0.3:
            reasoning.append(f"High volatility ({trend.volatility:.2f}) - sentiment unstable")
            risk_factors.append(0.2)
        
        # Theme analysis
        negative_themes = [
            theme for theme, sent in themes.sentiment_by_theme.items()
            if sent < -0.2 and theme in ["security", "regulation"]
        ]
        if negative_themes:
            reasoning.append(f"⚠️ Negative themes detected: {', '.join(negative_themes)}")
            risk_factors.append(0.2)
        
        # Calculate final confidence
        total_confidence = sum(confidence_factors)
        total_risk = sum(risk_factors)
        final_confidence = max(0.0, min(1.0, total_confidence - total_risk))
        
        # Determine final signal
        if signal_base == "mixed":
            final_signal = "mixed"
            suggested_action = "wait"
            risk_level = "high"
        elif signal_base == "bullish":
            if final_confidence > 0.7:
                final_signal = "strong_bullish"
                suggested_action = "buy"
                risk_level = "low"
            else:
                final_signal = "bullish"
                suggested_action = "buy" if final_confidence > 0.5 else "hold"
                risk_level = "medium" if final_confidence > 0.5 else "high"
        elif signal_base == "bearish":
            if final_confidence > 0.7:
                final_signal = "strong_bearish"
                suggested_action = "sell"
                risk_level = "low"
            else:
                final_signal = "bearish"
                suggested_action = "sell" if final_confidence > 0.5 else "hold"
                risk_level = "medium" if final_confidence > 0.5 else "high"
        else:  # neutral
            final_signal = "neutral"
            suggested_action = "hold"
            risk_level = "medium"
        
        return Recommendation(
            signal=final_signal,
            confidence=round(final_confidence, 4),
            reasoning=reasoning,
            risk_level=risk_level,
            suggested_action=suggested_action,
        )
    
    def generate_report(
        self,
        symbol: str,
        posts: List[tuple],  # List of (Post, sentiment_score)
        sentiments: List[Dict[str, float]],
        current_score: float,
        historical_scores: List[Tuple[datetime, float]],
        historical_mentions: List[Tuple[datetime, int]],
    ) -> InsightReport:
        """Generate complete insights report.
        
        Args:
            symbol: Trading symbol
            posts: List of (Post, sentiment_score) tuples
            sentiments: Sentiment analysis results from FinBERT
            current_score: Current aggregated sentiment score
            historical_scores: Historical sentiment data
            historical_mentions: Historical mention counts
            
        Returns:
            Complete InsightReport
        """
        current_mentions = len([p for p, _ in posts if (datetime.now(timezone.utc) - p.timestamp).total_seconds() < 3600])
        
        themes = self.extract_themes(posts, sentiments)
        source_diversity = self.analyze_source_diversity(posts, sentiments)
        trend = self.detect_trends_and_anomalies(
            symbol, current_score, historical_scores, current_mentions, historical_mentions
        )
        recommendation = self.generate_recommendation(
            current_score, trend, source_diversity, themes
        )
        
        return InsightReport(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            current_sentiment=current_score,
            themes=themes,
            source_diversity=source_diversity,
            trend=trend,
            recommendation=recommendation,
        )
