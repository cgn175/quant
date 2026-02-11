#!/usr/bin/env python3
"""
Download FinBERT models to a local directory for offline use.

Downloads both models to sentiment/models_local/ so they can be
loaded without internet access.

Usage:
    python3 sentiment/download_models.py
"""

from huggingface_hub import snapshot_download
import sys
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent / "models_local"

MODELS = {
    "ProsusAI/finbert": "prosus-finbert",
    "burakutf/finetuned-finbert-crypto": "crypto-finbert",
}


def download_model(model_name: str, local_name: str) -> bool:
    save_dir = MODELS_DIR / local_name
    print(f"\n📦 Downloading {model_name} → {save_dir}")

    try:
        snapshot_download(
            repo_id=model_name,
            local_dir=str(save_dir),
            ignore_patterns=["*.h5", "*.ot", "flax_*"],
        )
        print(f"   ✅ Saved to {save_dir}")
        return True

    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False


def main():
    print("=" * 60)
    print("FinBERT Model Download Script")
    print("=" * 60)
    print(f"\nTarget directory: {MODELS_DIR}")

    for model_name, local_name in MODELS.items():
        save_dir = MODELS_DIR / local_name
        if save_dir.exists():
            print(f"  ✓ {local_name} already exists")
        else:
            print(f"  ✗ {local_name} not found")

    success = 0
    for model_name, local_name in MODELS.items():
        if download_model(model_name, local_name):
            success += 1

    print(f"\n{'=' * 60}")
    print(f"Done: {success}/{len(MODELS)} models downloaded")
    print("=" * 60)

    if success == len(MODELS):
        print("\n✅ You can now use FinBERT offline:")
        print("   from models.finbert_offline import get_analyzer")
        print("   analyzer = get_analyzer(offline=True)")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
