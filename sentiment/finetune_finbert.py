#!/usr/bin/env python3
"""
Fine-tune FinBERT on crypto sentiment data.

This script fine-tunes the ProsusAI/finbert model on labeled crypto sentiment
data to create a custom crypto-specific sentiment model.

Usage:
    python3 finetune_finbert.py --data training_data.jsonl --output models/custom-crypto-finbert
    python3 finetune_finbert.py --from-db --output models/custom-crypto-finbert
"""

import os
import sys
import json
import sqlite3
import logging
import argparse
from typing import Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import torch
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, classification_report
from sklearn.model_selection import train_test_split
from datasets import Dataset, DatasetDict
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    TrainingArguments,
    Trainer,
    EarlyStoppingCallback,
    DataCollatorWithPadding,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Label mapping (ProsusAI/finbert uses: 0=positive, 1=negative, 2=neutral)
LABEL_MAP = {"positive": 0, "negative": 1, "neutral": 2}
ID2LABEL = {0: "positive", 1: "negative", 2: "neutral"}

# Model configuration
BASE_MODEL = "ProsusAI/finbert"
MAX_LENGTH = 128  # Shorter for crypto news/social posts
BATCH_SIZE = 16
LEARNING_RATE = 2e-5
NUM_EPOCHS = 5
WARMUP_RATIO = 0.1
WEIGHT_DECAY = 0.01


def load_data_from_jsonl(path: str) -> List[Dict]:
    """Load training data from JSONL file."""
    examples = []
    with open(path, 'r') as f:
        for line in f:
            examples.append(json.loads(line))
    logger.info(f"Loaded {len(examples)} examples from {path}")
    return examples


def load_data_from_db(db_path: str = "sentiment.db") -> List[Dict]:
    """Load training data from SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT text, label, symbol, price_change_pct, source
        FROM training_data
        ORDER BY timestamp DESC
    """)
    
    rows = cursor.fetchall()
    conn.close()
    
    examples = []
    for text, label, symbol, price_change, source in rows:
        examples.append({
            "text": text,
            "label": label,
            "symbol": symbol,
            "price_change_pct": price_change,
            "source": source
        })
    
    logger.info(f"Loaded {len(examples)} examples from database")
    return examples


def prepare_dataset(examples: List[Dict], test_size: float = 0.2, val_size: float = 0.1) -> DatasetDict:
    """
    Prepare HuggingFace dataset from examples.
    
    Splits data into train/val/test with stratification by label.
    """
    texts = [ex["text"] for ex in examples]
    labels = [LABEL_MAP[ex["label"]] for ex in examples]
    
    # First split: separate test set
    train_val_texts, test_texts, train_val_labels, test_labels = train_test_split(
        texts, labels, test_size=test_size, random_state=42, stratify=labels
    )
    
    # Second split: separate val from train
    val_ratio = val_size / (1 - test_size)
    train_texts, val_texts, train_labels, val_labels = train_test_split(
        train_val_texts, train_val_labels, test_size=val_ratio, random_state=42, 
        stratify=train_val_labels
    )
    
    # Create datasets
    train_ds = Dataset.from_dict({"text": train_texts, "label": train_labels})
    val_ds = Dataset.from_dict({"text": val_texts, "label": val_labels})
    test_ds = Dataset.from_dict({"text": test_texts, "label": test_labels})
    
    dataset = DatasetDict({
        "train": train_ds,
        "validation": val_ds,
        "test": test_ds
    })
    
    logger.info(f"Dataset splits:")
    logger.info(f"  Train: {len(train_ds)} examples")
    logger.info(f"  Validation: {len(val_ds)} examples")
    logger.info(f"  Test: {len(test_ds)} examples")
    
    # Label distribution
    for split_name, split_ds in dataset.items():
        label_counts = {}
        for label in split_ds["label"]:
            label_counts[ID2LABEL[label]] = label_counts.get(ID2LABEL[label], 0) + 1
        logger.info(f"  {split_name} labels: {label_counts}")
    
    return dataset


def tokenize_dataset(dataset: DatasetDict, tokenizer) -> DatasetDict:
    """Tokenize all splits of the dataset."""
    def tokenize_function(examples):
        return tokenizer(
            examples["text"],
            padding=False,  # Will be padded by data collator
            truncation=True,
            max_length=MAX_LENGTH,
        )
    
    tokenized = dataset.map(tokenize_function, batched=True)
    return tokenized


def compute_metrics(eval_pred) -> Dict:
    """Compute metrics for evaluation."""
    predictions, labels = eval_pred
    predictions = np.argmax(predictions, axis=1)
    
    accuracy = accuracy_score(labels, predictions)
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels, predictions, average='weighted', zero_division=0
    )
    
    # Per-class metrics
    class_report = classification_report(
        labels, predictions, 
        target_names=["positive", "negative", "neutral"],
        output_dict=True,
        zero_division=0
    )
    
    metrics = {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }
    
    # Add per-class F1
    for label_name in ["positive", "negative", "neutral"]:
        metrics[f"f1_{label_name}"] = class_report[label_name]["f1-score"]
    
    return metrics


def fine_tune_finbert(
    dataset: DatasetDict,
    output_dir: str,
    num_epochs: int = NUM_EPOCHS,
    batch_size: int = BATCH_SIZE,
    learning_rate: float = LEARNING_RATE,
):
    """
    Fine-tune FinBERT on the prepared dataset.
    """
    logger.info(f"Loading base model: {BASE_MODEL}")
    
    # Load tokenizer and model
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL,
        num_labels=3,
        id2label=ID2LABEL,
        label2id=LABEL_MAP,
    )
    
    # Tokenize dataset
    logger.info("Tokenizing dataset...")
    tokenized_dataset = tokenize_dataset(dataset, tokenizer)
    
    # Data collator for dynamic padding
    data_collator = DataCollatorWithPadding(tokenizer=tokenizer)
    
    # Calculate training steps
    num_train_samples = len(tokenized_dataset["train"])
    steps_per_epoch = num_train_samples // batch_size
    total_steps = steps_per_epoch * num_epochs
    warmup_steps = int(total_steps * WARMUP_RATIO)
    eval_steps = max(steps_per_epoch // 2, 10)  # Eval twice per epoch
    
    logger.info(f"Training configuration:")
    logger.info(f"  Epochs: {num_epochs}")
    logger.info(f"  Batch size: {batch_size}")
    logger.info(f"  Learning rate: {learning_rate}")
    logger.info(f"  Total steps: {total_steps}")
    logger.info(f"  Warmup steps: {warmup_steps}")
    logger.info(f"  Eval steps: {eval_steps}")
    
    # Training arguments
    training_args = TrainingArguments(
        output_dir=output_dir,
        overwrite_output_dir=True,
        num_train_epochs=num_epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size * 2,
        learning_rate=learning_rate,
        weight_decay=WEIGHT_DECAY,
        warmup_steps=warmup_steps,
        eval_strategy="steps",
        eval_steps=eval_steps,
        save_strategy="steps",
        save_steps=eval_steps,
        save_total_limit=3,
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        greater_is_better=True,
        logging_steps=eval_steps // 2,
        logging_dir=f"{output_dir}/logs",
        report_to=["none"],  # Disable wandb/tensorboard for simplicity
        seed=42,
    )
    
    # Initialize trainer
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_dataset["train"],
        eval_dataset=tokenized_dataset["validation"],
        tokenizer=tokenizer,
        data_collator=data_collator,
        compute_metrics=compute_metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=3)],
    )
    
    # Train
    logger.info("Starting training...")
    train_result = trainer.train()
    
    logger.info(f"Training complete!")
    logger.info(f"  Final train loss: {train_result.training_loss:.4f}")
    
    # Evaluate on test set
    logger.info("Evaluating on test set...")
    test_results = trainer.evaluate(tokenized_dataset["test"])
    
    logger.info("Test set results:")
    for key, value in test_results.items():
        if isinstance(value, float):
            logger.info(f"  {key}: {value:.4f}")
    
    # Save model
    logger.info(f"Saving model to {output_dir}")
    trainer.save_model(output_dir)
    tokenizer.save_pretrained(output_dir)
    
    # Save training summary
    summary = {
        "base_model": BASE_MODEL,
        "training_date": datetime.now().isoformat(),
        "num_train_examples": len(dataset["train"]),
        "num_val_examples": len(dataset["validation"]),
        "num_test_examples": len(dataset["test"]),
        "hyperparameters": {
            "num_epochs": num_epochs,
            "batch_size": batch_size,
            "learning_rate": learning_rate,
            "max_length": MAX_LENGTH,
            "weight_decay": WEIGHT_DECAY,
            "warmup_ratio": WARMUP_RATIO,
        },
        "test_results": {k: float(v) if isinstance(v, (int, float, np.floating)) else v 
                        for k, v in test_results.items()}
    }
    
    with open(f"{output_dir}/training_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    
    return trainer, test_results


def benchmark_vs_baseline(finetuned_model_path: str, test_examples: List[Dict]):
    """
    Benchmark the fine-tuned model against the baseline ProsusAI/finbert.
    """
    logger.info("\n" + "="*60)
    logger.info("BENCHMARK: Fine-tuned vs Baseline ProsusAI/finbert")
    logger.info("="*60)
    
    # Load models
    baseline_tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    baseline_model = AutoModelForSequenceClassification.from_pretrained(BASE_MODEL)
    baseline_model.eval()
    
    finetuned_tokenizer = AutoTokenizer.from_pretrained(finetuned_model_path)
    finetuned_model = AutoModelForSequenceClassification.from_pretrained(finetuned_model_path)
    finetuned_model.eval()
    
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    baseline_model.to(device)
    finetuned_model.to(device)
    
    texts = [ex["text"] for ex in test_examples]
    true_labels = [LABEL_MAP[ex["label"]] for ex in test_examples]
    
    def predict(model, tokenizer, texts):
        inputs = tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=MAX_LENGTH,
            return_tensors="pt"
        ).to(device)
        
        with torch.no_grad():
            outputs = model(**inputs)
            predictions = torch.argmax(outputs.logits, dim=1).cpu().numpy()
        
        return predictions
    
    # Get predictions
    baseline_preds = predict(baseline_model, baseline_tokenizer, texts)
    finetuned_preds = predict(finetuned_model, finetuned_tokenizer, texts)
    
    # Calculate metrics
    baseline_acc = accuracy_score(true_labels, baseline_preds)
    finetuned_acc = accuracy_score(true_labels, finetuned_preds)
    
    logger.info(f"\nAccuracy comparison:")
    logger.info(f"  Baseline (ProsusAI/finbert): {baseline_acc:.4f}")
    logger.info(f"  Fine-tuned:                  {finetuned_acc:.4f}")
    logger.info(f"  Improvement:                 {finetuned_acc - baseline_acc:+.4f}")
    
    # Detailed classification report
    logger.info(f"\nBaseline model report:")
    logger.info(classification_report(
        true_labels, baseline_preds, 
        target_names=["positive", "negative", "neutral"],
        zero_division=0
    ))
    
    logger.info(f"\nFine-tuned model report:")
    logger.info(classification_report(
        true_labels, finetuned_preds,
        target_names=["positive", "negative", "neutral"],
        zero_division=0
    ))
    
    return {
        "baseline_accuracy": baseline_acc,
        "finetuned_accuracy": finetuned_acc,
        "improvement": finetuned_acc - baseline_acc
    }


def main():
    parser = argparse.ArgumentParser(
        description="Fine-tune FinBERT on crypto sentiment data"
    )
    parser.add_argument(
        "--data", 
        type=str,
        help="Path to JSONL training data file"
    )
    parser.add_argument(
        "--from-db",
        action="store_true",
        help="Load training data from SQLite database"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="models/custom-crypto-finbert",
        help="Output directory for fine-tuned model"
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=NUM_EPOCHS,
        help=f"Number of training epochs (default: {NUM_EPOCHS})"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"Batch size (default: {BATCH_SIZE})"
    )
    parser.add_argument(
        "--lr",
        type=float,
        default=LEARNING_RATE,
        help=f"Learning rate (default: {LEARNING_RATE})"
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Benchmark fine-tuned model vs baseline after training"
    )
    
    args = parser.parse_args()
    
    # Load data
    if args.from_db:
        examples = load_data_from_db()
    elif args.data:
        examples = load_data_from_jsonl(args.data)
    else:
        # Try default paths
        if os.path.exists("training_data.jsonl"):
            examples = load_data_from_jsonl("training_data.jsonl")
        else:
            logger.error("No data source specified. Use --data or --from-db")
            sys.exit(1)
    
    if len(examples) < 100:
        logger.warning(f"Dataset is small ({len(examples)} examples). "
                      f"Fine-tuning may not be effective.")
        if len(examples) < 30:
            logger.error("Not enough data for fine-tuning (minimum 30 examples)")
            sys.exit(1)
    
    # Prepare dataset
    dataset = prepare_dataset(examples)
    
    # Fine-tune
    trainer, test_results = fine_tune_finbert(
        dataset=dataset,
        output_dir=args.output,
        num_epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
    )
    
    # Benchmark if requested
    if args.benchmark:
        test_examples = [
            {"text": ex["text"], "label": ex["label"]}
            for ex in examples[-len(dataset["test"]):]  # Use same test set
        ]
        benchmark_vs_baseline(args.output, test_examples)
    
    logger.info(f"\nFine-tuned model saved to: {args.output}")
    logger.info(f"Test accuracy: {test_results.get('eval_accuracy', 'N/A')}")


if __name__ == "__main__":
    main()
