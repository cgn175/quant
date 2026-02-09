"""
Database persistence layer for sentiment data using SQLite.

Stores sentiment scores, source attribution, mention counts, and timestamps.
Supports both hourly aggregates (for recent data) and daily aggregates (for historical).
"""

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class SentimentDB:
    """Async SQLite wrapper for sentiment data persistence."""

    def __init__(self, db_path: str = "sentiment.db"):
        self.db_path = db_path
        self.loop = asyncio.get_event_loop()
        self._init_db()

    def _init_db(self):
        """Initialize database schema if not exists."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Hourly sentiment aggregates (recent data, 7 days retention)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sentiment_hourly (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                score_positive REAL NOT NULL,
                score_negative REAL NOT NULL,
                score_neutral REAL NOT NULL,
                mentions_count INTEGER NOT NULL,
                sources TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(symbol, timestamp)
            )
        """)

        # Daily sentiment aggregates (long-term history, 2 years retention)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sentiment_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                date TEXT NOT NULL,
                score_positive REAL NOT NULL,
                score_negative REAL NOT NULL,
                score_neutral REAL NOT NULL,
                mentions_count INTEGER NOT NULL,
                sources TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(symbol, date)
            )
        """)

        # Per-source sentiment scores (granular tracking)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sentiment_source (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                source TEXT NOT NULL,
                score REAL NOT NULL,
                mentions_count INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)

        # Mention history for velocity/zscore calculations
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mention_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                count INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)

        # Create indices for efficient querying
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sentiment_hourly_symbol_time
            ON sentiment_hourly(symbol, timestamp DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sentiment_daily_symbol_date
            ON sentiment_daily(symbol, date DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sentiment_source_symbol_time
            ON sentiment_source(symbol, timestamp DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_mention_history_symbol_time
            ON mention_history(symbol, timestamp DESC)
        """)

        conn.commit()
        conn.close()
        logger.info(f"Sentiment database initialized at {self.db_path}")

    async def save_hourly_sentiment(
        self,
        symbol: str,
        timestamp: datetime,
        score_positive: float,
        score_negative: float,
        score_neutral: float,
        mentions_count: int,
        sources: List[str],
    ) -> bool:
        """Save hourly sentiment aggregate."""

        def _save():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            sources_str = ",".join(sources)
            ts_unix = int(timestamp.timestamp())
            now_unix = int(datetime.now(timezone.utc).timestamp())

            try:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO sentiment_hourly
                    (symbol, timestamp, score_positive, score_negative, score_neutral,
                     mentions_count, sources, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        symbol,
                        ts_unix,
                        score_positive,
                        score_negative,
                        score_neutral,
                        mentions_count,
                        sources_str,
                        now_unix,
                    ),
                )
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Failed to save hourly sentiment: {e}")
                return False
            finally:
                conn.close()

        return await self.loop.run_in_executor(None, _save)

    async def save_daily_sentiment(
        self,
        symbol: str,
        date: str,  # YYYY-MM-DD
        score_positive: float,
        score_negative: float,
        score_neutral: float,
        mentions_count: int,
        sources: List[str],
    ) -> bool:
        """Save daily sentiment aggregate."""

        def _save():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            sources_str = ",".join(sources)
            now_unix = int(datetime.now(timezone.utc).timestamp())

            try:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO sentiment_daily
                    (symbol, date, score_positive, score_negative, score_neutral,
                     mentions_count, sources, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        symbol,
                        date,
                        score_positive,
                        score_negative,
                        score_neutral,
                        mentions_count,
                        sources_str,
                        now_unix,
                    ),
                )
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Failed to save daily sentiment: {e}")
                return False
            finally:
                conn.close()

        return await self.loop.run_in_executor(None, _save)

    async def save_source_sentiment(
        self,
        symbol: str,
        timestamp: datetime,
        source: str,
        score: float,
        mentions_count: int,
    ) -> bool:
        """Save per-source sentiment score."""

        def _save():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            ts_unix = int(timestamp.timestamp())
            now_unix = int(datetime.now(timezone.utc).timestamp())

            try:
                cursor.execute(
                    """
                    INSERT INTO sentiment_source
                    (symbol, timestamp, source, score, mentions_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (symbol, ts_unix, source, score, mentions_count, now_unix),
                )
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Failed to save source sentiment: {e}")
                return False
            finally:
                conn.close()

        return await self.loop.run_in_executor(None, _save)

    async def save_mention_history(
        self,
        symbol: str,
        timestamp: datetime,
        count: int,
    ) -> bool:
        """Save mention count for this hour."""

        def _save():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            ts_unix = int(timestamp.timestamp())
            now_unix = int(datetime.now(timezone.utc).timestamp())

            try:
                cursor.execute(
                    """
                    INSERT INTO mention_history
                    (symbol, timestamp, count, created_at)
                    VALUES (?, ?, ?, ?)
                """,
                    (symbol, ts_unix, count, now_unix),
                )
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Failed to save mention history: {e}")
                return False
            finally:
                conn.close()

        return await self.loop.run_in_executor(None, _save)

    async def get_hourly_sentiment(
        self,
        symbol: str,
        hours: int = 24,
    ) -> List[Dict]:
        """Fetch hourly sentiment data for the past N hours."""

        def _fetch():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cutoff_ts = int(
                (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()
            )

            cursor.execute(
                """
                SELECT timestamp, score_positive, score_negative, score_neutral,
                       mentions_count, sources
                FROM sentiment_hourly
                WHERE symbol = ? AND timestamp >= ?
                ORDER BY timestamp DESC
            """,
                (symbol, cutoff_ts),
            )

            rows = cursor.fetchall()
            conn.close()

            return [
                {
                    "timestamp": datetime.fromtimestamp(row[0], tz=timezone.utc),
                    "score_positive": row[1],
                    "score_negative": row[2],
                    "score_neutral": row[3],
                    "mentions_count": row[4],
                    "sources": row[5].split(",") if row[5] else [],
                }
                for row in rows
            ]

        return await self.loop.run_in_executor(None, _fetch)

    async def get_daily_sentiment(
        self,
        symbol: str,
        days: int = 90,
    ) -> List[Dict]:
        """Fetch daily sentiment data for the past N days."""

        def _fetch():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cutoff_date = (
                (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
            )

            cursor.execute(
                """
                SELECT date, score_positive, score_negative, score_neutral,
                       mentions_count, sources
                FROM sentiment_daily
                WHERE symbol = ? AND date >= ?
                ORDER BY date DESC
            """,
                (symbol, cutoff_date),
            )

            rows = cursor.fetchall()
            conn.close()

            return [
                {
                    "date": row[0],
                    "score_positive": row[1],
                    "score_negative": row[2],
                    "score_neutral": row[3],
                    "mentions_count": row[4],
                    "sources": row[5].split(",") if row[5] else [],
                }
                for row in rows
            ]

        return await self.loop.run_in_executor(None, _fetch)

    async def get_mention_history(
        self,
        symbol: str,
        hours: int = 24,
    ) -> List[Tuple[datetime, int]]:
        """Fetch mention count history for zscore calculation."""

        def _fetch():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cutoff_ts = int(
                (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()
            )

            cursor.execute(
                """
                SELECT timestamp, count
                FROM mention_history
                WHERE symbol = ? AND timestamp >= ?
                ORDER BY timestamp DESC
            """,
                (symbol, cutoff_ts),
            )

            rows = cursor.fetchall()
            conn.close()

            return [
                (datetime.fromtimestamp(row[0], tz=timezone.utc), row[1])
                for row in rows
            ]

        return await self.loop.run_in_executor(None, _fetch)

    async def cleanup_old_data(self) -> bool:
        """Delete old sentiment data beyond retention periods."""

        def _cleanup():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Keep hourly data for 7 days
            cutoff_hourly = int(
                (datetime.now(timezone.utc) - timedelta(days=7)).timestamp()
            )
            cursor.execute(
                "DELETE FROM sentiment_hourly WHERE timestamp < ?", (cutoff_hourly,)
            )

            # Keep daily data for 2 years
            cutoff_daily = (
                (datetime.now(timezone.utc) - timedelta(days=730)).date().isoformat()
            )
            cursor.execute(
                "DELETE FROM sentiment_daily WHERE date < ?", (cutoff_daily,)
            )

            # Keep mention history for 24 hours
            cutoff_mentions = int(
                (datetime.now(timezone.utc) - timedelta(hours=24)).timestamp()
            )
            cursor.execute(
                "DELETE FROM mention_history WHERE timestamp < ?", (cutoff_mentions,)
            )

            conn.commit()
            deleted = cursor.rowcount
            conn.close()

            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old sentiment records")
            return True

        return await self.loop.run_in_executor(None, _cleanup)

    async def has_any_data(self) -> bool:
        """Return True if any sentiment data exists in the database."""

        def _check():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT 1 FROM sentiment_hourly LIMIT 1")
                if cursor.fetchone():
                    return True
                cursor.execute("SELECT 1 FROM sentiment_daily LIMIT 1")
                return cursor.fetchone() is not None
            finally:
                conn.close()

        return await self.loop.run_in_executor(None, _check)
