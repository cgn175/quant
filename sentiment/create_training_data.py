#!/usr/bin/env python3
"""
Create training data for FinBERT fine-tuning.

Two strategies:
1. Use existing FinBERT predictions as pseudo-labels (weak supervision)
2. Fetch price data and label based on price movement (strong supervision) - slower

Usage:
    python3 create_training_data.py --strategy pseudo    # Fast, uses existing predictions
    python3 create_training_data.py --strategy price     # Slow, fetches price data
"""

import os
import sys
import json
import sqlite3
import asyncio
import httpx
import logging
import argparse
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = os.getenv("SENTIMENT_DB_PATH", "sentiment.db")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")

LABEL_MAP = {"positive": 0, "negative": 1, "neutral": 2}


@dataclass
class TrainingExample:
    text: str
    label: str
    symbol: str
    source: str
    confidence: float
    label_strategy: str  # 'pseudo' or 'price'


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_predictions_pseudo_labels(min_confidence: float = 0.7, limit: int = 1000) -> List[TrainingExample]:
    """
    Create training examples using high-confidence predictions as pseudo-labels.
    This is fast and doesn't require API calls.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT text, pred_label, symbol, source, pred_confidence
        FROM raw_predictions
        WHERE pred_confidence >= ?
          AND LENGTH(text) > 20  -- Filter out very short texts
        ORDER BY pred_confidence DESC
        LIMIT ?
    """, (min_confidence, limit))
    
    examples = []
    for row in cursor.fetchall():
        examples.append(TrainingExample(
            text=row["text"],
            label=row["pred_label"],
            symbol=row["symbol"],
            source=row["source"],
            confidence=row["pred_confidence"],
            label_strategy="pseudo"
        ))
    
    conn.close()
    logger.info(f"Fetched {len(examples)} examples with pseudo-labels (confidence >= {min_confidence})")
    return examples


def assign_label_from_price_change(price_change_pct: float) -> str:
    """Assign sentiment label based on price movement."""
    if price_change_pct > 1.5:
        return "positive"
    elif price_change_pct < -1.5:
        return "negative"
    else:
        return "neutral"


async def fetch_prices_batch(symbols: List[str], timestamp: datetime, http_client: httpx.AsyncClient) -> Dict[str, float]:
    """Fetch prices for multiple symbols at once using CoinGecko."""
    coin_ids = {
        "BTCUSDT": "bitcoin",
        "ETHUSDT": "ethereum", 
        "SOLUSDT": "solana",
        "BNBUSDT": "binancecoin",
    }
    
    # Get unique coin IDs needed
    needed_coins = set()
    for sym in symbols:
        if sym in coin_ids:
            needed_coins.add(coin_ids[sym])
    
    if not needed_coins:
        return {}
    
    prices = {}
    
    for coin_id in needed_coins:
        try:
            from_ts = int((timestamp - timedelta(hours=1)).timestamp())
            to_ts = int((timestamp + timedelta(hours=6)).timestamp())
            
            url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart/range"
            params = {"vs_currency": "usd", "from": from_ts, "to": to_ts}
            headers = {}
            if COINGECKO_API_KEY:
                headers["x_cg_demo_api_key"] = COINGECKO_API_KEY
            
            response = await http_client.get(url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 429:
                logger.warning("Rate limited by CoinGecko, waiting 60s...")
                await asyncio.sleep(60)
                continue
            
            response.raise_for_status()
            data = response.json()
            prices_data = data.get("prices", [])
            
            if len(prices_data) >= 2:
                # Find price at prediction time and 4h later
                pred_ts = int(timestamp.timestamp() * 1000)
                
                price_at_pred = None
                price_4h = None
                min_diff_pred = float('inf')
                min_diff_4h = float('inf')
                target_4h_ts = pred_ts + (4 * 60 * 60 * 1000)
                
                for price_ts, price in prices_data:
                    diff_pred = abs(price_ts - pred_ts)
                    if diff_pred < min_diff_pred:
                        min_diff_pred = diff_pred
                        price_at_pred = price
                    
                    diff_4h = abs(price_ts - target_4h_ts)
                    if diff_4h < min_diff_4h:
                        min_diff_4h = diff_4h
                        price_4h = price
                
                if price_at_pred and price_4h:
                    change = ((price_4h - price_at_pred) / price_at_pred) * 100
                    # Map back to symbol
                    for sym, cid in coin_ids.items():
                        if cid == coin_id:
                            prices[sym] = change
                            break
            
            # Rate limiting between coins
            await asyncio.sleep(12 if not COINGECKO_API_KEY else 1)
            
        except Exception as e:
            logger.error(f"Failed to fetch price for {coin_id}: {e}")
            await asyncio.sleep(5)
    
    return prices


async def fetch_predictions_price_labels(limit: int = 200) -> List[TrainingExample]:
    """
    Create training examples by fetching price data and labeling based on price movement.
    This is slower but provides stronger supervision.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get predictions grouped by timestamp (to minimize API calls)
    cursor.execute("""
        SELECT text, pred_label, symbol, source, pred_confidence, fetched_at
        FROM raw_predictions
        WHERE LENGTH(text) > 20
        ORDER BY fetched_at DESC
        LIMIT ?
    """, (limit,))
    
    rows = cursor.fetchall()
    conn.close()
    
    # Group by timestamp to batch API calls
    timestamp_groups = {}
    for row in rows:
        ts = row["fetched_at"]
        if ts not in timestamp_groups:
            timestamp_groups[ts] = []
        timestamp_groups[ts].append(row)
    
    logger.info(f"Processing {len(rows)} predictions across {len(timestamp_groups)} timestamps")
    
    examples = []
    
    async with httpx.AsyncClient() as http_client:
        for ts, group_rows in timestamp_groups.items():
            timestamp = datetime.fromtimestamp(ts, tz=timezone.utc)
            symbols = list(set(r["symbol"] for r in group_rows))
            
            # Fetch prices for all symbols at this timestamp
            price_changes = await fetch_prices_batch(symbols, timestamp, http_client)
            
            for row in group_rows:
                symbol = row["symbol"]
                if symbol in price_changes:
                    label = assign_label_from_price_change(price_changes[symbol])
                    examples.append(TrainingExample(
                        text=row["text"],
                        label=label,
                        symbol=symbol,
                        source=row["source"],
                        confidence=abs(price_changes[symbol]),
                        label_strategy="price"
                    ))
            
            logger.info(f"Processed {len(group_rows)} predictions for timestamp {timestamp}")
    
    logger.info(f"Created {len(examples)} examples with price-based labels")
    return examples


def export_to_jsonl(examples: List[TrainingExample], output_path: str):
    """Export examples to JSONL format."""
    with open(output_path, 'w') as f:
        for ex in examples:
            record = {
                "text": ex.text,
                "label": ex.label,
                "symbol": ex.symbol,
                "source": ex.source,
                "confidence": ex.confidence,
                "label_strategy": ex.label_strategy
            }
            f.write(json.dumps(record) + '\n')
    
    logger.info(f"Exported {len(examples)} examples to {output_path}")


def save_to_database(examples: List[TrainingExample]):
    """Save training examples to SQLite database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create training_data table if not exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS training_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            label TEXT NOT NULL,
            symbol TEXT NOT NULL,
            source TEXT,
            confidence REAL,
            label_strategy TEXT,
            created_at INTEGER NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_training_label ON training_data(label)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_training_symbol ON training_data(symbol)")
    
    created_at = int(datetime.now(timezone.utc).timestamp())
    
    for ex in examples:
        cursor.execute("""
            INSERT INTO training_data (text, label, symbol, source, confidence, label_strategy, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (ex.text, ex.label, ex.symbol, ex.source, ex.confidence, ex.label_strategy, created_at))
    
    conn.commit()
    conn.close()
    logger.info(f"Saved {len(examples)} examples to database")


def print_stats(examples: List[TrainingExample]):
    """Print statistics about the training data."""
    print("\n" + "="*60)
    print("TRAINING DATA STATISTICS")
    print("="*60)
    print(f"Total examples: {len(examples)}")
    
    # By label
    label_counts = {}
    for ex in examples:
        label_counts[ex.label] = label_counts.get(ex.label, 0) + 1
    print(f"\nBy label:")
    for label, count in sorted(label_counts.items()):
        pct = count / len(examples) * 100
        print(f"  {label:>10}: {count:>4} ({pct:>5.1f}%)")
    
    # By strategy
    strategy_counts = {}
    for ex in examples:
        strategy_counts[ex.label_strategy] = strategy_counts.get(ex.label_strategy, 0) + 1
    print(f"\nBy labeling strategy:")
    for strategy, count in sorted(strategy_counts.items()):
        pct = count / len(examples) * 100
        print(f"  {strategy:>10}: {count:>4} ({pct:>5.1f}%)")
    
    # By symbol
    symbol_counts = {}
    for ex in examples:
        symbol_counts[ex.symbol] = symbol_counts.get(ex.symbol, 0) + 1
    print(f"\nBy symbol:")
    for symbol, count in sorted(symbol_counts.items(), key=lambda x: -x[1]):
        pct = count / len(examples) * 100
        print(f"  {symbol:>10}: {count:>4} ({pct:>5.1f}%)")
    
    print("="*60)


async def main():
    parser = argparse.ArgumentParser(description="Create training data for FinBERT fine-tuning")
    parser.add_argument("--strategy", choices=["pseudo", "price", "both"], default="pseudo",
                       help="Labeling strategy: pseudo (fast), price (slow), or both")
    parser.add_argument("--limit", type=int, default=1000,
                       help="Maximum number of examples to generate")
    parser.add_argument("--min-confidence", type=float, default=0.7,
                       help="Minimum confidence for pseudo-labels")
    parser.add_argument("--output", type=str, default="training_data.jsonl",
                       help="Output JSONL file path")
    parser.add_argument("--no-db", action="store_true",
                       help="Don't save to database, only export to JSONL")
    
    args = parser.parse_args()
    
    examples = []
    
    if args.strategy in ["pseudo", "both"]:
        pseudo_examples = fetch_predictions_pseudo_labels(
            min_confidence=args.min_confidence,
            limit=args.limit
        )
        examples.extend(pseudo_examples)
    
    if args.strategy in ["price", "both"]:
        price_limit = args.limit if args.strategy == "price" else args.limit // 2
        price_examples = await fetch_predictions_price_labels(limit=price_limit)
        examples.extend(price_examples)
    
    if not examples:
        logger.error("No examples generated!")
        sys.exit(1)
    
    # Deduplicate by text
    seen_texts = set()
    unique_examples = []
    for ex in examples:
        if ex.text not in seen_texts:
            seen_texts.add(ex.text)
            unique_examples.append(ex)
    
    logger.info(f"Deduplicated: {len(examples)} -> {len(unique_examples)} unique examples")
    examples = unique_examples[:args.limit]
    
    # Print stats
    print_stats(examples)
    
    # Export to JSONL
    export_to_jsonl(examples, args.output)
    
    # Save to database
    if not args.no_db:
        save_to_database(examples)
    
    logger.info(f"Done! Created {len(examples)} training examples.")


if __name__ == "__main__":
    asyncio.run(main())
