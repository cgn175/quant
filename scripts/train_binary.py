#!/usr/bin/env python3
"""Train binary XGBoost model (UP vs DOWN only, no NEUTRAL).

Strategy:
- Use 2 years of 5m data
- Train on year 1 (Feb 2024 - Feb 2025)
- Test on year 2 (Feb 2025 - Feb 2026) = true out-of-sample
- Binary classification: only keep bars where |return| > threshold
- This forces the model to learn directional signals, not predict NEUTRAL
"""

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import optuna
import pandas as pd
import xgboost as xgb
from build_features import FEATURE_COLUMNS, add_features
from sklearn.metrics import accuracy_score, classification_report, f1_score


def prepare_binary_dataset(
    data_dir: Path,
    symbol: str,
    threshold: float = 0.002,
    timeframe: str = "5m",
) -> tuple[pd.DataFrame, pd.Series]:
    """Load data and prepare binary (UP=1, DOWN=0) dataset.
    Bars with |return| < threshold (NEUTRAL) are dropped.
    """
    pattern = f"{symbol.replace('/', '_')}_*.parquet"
    files = list(data_dir.glob(pattern))

    if not files:
        raise ValueError(f"No data found for {symbol} in {data_dir}")

    dfs = []
    for f in files:
        print(f"Loading {f}")
        df = pd.read_parquet(f)
        df = add_features(df, timeframe=timeframe)
        dfs.append(df)

    df = pd.concat(dfs, axis=0).sort_index()
    df = df[~df.index.duplicated(keep="last")]

    # Compute future return and label
    df["future_ret"] = df["close"].shift(-1) / df["close"] - 1

    # Binary labels: UP=1, DOWN=0, drop NEUTRAL
    df["label"] = np.nan
    df.loc[df["future_ret"] > threshold, "label"] = 1  # UP
    df.loc[df["future_ret"] < -threshold, "label"] = 0  # DOWN
    # Rows with |future_ret| <= threshold are left as NaN and dropped

    # Drop NaN (NEUTRAL bars + feature warm-up NaNs + last bar)
    df = df.dropna(subset=FEATURE_COLUMNS + ["label"])

    X = df[FEATURE_COLUMNS]
    y = df["label"].astype(int)

    print(f"\nDataset: {len(X)} bars (NEUTRAL bars removed)")
    print(f"UP:   {(y == 1).sum()} ({(y == 1).mean() * 100:.1f}%)")
    print(f"DOWN: {(y == 0).sum()} ({(y == 0).mean() * 100:.1f}%)")
    print(f"Date range: {df.index[0]} to {df.index[-1]}")

    return X, y


def train_binary_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    n_trials: int = 50,
) -> tuple[xgb.XGBClassifier, dict]:
    """Train binary XGBoost with Optuna tuning."""

    print(
        f"\nTrain size: {len(X_train)} (UP: {(y_train == 1).sum()}, DOWN: {(y_train == 0).sum()})"
    )
    print(
        f"Val size:   {len(X_val)} (UP: {(y_val == 1).sum()}, DOWN: {(y_val == 0).sum()})"
    )

    def objective(trial):
        params = {
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "tree_method": "hist",
            "max_depth": trial.suggest_int("max_depth", 3, 8),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 100, 500),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
            "gamma": trial.suggest_float("gamma", 0.0, 5.0),
            "scale_pos_weight": trial.suggest_float("scale_pos_weight", 0.8, 1.2),
            "random_state": 42,
        }

        model = xgb.XGBClassifier(**params)
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

        y_pred = model.predict(X_val)
        return f1_score(y_val, y_pred, average="binary")

    print(f"\nRunning Optuna optimization ({n_trials} trials)...")
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    print(f"\nBest trial F1: {study.best_trial.value:.4f}")
    print(f"Best params: {study.best_trial.params}")

    best_params = {
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "tree_method": "hist",
        "random_state": 42,
        **study.best_trial.params,
    }

    # Train final model
    print("\nTraining final model...")
    model = xgb.XGBClassifier(**best_params)
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=True)

    # Evaluate
    y_pred = model.predict(X_val)
    y_proba = model.predict_proba(X_val)

    print("\n" + "=" * 60)
    print("VALIDATION RESULTS (Out-of-Sample)")
    print("=" * 60)
    print(f"Accuracy: {accuracy_score(y_val, y_pred):.4f}")
    print(f"F1 (binary): {f1_score(y_val, y_pred, average='binary'):.4f}")
    print(f"\nClassification Report:")
    print(classification_report(y_val, y_pred, target_names=["DOWN", "UP"]))

    # Analyze prediction confidence
    proba_up = y_proba[:, 1]
    print(f"Prediction stats:")
    print(f"  Mean P(UP):  {proba_up.mean():.4f}")
    print(f"  Std  P(UP):  {proba_up.std():.4f}")
    print(
        f"  High conf (>0.6): {(proba_up > 0.6).sum()} ({(proba_up > 0.6).mean() * 100:.1f}%)"
    )
    print(
        f"  High conf (>0.7): {(proba_up > 0.7).sum()} ({(proba_up > 0.7).mean() * 100:.1f}%)"
    )

    # Win rate at different confidence thresholds
    print(f"\nWin rate by confidence threshold (on val data):")
    for thresh in [0.50, 0.55, 0.60, 0.65, 0.70]:
        mask = proba_up > thresh
        if mask.sum() > 0:
            wr = (y_val[mask] == 1).mean()
            print(
                f"  P(UP) > {thresh:.2f}: {mask.sum():5d} trades, WR = {wr * 100:.1f}%"
            )

    for thresh in [0.50, 0.45, 0.40, 0.35, 0.30]:
        mask = proba_up < thresh
        if mask.sum() > 0:
            wr_short = (y_val[mask] == 0).mean()
            print(
                f"  P(UP) < {thresh:.2f}: {mask.sum():5d} shorts, WR = {wr_short * 100:.1f}%"
            )

    metrics = {
        "train_accuracy": float(accuracy_score(y_train, model.predict(X_train))),
        "val_accuracy": float(accuracy_score(y_val, y_pred)),
        "train_f1": float(f1_score(y_train, model.predict(X_train), average="binary")),
        "val_f1": float(f1_score(y_val, y_pred, average="binary")),
        "train_size": len(X_train),
        "val_size": len(X_val),
        "best_params": best_params,
        "model_type": "binary",
        "n_features": len(FEATURE_COLUMNS),
    }

    return model, metrics


def save_model(model, output_dir: Path, metrics: dict, symbol: str, threshold: float):
    """Save model, metrics, and feature list."""
    output_dir.mkdir(parents=True, exist_ok=True)

    model.save_model(output_dir / "xgboost_model.json")
    joblib.dump(model, output_dir / "xgboost_model.joblib")

    metrics["symbol"] = symbol
    metrics["threshold"] = threshold
    with open(output_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    with open(output_dir / "features.json", "w") as f:
        json.dump(FEATURE_COLUMNS, f, indent=2)

    print(f"\nModel saved to {output_dir}/")


def main():
    parser = argparse.ArgumentParser(description="Train binary XGBoost (UP vs DOWN)")
    parser.add_argument("--data-dir", type=str, default="data_5m_2y")
    parser.add_argument("--symbol", type=str, default="BTC/USDT")
    parser.add_argument(
        "--threshold", type=float, default=0.002, help="Return threshold (0.002 = 0.2%)"
    )
    parser.add_argument("--timeframe", type=str, default="5m")
    parser.add_argument("--n-trials", type=int, default=50)
    parser.add_argument("--output", type=str, default="models_v2")
    parser.add_argument(
        "--split-date",
        type=str,
        default="2025-02-08",
        help="Train/test split date (train < date, test >= date)",
    )

    args = parser.parse_args()

    # Load and prepare data
    X, y = prepare_binary_dataset(
        Path(args.data_dir), args.symbol, args.threshold, args.timeframe
    )

    # Split by date: year 1 = train, year 2 = test (true OOS)
    split_date = pd.Timestamp(args.split_date)
    train_mask = X.index < split_date
    val_mask = X.index >= split_date

    X_train, y_train = X[train_mask], y[train_mask]
    X_val, y_val = X[val_mask], y[val_mask]

    print(f"\nTime-based split at {args.split_date}:")
    print(f"  Train: {X_train.index[0]} to {X_train.index[-1]} ({len(X_train)} bars)")
    print(f"  Val:   {X_val.index[0]} to {X_val.index[-1]} ({len(X_val)} bars)")

    # Train
    model, metrics = train_binary_model(X_train, y_train, X_val, y_val, args.n_trials)

    # Save
    sym_short = args.symbol.replace("/", "").lower()
    output_dir = Path(args.output) / f"{sym_short}_5m_binary"
    save_model(model, output_dir, metrics, args.symbol, args.threshold)


if __name__ == "__main__":
    main()
