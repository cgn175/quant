#!/usr/bin/env python3
"""
Label training data for FinBERT fine-tuning.

Fetches historical price data for existing raw_predictions and creates
labeled training examples based on price movement after the prediction.

Labeling strategy:
- positive: price increased >1% within 4h after prediction
- negative: price decreased >1% within 4h after prediction  
- neutral: price changed <=1% within 4h after prediction
"""

import os
import sys
import asyncio
import sqlite3
import httpx
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = os.getenv("SENTIMENT_DB_PATH", "sentiment.db")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")

# CoinGecko coin IDs for symbols
COIN_IDS = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum",
    "SOLUSDT": "solana",
    "BNBUSDT": "binancecoin",
}


@dataclass
class LabeledExample:
    text: str
    label: str  # positive, negative, neutral
    symbol: str
    timestamp: datetime
    price_at_pred: float
    price_4h_later: float
    price_change_pct: float
    source: str


def get_db_connection():
    """Get SQLite database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_predictions_without_labels(conn: sqlite3.Connection) -> List[Dict]:
    """Fetch raw predictions that don't have corresponding market snapshot data."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.id, r.symbol, r.text, r.source, r.fetched_at, r.pred_label
        FROM raw_predictions r
        LEFT JOIN market_snapshots m ON r.symbol = m.symbol 
            AND ABS(r.fetched_at - m.timestamp) < 3600
        WHERE m.id IS NULL
        ORDER BY r.fetched_at DESC
    """)
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def fetch_all_predictions(conn: sqlite3.Connection, min_confidence: float = 0.6) -> List[Dict]:
    """Fetch all raw predictions with confidence filter."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, symbol, text, source, fetched_at, pred_label, pred_confidence
        FROM raw_predictions
        WHERE pred_confidence >= ?
        ORDER BY fetched_at DESC
    """, (min_confidence,))
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


async def fetch_historical_price(
    symbol: str, 
    timestamp: datetime,
    http_client: httpx.AsyncClient
) -> Optional[Dict[str, float]]:
    """
    Fetch historical price data from CoinGecko.
    Returns price at prediction time and 4h later.
    """
    coin_id = COIN_IDS.get(symbol)
    if not coin_id:
        logger.warning(f"Unknown symbol: {symbol}")
        return None
    
    # Convert to CoinGecko format (needs date in DD-MM-YYYY for history endpoint)
    # For recent data, we can use the market_chart endpoint with hourly granularity
    
    try:
        # Calculate time range (we need data from 1h before to 6h after prediction)
        from_ts = int((timestamp - timedelta(hours=1)).timestamp())
        to_ts = int((timestamp + timedelta(hours=6)).timestamp())
        
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart/range"
        params = {
            "vs_currency": "usd",
            "from": from_ts,
            "to": to_ts,
        }
        headers = {}
        if COINGECKO_API_KEY:
            headers["x_cg_demo_api_key"] = COINGECKO_API_KEY
        
        response = await http_client.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        prices = data.get("prices", [])
        if not prices:
            logger.warning(f"No price data for {symbol} at {timestamp}")
            return None
        
        # Find price closest to prediction timestamp
        pred_ts = int(timestamp.timestamp() * 1000)  # CoinGecko uses milliseconds
        
        closest_price = None
        closest_diff = float('inf')
        
        for price_ts, price in prices:
            diff = abs(price_ts - pred_ts)
            if diff < closest_diff:
                closest_diff = diff
                closest_price = price
        
        if closest_price is None:
            return None
        
        # Find price ~4 hours later
        target_4h_ts = pred_ts + (4 * 60 * 60 * 1000)
        price_4h = None
        closest_4h_diff = float('inf')
        
        for price_ts, price in prices:
            diff = abs(price_ts - target_4h_ts)
            if diff < closest_4h_diff:
                closest_4h_diff = diff
                price_4h = price
        
        return {
            "price_at_pred": closest_price,
            "price_4h_later": price_4h,
            "prices": prices
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch price for {symbol}: {e}")
        return None


def assign_label(price_change_pct: float) -> str:
    """
    Assign sentiment label based on price change.
    
    Labeling thresholds:
    - positive: price up > 1.5%
    - negative: price down > 1.5%
    - neutral: price change <= 1.5%
    """
    if price_change_pct > 1.5:
        return "positive"
    elif price_change_pct < -1.5:
        return "negative"
    else:
        return "neutral"


def save_market_snapshot(
    conn: sqlite3.Connection,
    symbol: str,
    timestamp: datetime,
    price_close: float,
    price_4h: Optional[float] = None
):
    """Save market snapshot to database."""
    cursor = conn.cursor()
    ts_unix = int(timestamp.timestamp())
    created_at = int(datetime.now(timezone.utc).timestamp())
    
    cursor.execute("""
        INSERT OR REPLACE INTO market_snapshots
        (symbol, timestamp, price_close, price_4h_later, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (symbol, ts_unix, price_close, price_4h, created_at))
    conn.commit()


def save_labeled_examples(conn: sqlite3.Connection, examples: List[LabeledExample]):
    """Save labeled examples to training_data table."""
    cursor = conn.cursor()
    
    # Create training_data table if not exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS training_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            label TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            price_at_pred REAL,
            price_4h_later REAL,
            price_change_pct REAL,
            source TEXT,
            created_at INTEGER NOT NULL
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_training_data_symbol 
        ON training_data(symbol)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_training_data_label 
        ON training_data(label)
    """)
    
    created_at = int(datetime.now(timezone.utc).timestamp())
    
    for ex in examples:
        cursor.execute("""
            INSERT INTO training_data
            (text, label, symbol, timestamp, price_at_pred, price_4h_later, price_change_pct, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ex.text, ex.label, ex.symbol, int(ex.timestamp.timestamp()),
            ex.price_at_pred, ex.price_4h_later, ex.price_change_pct,
            ex.source, created_at
        ))
    
    conn.commit()
    logger.info(f"Saved {len(examples)} labeled examples to training_data")


def export_to_jsonl(examples: List[LabeledExample], output_path: str):
    """Export labeled examples to JSONL format for HuggingFace datasets."""
    import json
    
    with open(output_path, 'w') as f:
        for ex in examples:
            record = {
                "text": ex.text,
                "label": ex.label,
                "symbol": ex.symbol,
                "timestamp": ex.timestamp.isoformat(),
                "price_change_pct": ex.price_change_pct,
                "source": ex.source
            }
            f.write(json.dumps(record) + '\n')
    
    logger.info(f"Exported {len(examples)} examples to {output_path}")


async def label_existing_predictions():
    """
    Main function to label existing predictions with price data.
    
    This fetches historical prices for all existing predictions and creates
    labeled training examples based on subsequent price movement.
    """
    conn = get_db_connection()
    
    # Fetch predictions
    predictions = fetch_all_predictions(conn, min_confidence=0.5)
    logger.info(f"Found {len(predictions)} predictions to label")
    
    if not predictions:
        logger.warning("No predictions found. Run the sentiment service first.")
        return []
    
    labeled_examples = []
    
    async with httpx.AsyncClient() as http_client:
        for i, pred in enumerate(predictions):
            symbol = pred["symbol"]
            fetched_at = datetime.fromtimestamp(pred["fetched_at"], tz=timezone.utc)
            
            # Fetch historical price
            price_data = await fetch_historical_price(symbol, fetched_at, http_client)
            
            if price_data and price_data["price_4h_later"]:
                price_at_pred = price_data["price_at_pred"]
                price_4h = price_data["price_4h_later"]
                price_change_pct = ((price_4h - price_at_pred) / price_at_pred) * 100
                
                # Assign label based on price change
                label = assign_label(price_change_pct)
                
                example = LabeledExample(
                    text=pred["text"],
                    label=label,
                    symbol=symbol,
                    timestamp=fetched_at,
                    price_at_pred=price_at_pred,
                    price_4h_later=price_4h,
                    price_change_pct=price_change_pct,
                    source=pred["source"]
                )
                labeled_examples.append(example)
                
                # Save market snapshot
                save_market_snapshot(conn, symbol, fetched_at, price_at_pred, price_4h)
                
                logger.info(f"[{i+1}/{len(predictions)}] {symbol} @ {fetched_at}: "
                          f"{price_change_pct:+.2f}% -> {label}")
            else:
                logger.warning(f"[{i+1}/{len(predictions)}] No price data for {symbol} @ {fetched_at}")
            
            # Rate limiting
            if (i + 1) % 10 == 0:
                await asyncio.sleep(1)
    
    # Save labeled examples
    if labeled_examples:
        save_labeled_examples(conn, labeled_examples)
        export_to_jsonl(labeled_examples, "training_data.jsonl")
        
        # Print label distribution
        label_counts = {}
        for ex in labeled_examples:
            label_counts[ex.label] = label_counts.get(ex.label, 0) + 1
        
        logger.info("Label distribution:")
        for label, count in sorted(label_counts.items()):
            pct = count / len(labeled_examples) * 100
            logger.info(f"  {label}: {count} ({pct:.1f}%)")
    
    conn.close()
    return labeled_examples


def get_training_stats():
    """Get statistics about training data."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if training_data table exists
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='training_data'
    """)
    if not cursor.fetchone():
        logger.info("No training_data table yet. Run label_existing_predictions() first.")
        conn.close()
        return
    
    cursor.execute("SELECT COUNT(*) FROM training_data")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT label, COUNT(*) FROM training_data GROUP BY label")
    by_label = cursor.fetchall()
    
    cursor.execute("SELECT symbol, COUNT(*) FROM training_data GROUP BY symbol")
    by_symbol = cursor.fetchall()
    
    logger.info(f"\nTraining Data Statistics:")
    logger.info(f"Total examples: {total}")
    logger.info(f"\nBy label:")
    for label, count in by_label:
        logger.info(f"  {label}: {count}")
    logger.info(f"\nBy symbol:")
    for symbol, count in by_symbol:
        logger.info(f"  {symbol}: {count}")
    
    conn.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Label training data for FinBERT fine-tuning")
    parser.add_argument("--stats", action="store_true", help="Show training data statistics")
    parser.add_argument("--label", action="store_true", help="Label existing predictions")
    
    args = parser.parse_args()
    
    if args.stats:
        get_training_stats()
    elif args.label:
        examples = asyncio.run(label_existing_predictions())
        print(f"\nCreated {len(examples)} labeled training examples")
    else:
        # Default: show stats if available, otherwise show help
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='training_data'
        """)
        has_data = cursor.fetchone() is not None
        conn.close()
        
        if has_data:
            get_training_stats()
        else:
            parser.print_help()
            print("\n\nTo create labeled training data, run: python3 label_training_data.py --label")
