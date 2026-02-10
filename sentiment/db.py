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

        # Raw predictions (every fetched article + FinBERT prediction)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                text TEXT NOT NULL,
                source TEXT NOT NULL,
                fetched_at INTEGER NOT NULL,
                published_at INTEGER,
                pred_positive REAL NOT NULL,
                pred_negative REAL NOT NULL,
                pred_neutral REAL NOT NULL,
                pred_label TEXT NOT NULL,
                pred_confidence REAL NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_raw_predictions_symbol_time
            ON raw_predictions(symbol, fetched_at DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_raw_predictions_source
            ON raw_predictions(source, fetched_at DESC)
        """)

        # Market snapshots (price data at prediction time for backtesting)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                price_open REAL,
                price_high REAL,
                price_low REAL,
                price_close REAL NOT NULL,
                volume REAL,
                price_1h_later REAL,
                price_4h_later REAL,
                price_24h_later REAL,
                created_at INTEGER NOT NULL,
                UNIQUE(symbol, timestamp)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_market_snapshots_symbol_time
            ON market_snapshots(symbol, timestamp DESC)
        """)

        # Telegram messages (from listener service)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS telegram_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                channel_username TEXT NOT NULL,
                text TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                processed BOOLEAN DEFAULT 0,
                UNIQUE(channel_username, message_id)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_telegram_messages_timestamp
            ON telegram_messages(timestamp DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_telegram_messages_processed
            ON telegram_messages(processed, timestamp DESC)
        """)

        # Fetched posts (all raw posts from all sources before analysis)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fetched_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                text TEXT NOT NULL,
                source TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                score INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL,
                UNIQUE(text, source, timestamp)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_fetched_posts_symbol_time
            ON fetched_posts(symbol, timestamp DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_fetched_posts_source
            ON fetched_posts(source, timestamp DESC)
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

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _save)

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

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _save)

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

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _save)

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

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _save)

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

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch)

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

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch)

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

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch)

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

            # Keep mention history for 7 days (to support z-score calculation)
            cutoff_mentions = int(
                (datetime.now(timezone.utc) - timedelta(days=7)).timestamp()
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

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _cleanup)

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

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _check)

    async def save_raw_predictions(
        self,
        symbol: str,
        predictions: List[Dict],
    ) -> bool:
        """Bulk insert raw FinBERT predictions."""

        def _save():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            now_unix = int(datetime.now(timezone.utc).timestamp())

            try:
                rows = []
                for p in predictions:
                    fetched_at = int(p["fetched_at"].timestamp())
                    published_at = (
                        int(p["published_at"].timestamp())
                        if p.get("published_at")
                        else None
                    )
                    rows.append((
                        symbol,
                        p["text"],
                        p["source"],
                        fetched_at,
                        published_at,
                        p["pred_positive"],
                        p["pred_negative"],
                        p["pred_neutral"],
                        p["pred_label"],
                        p["pred_confidence"],
                        now_unix,
                    ))

                cursor.executemany(
                    """
                    INSERT INTO raw_predictions
                    (symbol, text, source, fetched_at, published_at,
                     pred_positive, pred_negative, pred_neutral,
                     pred_label, pred_confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    rows,
                )
                conn.commit()
                logger.info(
                    f"Saved {len(rows)} raw predictions for {symbol}"
                )
                return True
            except Exception as e:
                logger.error(f"Failed to save raw predictions: {e}")
                return False
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _save)

    async def save_market_snapshot(
        self,
        symbol: str,
        timestamp: datetime,
        price_close: float,
        price_open: Optional[float] = None,
        price_high: Optional[float] = None,
        price_low: Optional[float] = None,
        volume: Optional[float] = None,
    ) -> bool:
        """Save market price snapshot for later backtesting."""

        def _save():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            ts_unix = int(timestamp.timestamp())
            now_unix = int(datetime.now(timezone.utc).timestamp())

            try:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO market_snapshots
                    (symbol, timestamp, price_open, price_high, price_low,
                     price_close, volume, price_1h_later, price_4h_later,
                     price_24h_later, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?)
                """,
                    (
                        symbol,
                        ts_unix,
                        price_open,
                        price_high,
                        price_low,
                        price_close,
                        volume,
                        now_unix,
                    ),
                )
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"Failed to save market snapshot: {e}")
                return False
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _save)

    async def update_market_snapshot_prices(
        self,
        symbol: str,
        timestamp: datetime,
        price_1h: Optional[float] = None,
        price_4h: Optional[float] = None,
        price_24h: Optional[float] = None,
    ) -> bool:
        """Update future price fields for a market snapshot."""

        def _update():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            ts_unix = int(timestamp.timestamp())

            try:
                set_clauses = []
                params = []
                if price_1h is not None:
                    set_clauses.append("price_1h_later = ?")
                    params.append(price_1h)
                if price_4h is not None:
                    set_clauses.append("price_4h_later = ?")
                    params.append(price_4h)
                if price_24h is not None:
                    set_clauses.append("price_24h_later = ?")
                    params.append(price_24h)

                if not set_clauses:
                    return True

                params.extend([symbol, ts_unix])
                cursor.execute(
                    f"""
                    UPDATE market_snapshots
                    SET {', '.join(set_clauses)}
                    WHERE symbol = ? AND timestamp = ?
                """,
                    params,
                )
                conn.commit()
                return True
            except Exception as e:
                logger.error(
                    f"Failed to update market snapshot prices: {e}"
                )
                return False
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _update)

    async def get_raw_predictions(
        self,
        symbol: str,
        hours: int = 24,
        source: Optional[str] = None,
    ) -> List[Dict]:
        """Fetch raw predictions for a symbol within the past N hours."""

        def _fetch():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cutoff_ts = int(
                (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()
            )

            try:
                if source:
                    cursor.execute(
                        """
                        SELECT id, symbol, text, source, fetched_at, published_at,
                               pred_positive, pred_negative, pred_neutral,
                               pred_label, pred_confidence, created_at
                        FROM raw_predictions
                        WHERE symbol = ? AND fetched_at >= ? AND source = ?
                        ORDER BY fetched_at DESC
                    """,
                        (symbol, cutoff_ts, source),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT id, symbol, text, source, fetched_at, published_at,
                               pred_positive, pred_negative, pred_neutral,
                               pred_label, pred_confidence, created_at
                        FROM raw_predictions
                        WHERE symbol = ? AND fetched_at >= ?
                        ORDER BY fetched_at DESC
                    """,
                        (symbol, cutoff_ts),
                    )

                rows = cursor.fetchall()
                return [
                    {
                        "id": row[0],
                        "symbol": row[1],
                        "text": row[2],
                        "source": row[3],
                        "fetched_at": datetime.fromtimestamp(
                            row[4], tz=timezone.utc
                        ),
                        "published_at": (
                            datetime.fromtimestamp(row[5], tz=timezone.utc)
                            if row[5]
                            else None
                        ),
                        "pred_positive": row[6],
                        "pred_negative": row[7],
                        "pred_neutral": row[8],
                        "pred_label": row[9],
                        "pred_confidence": row[10],
                        "created_at": datetime.fromtimestamp(
                            row[11], tz=timezone.utc
                        ),
                    }
                    for row in rows
                ]
            except Exception as e:
                logger.error(f"Failed to fetch raw predictions: {e}")
                return []
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch)

    async def get_prediction_accuracy(
        self,
        symbol: str,
        days: int = 7,
    ) -> Dict:
        """Compute prediction accuracy by joining predictions with market snapshots."""

        def _fetch():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cutoff_ts = int(
                (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
            )

            try:
                cursor.execute(
                    """
                    SELECT r.pred_label, r.source,
                           m.price_close, m.price_4h_later
                    FROM raw_predictions r
                    JOIN market_snapshots m
                      ON r.symbol = m.symbol
                      AND m.timestamp = (
                          SELECT MAX(ms.timestamp)
                          FROM market_snapshots ms
                          WHERE ms.symbol = r.symbol
                            AND ms.timestamp <= r.fetched_at
                      )
                    WHERE r.symbol = ?
                      AND r.fetched_at >= ?
                      AND m.price_4h_later IS NOT NULL
                    ORDER BY r.fetched_at DESC
                """,
                    (symbol, cutoff_ts),
                )

                rows = cursor.fetchall()

                total = 0
                correct = 0
                by_source: Dict[str, Dict] = {}

                for pred_label, source, price_close, price_4h in rows:
                    if price_close is None or price_4h is None:
                        continue

                    total += 1
                    change_pct = (price_4h - price_close) / price_close

                    is_correct = False
                    if pred_label == "positive" and price_4h > price_close:
                        is_correct = True
                    elif pred_label == "negative" and price_4h < price_close:
                        is_correct = True
                    elif pred_label == "neutral" and abs(change_pct) < 0.01:
                        is_correct = True

                    if is_correct:
                        correct += 1

                    if source not in by_source:
                        by_source[source] = {"total": 0, "correct": 0}
                    by_source[source]["total"] += 1
                    if is_correct:
                        by_source[source]["correct"] += 1

                accuracy = correct / total if total > 0 else 0.0
                source_accuracy = {}
                for src, counts in by_source.items():
                    src_acc = (
                        counts["correct"] / counts["total"]
                        if counts["total"] > 0
                        else 0.0
                    )
                    source_accuracy[src] = {
                        "total": counts["total"],
                        "correct": counts["correct"],
                        "accuracy": src_acc,
                    }

                return {
                    "total": total,
                    "correct": correct,
                    "accuracy": accuracy,
                    "by_source": source_accuracy,
                }
            except Exception as e:
                logger.error(f"Failed to compute prediction accuracy: {e}")
                return {
                    "total": 0,
                    "correct": 0,
                    "accuracy": 0.0,
                    "by_source": {},
                }
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch)

    async def save_telegram_message(
        self,
        message_id: int,
        channel_username: str,
        text: str,
        timestamp: datetime,
    ) -> bool:
        """Save raw Telegram message from listener service."""

        def _save():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            ts_unix = int(timestamp.timestamp())
            now_unix = int(datetime.now(timezone.utc).timestamp())

            try:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO telegram_messages
                    (message_id, channel_username, text, timestamp, created_at, processed)
                    VALUES (?, ?, ?, ?, ?, 0)
                """,
                    (message_id, channel_username, text, ts_unix, now_unix),
                )
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Failed to save telegram message: {e}")
                return False
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _save)

    async def get_unprocessed_telegram_messages(
        self, limit: int = 100
    ) -> List[Dict]:
        """Get unprocessed Telegram messages for sentiment analysis."""

        def _fetch():
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            try:
                cursor.execute(
                    """
                    SELECT id, message_id, channel_username, text, timestamp
                    FROM telegram_messages
                    WHERE processed = 0
                    ORDER BY timestamp DESC
                    LIMIT ?
                """,
                    (limit,),
                )
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to fetch unprocessed messages: {e}")
                return []
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch)

    async def mark_telegram_message_processed(self, message_db_id: int) -> bool:
        """Mark a Telegram message as processed."""

        def _mark():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            try:
                cursor.execute(
                    """
                    UPDATE telegram_messages
                    SET processed = 1
                    WHERE id = ?
                """,
                    (message_db_id,),
                )
                conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Failed to mark message as processed: {e}")
                return False
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _mark)

    async def save_fetched_posts(self, posts: List) -> int:
        """Save fetched posts to database. Returns number of new posts saved."""
        
        def _save():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            now_unix = int(datetime.now(timezone.utc).timestamp())
            saved_count = 0
            
            try:
                for post in posts:
                    ts_unix = int(post.timestamp.timestamp())
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO fetched_posts
                        (symbol, text, source, timestamp, score, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (post.symbol, post.text, post.source, ts_unix, post.score, now_unix),
                    )
                    if cursor.rowcount > 0:
                        saved_count += 1
                
                conn.commit()
                return saved_count
            except Exception as e:
                logger.error(f"Failed to save fetched posts: {e}")
                return 0
            finally:
                conn.close()
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _save)

    async def get_fetched_posts(
        self,
        symbol: str,
        hours: int = 24,
        source: Optional[str] = None,
    ) -> List[Dict]:
        """Fetch all posts for a symbol within the past N hours."""
        
        def _fetch():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cutoff_ts = int(
                (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()
            )
            
            try:
                if source:
                    cursor.execute(
                        """
                        SELECT id, symbol, text, source, timestamp, score, created_at
                        FROM fetched_posts
                        WHERE symbol = ? AND timestamp >= ? AND source = ?
                        ORDER BY timestamp DESC
                        """,
                        (symbol, cutoff_ts, source),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT id, symbol, text, source, timestamp, score, created_at
                        FROM fetched_posts
                        WHERE symbol = ? AND timestamp >= ?
                        ORDER BY timestamp DESC
                        """,
                        (symbol, cutoff_ts),
                    )
                
                rows = cursor.fetchall()
                return [
                    {
                        "id": row[0],
                        "symbol": row[1],
                        "text": row[2],
                        "source": row[3],
                        "timestamp": datetime.fromtimestamp(row[4], tz=timezone.utc),
                        "score": row[5],
                        "created_at": datetime.fromtimestamp(row[6], tz=timezone.utc),
                    }
                    for row in rows
                ]
            except Exception as e:
                logger.error(f"Failed to fetch posts: {e}")
                return []
            finally:
                conn.close()
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch)
