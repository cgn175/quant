#!/usr/bin/env python3
"""
Update FinBERT models from HuggingFace to local cache.

Run this when you want to pull the latest model versions.
After updating, the bot will use the new versions automatically.

Usage:
    python3 sentiment/update_models.py
"""

from transformers import AutoTokenizer, AutoModelForSequenceClassification

MODELS = [
    "ProsusAI/finbert",
    "burakutf/finetuned-finbert-crypto",
]


def main():
    print("Updating FinBERT models from HuggingFace...\n")

    for model_name in MODELS:
        try:
            print(f"  Downloading {model_name}...")
            AutoTokenizer.from_pretrained(model_name, local_files_only=False)
            AutoModelForSequenceClassification.from_pretrained(model_name, local_files_only=False)
            print(f"  ✅ {model_name}\n")
        except Exception as e:
            print(f"  ❌ {model_name}: {e}\n")

    print("Done. Restart the sentiment service to use updated models.")


if __name__ == "__main__":
    main()
