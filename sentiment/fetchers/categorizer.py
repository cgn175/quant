"""
Post categorization module for symbol-specific filtering.

This module provides functions to categorize general crypto news posts
into symbol-specific posts using keyword matching and NLP techniques.
"""

import re
from typing import List, Set
from .base import Post, extract_base_token


# Symbol keyword mappings
SYMBOL_KEYWORDS = {
    "BTC": [
        "bitcoin", "btc", "$btc", "₿",
        "bitcoin price", "btc price", "bitcoin network",
        "bitcoin mining", "bitcoin halving", "bitcoin etf"
    ],
    "ETH": [
        "ethereum", "eth", "$eth", "ether", "Ξ",
        "ethereum price", "eth price", "ethereum network",
        "eth 2.0", "ethereum 2.0", "ethereum merge", "ethereum staking",
        "vitalik", "vitalik buterin"
    ],
    "SOL": [
        "solana", "sol", "$sol", "◎",
        "solana price", "sol price", "solana network",
        "solana labs", "anatoly", "anatoly yakovenko"
    ],
    "BNB": [
        "binance", "bnb", "$bnb", "binance coin",
        "bnb price", "binance price", "binance chain",
        "bsc", "binance smart chain", "bnb chain"
    ],
}

# General crypto keywords (not symbol-specific)
GENERAL_CRYPTO_KEYWORDS = [
    "cryptocurrency", "crypto market", "blockchain",
    "digital assets", "crypto", "defi", "nft",
    "web3", "altcoin", "stablecoin", "cbdc",
    "crypto regulation", "crypto adoption",
    "crypto exchange", "crypto trading",
    "institutional crypto", "crypto etf",
    "crypto mining", "crypto wallet"
]


def normalize_text(text: str) -> str:
    """Normalize text for keyword matching."""
    return text.lower().strip()


def extract_symbols_from_post(post: Post, target_symbols: List[str] = None) -> List[str]:
    """
    Extract all relevant trading symbols from a post.
    
    Args:
        post: Post object with text content
        target_symbols: List of trading symbols to check (e.g., ["BTCUSDT", "ETHUSDT"])
                       If None, checks all known symbols
    
    Returns:
        List of trading symbols this post is relevant to (e.g., ["BTCUSDT", "ETHUSDT"])
    """
    text_lower = normalize_text(post.text)
    matched_symbols = []
    
    # If target_symbols not specified, check all known symbols
    if target_symbols is None:
        target_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    
    for symbol in target_symbols:
        base_token = extract_base_token(symbol)
        keywords = SYMBOL_KEYWORDS.get(base_token, [base_token.lower()])
        
        # Check if any keyword matches
        if any(keyword in text_lower for keyword in keywords):
            matched_symbols.append(symbol)
    
    return matched_symbols


def is_general_market_post(post: Post) -> bool:
    """
    Check if a post is about general crypto market (not symbol-specific).
    
    Args:
        post: Post object with text content
    
    Returns:
        True if post is about general market trends, False otherwise
    """
    text_lower = normalize_text(post.text)
    
    # Check for general crypto keywords
    has_general_keywords = any(
        keyword in text_lower for keyword in GENERAL_CRYPTO_KEYWORDS
    )
    
    # Check if it mentions specific symbols
    symbols = extract_symbols_from_post(post)
    
    # If it has general keywords but no specific symbols, it's general market news
    # If it mentions 3+ symbols, it's also general market news
    return has_general_keywords and (not symbols or len(symbols) >= 3)


def categorize_posts(
    posts: List[Post],
    target_symbols: List[str] = None
) -> dict[str, List[Post]]:
    """
    Categorize a list of general posts into symbol-specific groups.
    
    Args:
        posts: List of Post objects from general fetchers
        target_symbols: List of trading symbols to categorize into
                       (e.g., ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"])
    
    Returns:
        Dictionary mapping symbols to their relevant posts.
        Includes special key "MARKET" for general market news.
        
    Example:
        {
            "BTCUSDT": [Post(...), Post(...)],
            "ETHUSDT": [Post(...)],
            "MARKET": [Post(...), Post(...)]
        }
    """
    if target_symbols is None:
        target_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    
    categorized = {symbol: [] for symbol in target_symbols}
    categorized["MARKET"] = []
    
    for post in posts:
        # Check if it's general market news
        if is_general_market_post(post):
            market_post = Post(
                text=post.text,
                source=post.source,
                symbol="MARKET",
                timestamp=post.timestamp,
                score=post.score
            )
            categorized["MARKET"].append(market_post)
        
        # Extract relevant symbols
        relevant_symbols = extract_symbols_from_post(post, target_symbols)
        
        # Add post to each relevant symbol category
        for symbol in relevant_symbols:
            symbol_post = Post(
                text=post.text,
                source=post.source,
                symbol=symbol,
                timestamp=post.timestamp,
                score=post.score
            )
            categorized[symbol].append(symbol_post)
    
    return categorized


def deduplicate_posts(posts: List[Post]) -> List[Post]:
    """
    Remove duplicate posts based on text similarity.
    
    Args:
        posts: List of Post objects
    
    Returns:
        Deduplicated list of posts
    """
    seen_texts = set()
    unique_posts = []
    
    for post in posts:
        # Use first 100 chars as deduplication key
        key = normalize_text(post.text[:100])
        
        if key not in seen_texts:
            seen_texts.add(key)
            unique_posts.append(post)
    
    return unique_posts
