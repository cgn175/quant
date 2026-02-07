#!/usr/bin/env python3
"""Train XGBoost model for crypto price direction prediction."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, classification_report, f1_score
import optuna
import joblib

from build_features import FEATURE_COLUMNS, prepare_dataset


def time_series_split(X: pd.DataFrame, y: pd.Series, train_ratio: float = 0.8):
    """Split data by time, no shuffling."""
    split_idx = int(len(X) * train_ratio)
    
    X_train = X.iloc[:split_idx]
    y_train = y.iloc[:split_idx]
    X_val = X.iloc[split_idx:]
    y_val = y.iloc[split_idx:]
    
    return X_train, X_val, y_train, y_val


def objective(trial, X_train, y_train, X_val, y_val):
    """Optuna objective for hyperparameter tuning."""
    params = {
        "objective": "multi:softprob",
        "num_class": 3,
        "eval_metric": "mlogloss",
        "tree_method": "hist",
        "max_depth": trial.suggest_int("max_depth", 3, 10),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
        "n_estimators": trial.suggest_int("n_estimators", 100, 500),
        "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
        "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
        "random_state": 42,
    }
    
    model = xgb.XGBClassifier(**params)
    model.fit(
        X_train,
        y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )
    
    y_pred = model.predict(X_val)
    f1 = f1_score(y_val, y_pred, average="weighted")
    
    return f1


def train_model(
    X: pd.DataFrame,
    y: pd.Series,
    n_trials: int = 50,
    train_ratio: float = 0.8,
) -> tuple[xgb.XGBClassifier, dict]:
    """Train XGBoost with Optuna hyperparameter tuning."""
    
    X_train, X_val, y_train, y_val = time_series_split(X, y, train_ratio)
    
    print(f"Train size: {len(X_train)}, Val size: {len(X_val)}")
    print(f"\nRunning Optuna optimization with {n_trials} trials...")
    
    study = optuna.create_study(direction="maximize")
    study.optimize(
        lambda trial: objective(trial, X_train, y_train, X_val, y_val),
        n_trials=n_trials,
        show_progress_bar=True,
    )
    
    print(f"\nBest trial F1: {study.best_trial.value:.4f}")
    print(f"Best params: {study.best_trial.params}")
    
    best_params = {
        "objective": "multi:softprob",
        "num_class": 3,
        "eval_metric": "mlogloss",
        "tree_method": "hist",
        "random_state": 42,
        **study.best_trial.params,
    }
    
    print("\nTraining final model...")
    model = xgb.XGBClassifier(**best_params)
    model.fit(
        X_train,
        y_train,
        eval_set=[(X_val, y_val)],
        verbose=True,
    )
    
    y_pred = model.predict(X_val)
    y_proba = model.predict_proba(X_val)
    
    print("\nValidation Results:")
    print(f"Accuracy: {accuracy_score(y_val, y_pred):.4f}")
    print(f"F1 (weighted): {f1_score(y_val, y_pred, average='weighted'):.4f}")
    print("\nClassification Report:")
    print(classification_report(y_val, y_pred, target_names=["DOWN", "NEUTRAL", "UP"]))
    
    metrics = {
        "accuracy": float(accuracy_score(y_val, y_pred)),
        "f1_weighted": float(f1_score(y_val, y_pred, average="weighted")),
        "train_size": len(X_train),
        "val_size": len(X_val),
        "best_params": best_params,
    }
    
    return model, metrics


def save_model(model: xgb.XGBClassifier, output_dir: Path, metrics: dict):
    """Save model in multiple formats."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    model_path = output_dir / "xgboost_model.json"
    model.save_model(model_path)
    print(f"Saved XGBoost model to {model_path}")
    
    joblib_path = output_dir / "xgboost_model.joblib"
    joblib.dump(model, joblib_path)
    print(f"Saved joblib model to {joblib_path}")
    
    metrics_path = output_dir / "metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print(f"Saved metrics to {metrics_path}")
    
    features_path = output_dir / "features.json"
    with open(features_path, "w") as f:
        json.dump(FEATURE_COLUMNS, f, indent=2)
    print(f"Saved feature names to {features_path}")


def main():
    parser = argparse.ArgumentParser(description="Train XGBoost model")
    parser.add_argument("--data-dir", type=str, default="data", help="Data directory")
    parser.add_argument(
        "--symbols",
        type=str,
        default="BTC/USDT,ETH/USDT",
        help="Comma-separated symbols",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.0003,
        help="Return threshold for labels",
    )
    parser.add_argument("--n-trials", type=int, default=50, help="Optuna trials")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="Train ratio")
    parser.add_argument("--output", type=str, default="models", help="Output directory")
    
    args = parser.parse_args()
    
    symbols = [s.strip() for s in args.symbols.split(",")]
    X, y = prepare_dataset(Path(args.data_dir), symbols, args.threshold)
    
    model, metrics = train_model(X, y, args.n_trials, args.train_ratio)
    
    save_model(model, Path(args.output), metrics)
    print("\nTraining complete!")


if __name__ == "__main__":
    main()
