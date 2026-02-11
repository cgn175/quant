#!/usr/bin/env python3
"""Test offline FinBERT loading."""

import os
import sys

def test_offline_loading():
    print("Testing offline FinBERT loading...")
    print("-" * 60)

    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['HF_HUB_OFFLINE'] = '1'
    print("✓ Set TRANSFORMERS_OFFLINE=1, HF_HUB_OFFLINE=1")

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from models.finbert_offline import FinBERTAnalyzer

        print("\nLoading FinBERT analyzer from local directory...")
        analyzer = FinBERTAnalyzer(offline=True)
        print("✓ Analyzer loaded successfully")

        print("\nTesting inference...")
        test_texts = [
            "Bitcoin surges to new all-time high!",
            "Major exchange hacked, millions stolen",
            "SEC approves Bitcoin ETF",
        ]

        results = analyzer.analyze(test_texts)
        print("✓ Inference successful\n")

        for text, result in zip(test_texts, results):
            sentiment = max(result, key=result.get)
            print(f"  '{text}'")
            print(f"    → {sentiment.upper()} (pos={result['positive']:.2f}, neg={result['negative']:.2f}, neu={result['neutral']:.2f})")

        print("\n" + "=" * 60)
        print("✅ OFFLINE MODE WORKS!")
        print("=" * 60)
        return True

    except Exception as e:
        print(f"\n❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = test_offline_loading()
    sys.exit(0 if success else 1)
