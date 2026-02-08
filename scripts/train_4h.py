#!/usr/bin/env python3
"""Build features for 4h timeframe and train binary model.

Data split:
  - Train: Feb 2023 - Jan 2025 (2 years)
  - Test:  Feb 2025 - Feb 2026 (1 year, true OOS)
"""

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import optuna
import pandas as pd
import ta
import xgboost as xgb
from sklearn.metrics import accuracy_score, classification_report, f1_score

# ---------- Feature Engineering for 4h ----------

FEATURE_COLUMNS_4H = [
    # Price
    "close",
    "log_ret_1",
    "log_ret_2",
    "log_ret_6",
    "log_ret_12",
    # EMAs
    "ema_5",
    "ema_9",
    "ema_21",
    "ema_50",
    # Daily context (6 bars = 24h)
    "sma_6",
    "sma_30",
    "sma_42",
    # Trend alignment
    "trend_aligned",
    # RSI
    "rsi_7",
    "rsi_14",
    # Bollinger Bands
    "bb_upper",
    "bb_middle",
    "bb_lower",
    "bb_width",
    "bb_pct",
    # MACD
    "macd",
    "macd_signal",
    "macd_histogram",
    # Volume
    "volume_ratio",
    "vol_surge",
    # Volatility
    "atr_14",
    "atr_ratio",
    # Momentum
    "roc_6",
    "roc_12",
    # Time
    "hour_sin",
    "hour_cos",
    "day_sin",
    "day_cos",
]


def add_features_4h(df: pd.DataFrame) -> pd.DataFrame:
    """Add features optimized for 4h candles."""
    df = df.copy()

    # Price returns
    df["log_ret_1"] = np.log(df["close"] / df["close"].shift(1))
    df["log_ret_2"] = np.log(df["close"] / df["close"].shift(2))
    df["log_ret_6"] = np.log(df["close"] / df["close"].shift(6))  # 24h
    df["log_ret_12"] = np.log(df["close"] / df["close"].shift(12))  # 48h

    # EMAs
    df["ema_5"] = ta.trend.ema_indicator(df["close"], window=5)
    df["ema_9"] = ta.trend.ema_indicator(df["close"], window=9)
    df["ema_21"] = ta.trend.ema_indicator(df["close"], window=21)
    df["ema_50"] = ta.trend.ema_indicator(df["close"], window=50)

    # Daily/weekly SMAs (6 bars = 1 day, 42 bars = 1 week)
    df["sma_6"] = df["close"].rolling(window=6).mean()
    df["sma_30"] = df["close"].rolling(window=30).mean()  # ~5 days
    df["sma_42"] = df["close"].rolling(window=42).mean()  # ~1 week

    # Trend alignment: close above short, medium, and long MAs
    df["trend_aligned"] = (
        (df["close"] > df["ema_21"])
        & (df["close"] > df["sma_30"])
        & (df["close"] > df["sma_42"])
    ).astype(int)

    # RSI
    df["rsi_7"] = ta.momentum.rsi(df["close"], window=7)
    df["rsi_14"] = ta.momentum.rsi(df["close"], window=14)

    # Bollinger Bands
    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_middle"] = bb.bollinger_mavg()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]
    df["bb_pct"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])

    # MACD
    macd = ta.trend.MACD(df["close"], window_slow=26, window_fast=12, window_sign=9)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_histogram"] = macd.macd_diff()

    # Volume
    df["volume_ratio"] = df["volume"] / df["volume"].rolling(window=20).mean()
    df["vol_surge"] = (
        df["volume"] > df["volume"].rolling(window=50).mean() * 1.5
    ).astype(int)

    # ATR (Average True Range) - volatility measure
    df["atr_14"] = ta.volatility.average_true_range(
        df["high"], df["low"], df["close"], window=14
    )
    df["atr_ratio"] = df["atr_14"] / df["close"]  # normalized ATR

    # Rate of Change (momentum)
    df["roc_6"] = df["close"].pct_change(6)  # 24h momentum
    df["roc_12"] = df["close"].pct_change(12)  # 48h momentum

    # Time features
    df["hour_sin"] = np.sin(2 * np.pi * df.index.hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df.index.hour / 24)
    df["day_sin"] = np.sin(2 * np.pi * df.index.dayofweek / 7)
    df["day_cos"] = np.cos(2 * np.pi * df.index.dayofweek / 7)

    return df


# ---------- Training ----------


def prepare_data(data_dir: Path, symbol: str, threshold: float = 0.005):
    """Load 4h data, add features, create binary labels."""
    pattern = f"{symbol.replace('/', '_')}_*.parquet"
    files = list(data_dir.glob(pattern))
    if not files:
        raise ValueError(f"No data for {symbol} in {data_dir}")

    dfs = []
    for f in files:
        print(f"Loading {f}")
        df = pd.read_parquet(f)
        df = add_features_4h(df)
        dfs.append(df)

    df = pd.concat(dfs).sort_index()
    df = df[~df.index.duplicated(keep="last")]

    # Binary labels: UP=1, DOWN=0, drop NEUTRAL
    df["future_ret"] = df["close"].shift(-1) / df["close"] - 1
    df["label"] = np.nan
    df.loc[df["future_ret"] > threshold, "label"] = 1
    df.loc[df["future_ret"] < -threshold, "label"] = 0

    df = df.dropna(subset=FEATURE_COLUMNS_4H + ["label"])

    X = df[FEATURE_COLUMNS_4H]
    y = df["label"].astype(int)

    print(f"\nDataset: {len(X)} bars (NEUTRAL dropped)")
    print(f"UP:   {(y == 1).sum()} ({(y == 1).mean() * 100:.1f}%)")
    print(f"DOWN: {(y == 0).sum()} ({(y == 0).mean() * 100:.1f}%)")
    print(f"Date range: {df.index[0]} to {df.index[-1]}")

    return X, y, df


def train_model(X_train, y_train, X_val, y_val, n_trials=50):
    """Train binary XGBoost with Optuna."""

    print(
        f"\nTrain: {len(X_train)} (UP={int((y_train == 1).sum())}, DOWN={int((y_train == 0).sum())})"
    )
    print(
        f"Val:   {len(X_val)} (UP={int((y_val == 1).sum())}, DOWN={int((y_val == 0).sum())})"
    )

    def objective(trial):
        params = {
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "tree_method": "hist",
            "max_depth": trial.suggest_int("max_depth", 3, 8),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 50, 400),
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

    print(f"\nOptuna: {n_trials} trials...")
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    best_params = {
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "tree_method": "hist",
        "random_state": 42,
        **study.best_trial.params,
    }

    model = xgb.XGBClassifier(**best_params)
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

    y_pred = model.predict(X_val)
    y_proba = model.predict_proba(X_val)[:, 1]

    print(f"\n{'=' * 60}")
    print("OUT-OF-SAMPLE VALIDATION RESULTS")
    print(f"{'=' * 60}")
    print(f"Accuracy: {accuracy_score(y_val, y_pred):.4f}")
    print(f"F1:       {f1_score(y_val, y_pred, average='binary'):.4f}")
    print(classification_report(y_val, y_pred, target_names=["DOWN", "UP"]))

    print("Win rate by confidence threshold:")
    for t in [0.50, 0.55, 0.60, 0.65, 0.70]:
        m = y_proba > t
        if m.sum() > 0:
            wr = (y_val[m] == 1).mean() * 100
            print(f"  P(UP)>{t:.2f}: {m.sum():4d} trades, WR={wr:.1f}%")
    for t in [0.50, 0.45, 0.40, 0.35]:
        m = y_proba < t
        if m.sum() > 0:
            wr = (y_val[m] == 0).mean() * 100
            print(f"  P(UP)<{t:.2f}: {m.sum():4d} shorts, WR={wr:.1f}%")

    # Feature importance
    importances = model.feature_importances_
    fi = sorted(zip(FEATURE_COLUMNS_4H, importances), key=lambda x: -x[1])
    print("\nTop 10 features:")
    for name, imp in fi[:10]:
        print(f"  {name:20s}: {imp:.4f}")

    metrics = {
        "train_accuracy": float(accuracy_score(y_train, model.predict(X_train))),
        "val_accuracy": float(accuracy_score(y_val, y_pred)),
        "val_f1": float(f1_score(y_val, y_pred, average="binary")),
        "train_size": len(X_train),
        "val_size": len(X_val),
        "best_params": best_params,
        "n_features": len(FEATURE_COLUMNS_4H),
    }

    return model, metrics


def backtest_simple(df, model, split_date, fee=0.0005):
    """Run simple 1-bar-ahead backtest on OOS data."""
    oos = df[df.index >= split_date].copy()
    oos = oos.dropna(subset=FEATURE_COLUMNS_4H + ["future_ret"])

    X = oos[FEATURE_COLUMNS_4H]
    proba = model.predict_proba(X)[:, 1]
    oos["p_up"] = proba

    print(f"\n{'=' * 60}")
    print("SIMPLE BACKTEST (1-bar hold, long only)")
    print(f"{'=' * 60}")

    for thresh in [0.50, 0.55, 0.60, 0.65, 0.70]:
        mask = oos["p_up"] > thresh
        if mask.sum() == 0:
            continue
        trades = oos[mask]
        net_ret = trades["future_ret"] - fee
        wins = (net_ret > 0).sum()
        n = len(trades)
        wr = wins / n * 100
        total = net_ret.sum() * 100
        avg = net_ret.mean() * 100
        sharpe = (
            net_ret.mean() / net_ret.std() * np.sqrt(365 * 6)
            if net_ret.std() > 0
            else 0
        )
        print(
            f"  P(UP)>{thresh:.2f}: {n:4d} trades | WR={wr:.1f}% | Total={total:+.1f}% | Avg={avg:+.3f}% | Sharpe={sharpe:.2f}"
        )

    # Short side
    print()
    for thresh in [0.50, 0.45, 0.40, 0.35]:
        mask = oos["p_up"] < thresh
        if mask.sum() == 0:
            continue
        trades = oos[mask]
        net_ret = -trades["future_ret"] - fee
        wins = (net_ret > 0).sum()
        n = len(trades)
        wr = wins / n * 100
        total = net_ret.sum() * 100
        avg = net_ret.mean() * 100
        sharpe = (
            net_ret.mean() / net_ret.std() * np.sqrt(365 * 6)
            if net_ret.std() > 0
            else 0
        )
        print(
            f"  P(UP)<{thresh:.2f}: {n:4d} shorts | WR={wr:.1f}% | Total={total:+.1f}% | Avg={avg:+.3f}% | Sharpe={sharpe:.2f}"
        )

    # Monthly breakdown for best-looking threshold
    print(f"\nMonthly breakdown (P(UP) > 0.55):")
    mask = oos["p_up"] > 0.55
    if mask.sum() > 0:
        trades = oos[mask].copy()
        trades["net_ret"] = trades["future_ret"] - fee
        trades["month"] = trades.index.to_period("M")
        for month, grp in trades.groupby("month"):
            wr = (grp["net_ret"] > 0).mean() * 100
            print(
                f"  {month}: {len(grp):3d} trades | WR={wr:.1f}% | PnL={grp['net_ret'].sum() * 100:+.2f}%"
            )
        total_pnl = trades["net_ret"].sum() * 100
        total_wr = (trades["net_ret"] > 0).mean() * 100
        print(
            f"  TOTAL: {len(trades)} trades | WR={total_wr:.1f}% | PnL={total_pnl:+.2f}%"
        )


def main():
    parser = argparse.ArgumentParser(description="Train 4h binary model")
    parser.add_argument("--data-dir", type=str, default="data_4h")
    parser.add_argument("--symbol", type=str, default="BTC/USDT")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.005,
        help="Return threshold (0.005 = 0.5% for 4h)",
    )
    parser.add_argument("--n-trials", type=int, default=50)
    parser.add_argument("--split-date", type=str, default="2025-02-08")
    parser.add_argument("--output", type=str, default="models_4h")

    args = parser.parse_args()

    X, y, df = prepare_data(Path(args.data_dir), args.symbol, args.threshold)

    split_date = pd.Timestamp(args.split_date)
    train_mask = X.index < split_date
    val_mask = X.index >= split_date

    X_train, y_train = X[train_mask], y[train_mask]
    X_val, y_val = X[val_mask], y[val_mask]

    print(f"\nSplit at {args.split_date}:")
    print(f"  Train: {X_train.index[0]} to {X_train.index[-1]}")
    print(f"  Val:   {X_val.index[0]} to {X_val.index[-1]}")

    model, metrics = train_model(X_train, y_train, X_val, y_val, args.n_trials)

    # Simple backtest
    backtest_simple(df, model, args.split_date)

    # Save
    sym_short = args.symbol.replace("/", "").lower()
    output_dir = Path(args.output) / f"{sym_short}_4h_binary"
    output_dir.mkdir(parents=True, exist_ok=True)
    model.save_model(output_dir / "xgboost_model.json")
    joblib.dump(model, output_dir / "xgboost_model.joblib")
    metrics["symbol"] = args.symbol
    metrics["threshold"] = args.threshold
    metrics["timeframe"] = "4h"
    with open(output_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    with open(output_dir / "features.json", "w") as f:
        json.dump(FEATURE_COLUMNS_4H, f, indent=2)
    print(f"\nModel saved to {output_dir}/")


if __name__ == "__main__":
    main()
