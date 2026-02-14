# FinBERT Fine-tuning Summary (quant-a3n.4)

## Overview
This document summarizes the work done for fine-tuning FinBERT on accumulated crypto sentiment data.

## What Was Accomplished

### 1. Data Exploration
- **Raw predictions in DB**: 1,814 records with FinBERT predictions
- **Data span**: Feb 10-12, 2026 (51 hours of collected data)
- **Sources**: CoinGecko (1,582), NewsAPI (145), Telegram channels (82)
- **Symbols covered**: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT

### 2. Created Scripts

#### `create_training_data.py`
Creates labeled training data from accumulated predictions:
- **Pseudo-labeling strategy** (fast): Uses high-confidence FinBERT predictions as labels
- **Price-based labeling** (slow): Fetches historical prices and labels based on 4h price movement
- Features:
  - Deduplication by text content
  - Configurable confidence threshold
  - Export to JSONL and SQLite
  - Statistics reporting

Usage:
```bash
# Fast pseudo-labeling (uses existing predictions)
python3 create_training_data.py --strategy pseudo --limit 500

# Price-based labeling (requires API calls)
python3 create_training_data.py --strategy price --limit 200
```

#### `finetune_finbert.py`
Fine-tunes ProsusAI/finbert on custom crypto sentiment data:
- Features:
  - Loads from JSONL or SQLite database
  - Stratified train/val/test split (70/10/20)
  - Early stopping to prevent overfitting
  - Evaluation metrics: accuracy, precision, recall, F1 per class
  - Benchmarking against baseline ProsusAI/finbert
  - Saves training summary with hyperparameters

Usage:
```bash
# Fine-tune with generated data
python3 finetune_finbert.py --data training_data.jsonl --output models/custom-crypto-finbert --epochs 5

# With benchmark against baseline
python3 finetune_finbert.py --data training_data.jsonl --output models/custom-crypto-finbert --benchmark
```

#### `label_training_data.py`
Alternative script for price-based labeling with CoinGecko API:
- Fetches historical price data for each prediction timestamp
- Labels based on 4h price movement (>1.5% = positive, <-1.5% = negative)
- Saves market snapshots for future reference

### 3. Generated Training Data

Using pseudo-labeling (confidence >= 0.7):
```
Total examples: 266 (after deduplication)

Label distribution:
  negative:   60 (22.6%)
  neutral:   181 (68.0%)
  positive:   25 ( 9.4%)

By symbol:
  ETHUSDT: 177 (66.5%)
  BTCUSDT:  70 (26.3%)
  SOLUSDT:  15 ( 5.6%)
  BNBUSDT:   4 ( 1.5%)
```

Dataset splits:
- Train: 185 examples
- Validation: 27 examples
- Test: 54 examples

### 4. Fine-tuning Configuration

```python
BASE_MODEL = "ProsusAI/finbert"
MAX_LENGTH = 128
BATCH_SIZE = 4-16 (configurable)
LEARNING_RATE = 2e-5
NUM_EPOCHS = 3-10 (configurable)
WARMUP_RATIO = 0.1
WEIGHT_DECAY = 0.01
```

### 5. Current Limitations

1. **Small dataset**: Only 266 labeled examples
   - Recommendation: Continue accumulating data for 2-4 weeks for better results
   
2. **Label imbalance**: 68% neutral labels
   - The crypto market was relatively flat during data collection
   - Consider active learning to find more positive/negative examples

3. **No price-based labels yet**: CoinGecko API rate limits prevented fetching historical prices
   - With a paid API key, can generate stronger supervision labels

4. **Data quality**: Pseudo-labels are model predictions, not ground truth
   - Risk of reinforcing existing model biases
   - Price-based labels would provide independent signal

## Next Steps for Better Results

1. **Accumulate more data**: Run sentiment service for 2-4 weeks to get 2,000+ examples
2. **Get CoinGecko API key**: For price-based labeling without rate limits
3. **Manual annotation**: Label a small subset (100-200) for gold-standard evaluation
4. **Active learning**: Use model uncertainty to select which examples to label
5. **Data augmentation**: Paraphrase crypto texts to increase diversity

## Files Created

```
sentiment/
├── create_training_data.py      # Training data generation
├── finetune_finbert.py          # Fine-tuning script
├── label_training_data.py       # Price-based labeling
├── training_data.jsonl          # Generated training data (266 examples)
└── FINETUNING_SUMMARY.md        # This document
```

## How to Reproduce

1. Generate training data:
```bash
cd sentiment
python3 create_training_data.py --strategy pseudo --limit 1000 --output training_data.jsonl
```

2. Run fine-tuning:
```bash
python3 finetune_finbert.py --data training_data.jsonl --output models/custom-crypto-finbert --epochs 5 --benchmark
```

3. Use the fine-tuned model:
```python
from transformers import AutoTokenizer, AutoModelForSequenceClassification

tokenizer = AutoTokenizer.from_pretrained("sentiment/models/custom-crypto-finbert")
model = AutoModelForSequenceClassification.from_pretrained("sentiment/models/custom-crypto-finbert")
```

## Conclusion

The fine-tuning pipeline is fully set up and functional. The main blocker for better results is the amount of training data. With the current 266 examples, the model may overfit. Recommendation is to:
1. Keep the sentiment service running to accumulate more data
2. Re-run fine-tuning in 2-4 weeks when 2,000+ examples are available
3. Consider the ensemble approach (ProsusAI + Crypto FinBERT) currently in production as the best solution until more data is collected
