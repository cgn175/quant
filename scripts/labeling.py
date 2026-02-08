#!/usr/bin/env python3
"""Triple barrier labeling from 'Advances in Financial Machine Learning'.

Implements dynamic ATR-scaled barriers for binary label generation:
  - Take-Profit (TP): entry + tp_atr_mult * ATR
  - Stop-Loss (SL):   entry - sl_atr_mult * ATR
  - Time exit:         max_holding_bars bars, label by sign of return

Uses High/Low for intrabar barrier checks (more realistic than close-only).
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import ta


def triple_barrier_labels(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    atr: pd.Series,
    tp_atr_mult: float = 2.0,
    sl_atr_mult: float = 1.0,
    max_holding_bars: int = 20,
) -> pd.DataFrame:
    """Apply triple barrier labeling to every valid bar.

    Args:
        close: Close price series (timestamp-indexed).
        high: High price series.
        low: Low price series.
        atr: ATR series (same index as close).
        tp_atr_mult: TP barrier = entry_price + tp_atr_mult * ATR.
        sl_atr_mult: SL barrier = entry_price - sl_atr_mult * ATR.
        max_holding_bars: Maximum holding period before time exit.

    Returns:
        DataFrame with columns:
          - entry_idx: entry bar timestamp
          - exit_idx: exit bar timestamp
          - label: 1 (TP hit) or 0 (SL hit)
          - return: realized return (exit_price / entry_price - 1)
          - holding_bars: number of bars held
          - exit_reason: "tp", "sl", or "time"
    """
    # Validate inputs are aligned
    assert close.index.equals(high.index), "close/high index mismatch"
    assert close.index.equals(low.index), "close/low index mismatch"
    assert close.index.equals(atr.index), "close/atr index mismatch"

    # Filter out bars where ATR is NaN or zero
    valid_mask = atr.notna() & (atr > 0)
    valid_indices = close.index[valid_mask]

    results: list[dict] = []

    close_vals = close.values
    high_vals = high.values
    low_vals = low.values
    atr_vals = atr.values
    idx = close.index
    n = len(close_vals)

    # Map timestamps to integer positions for fast iteration
    idx_to_pos = {ts: i for i, ts in enumerate(idx)}

    for entry_ts in valid_indices:
        entry_pos = idx_to_pos[entry_ts]
        entry_price = close_vals[entry_pos]
        entry_atr = atr_vals[entry_pos]

        tp_price = entry_price + tp_atr_mult * entry_atr
        sl_price = entry_price - sl_atr_mult * entry_atr

        # Scan forward from entry+1
        max_pos = min(entry_pos + max_holding_bars, n - 1)
        exit_pos = max_pos
        exit_reason = "time"
        exit_price = close_vals[max_pos]

        for j in range(entry_pos + 1, max_pos + 1):
            # Check SL first (more conservative — if both hit in same bar, SL wins)
            if low_vals[j] <= sl_price:
                exit_pos = j
                exit_price = sl_price
                exit_reason = "sl"
                break
            # Check TP
            if high_vals[j] >= tp_price:
                exit_pos = j
                exit_price = tp_price
                exit_reason = "tp"
                break

        holding = exit_pos - entry_pos
        ret = exit_price / entry_price - 1.0

        if exit_reason == "time":
            label = 1 if ret > 0 else 0
        elif exit_reason == "tp":
            label = 1
        else:  # sl
            label = 0

        results.append(
            {
                "entry_idx": entry_ts,
                "exit_idx": idx[exit_pos],
                "label": label,
                "return": ret,
                "holding_bars": holding,
                "exit_reason": exit_reason,
            }
        )

    return pd.DataFrame(results)


def label_signals(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    atr: pd.Series,
    signal_indices: pd.DatetimeIndex | list,
    side: int = 1,
    tp_atr_mult: float = 2.0,
    sl_atr_mult: float = 1.0,
    max_holding_bars: int = 20,
) -> pd.DataFrame:
    """Label only at specific signal timestamps.

    Args:
        close: Close price series (timestamp-indexed).
        high: High price series.
        low: Low price series.
        atr: ATR series.
        signal_indices: Timestamps where signals occurred.
        side: Trade direction. 1 = long, -1 = short.
        tp_atr_mult: TP multiplier on ATR.
        sl_atr_mult: SL multiplier on ATR.
        max_holding_bars: Max bars to hold before time exit.

    Returns:
        DataFrame with same columns as triple_barrier_labels, plus 'side'.
    """
    # Validate signal indices exist in the data
    valid_signals = [ts for ts in signal_indices if ts in close.index]
    if not valid_signals:
        return pd.DataFrame(
            columns=[
                "entry_idx",
                "exit_idx",
                "label",
                "return",
                "holding_bars",
                "exit_reason",
                "side",
            ]
        )

    # For short trades, flip high/low and negate returns
    if side == -1:
        # Mirror: TP when price drops, SL when price rises
        # Flip high and low, then negate at the end
        close_adj = close.copy()
        high_adj = close.copy()  # placeholder — we need actual bars
        low_adj = close.copy()

        # For short: TP = entry - tp_mult*ATR (price going down)
        #            SL = entry + sl_mult*ATR (price going up)
        # We can reuse the long logic by flipping prices around entry
        pass  # Handled below with direct iteration

    close_vals = close.values
    high_vals = high.values
    low_vals = low.values
    atr_vals = atr.values
    idx = close.index
    n = len(close_vals)

    idx_to_pos = {ts: i for i, ts in enumerate(idx)}

    results: list[dict] = []

    for entry_ts in valid_signals:
        entry_pos = idx_to_pos[entry_ts]
        entry_price = close_vals[entry_pos]
        entry_atr = atr_vals[entry_pos]

        if np.isnan(entry_atr) or entry_atr <= 0:
            continue

        if side == 1:
            tp_price = entry_price + tp_atr_mult * entry_atr
            sl_price = entry_price - sl_atr_mult * entry_atr
        else:  # short
            tp_price = entry_price - tp_atr_mult * entry_atr
            sl_price = entry_price + sl_atr_mult * entry_atr

        max_pos = min(entry_pos + max_holding_bars, n - 1)
        exit_pos = max_pos
        exit_reason = "time"
        exit_price = close_vals[max_pos]

        for j in range(entry_pos + 1, max_pos + 1):
            if side == 1:
                # Long: SL if low <= sl_price, TP if high >= tp_price
                if low_vals[j] <= sl_price:
                    exit_pos = j
                    exit_price = sl_price
                    exit_reason = "sl"
                    break
                if high_vals[j] >= tp_price:
                    exit_pos = j
                    exit_price = tp_price
                    exit_reason = "tp"
                    break
            else:
                # Short: SL if high >= sl_price, TP if low <= tp_price
                if high_vals[j] >= sl_price:
                    exit_pos = j
                    exit_price = sl_price
                    exit_reason = "sl"
                    break
                if low_vals[j] <= tp_price:
                    exit_pos = j
                    exit_price = tp_price
                    exit_reason = "tp"
                    break

        holding = exit_pos - entry_pos

        if side == 1:
            ret = exit_price / entry_price - 1.0
        else:
            ret = entry_price / exit_price - 1.0

        if exit_reason == "time":
            ret = (close_vals[exit_pos] / entry_price - 1.0) * side
            label = 1 if ret > 0 else 0
        elif exit_reason == "tp":
            label = 1
        else:
            label = 0

        results.append(
            {
                "entry_idx": entry_ts,
                "exit_idx": idx[exit_pos],
                "label": label,
                "return": ret,
                "holding_bars": holding,
                "exit_reason": exit_reason,
                "side": side,
            }
        )

    return pd.DataFrame(results)


# ---------- CLI ----------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Triple barrier labeling for 4h OHLCV data"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data_4h",
        help="Directory with 4h OHLCV parquet files",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT",
        help="Comma-separated symbols",
    )
    parser.add_argument(
        "--tp-mult",
        type=float,
        default=2.0,
        help="Take-profit ATR multiplier (default: 2.0)",
    )
    parser.add_argument(
        "--sl-mult",
        type=float,
        default=1.0,
        help="Stop-loss ATR multiplier (default: 1.0)",
    )
    parser.add_argument(
        "--max-bars",
        type=int,
        default=20,
        help="Max holding period in bars (default: 20 = 80h on 4h)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data_4h/labels_triple_barrier.parquet",
        help="Output parquet path",
    )

    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")]
    data_dir = Path(args.data_dir)

    all_labels: list[pd.DataFrame] = []

    for symbol in symbols:
        pattern = f"{symbol.replace('/', '_')}_*.parquet"
        files = list(data_dir.glob(pattern))
        if not files:
            print(f"No data found for {symbol}")
            continue

        dfs = []
        for f in files:
            print(f"Loading {f}")
            dfs.append(pd.read_parquet(f))

        df = pd.concat(dfs).sort_index()
        df = df[~df.index.duplicated(keep="last")]

        # Compute ATR
        atr_14 = ta.volatility.average_true_range(
            df["high"], df["low"], df["close"], window=14
        )

        print(
            f"\nLabeling {symbol} (TP={args.tp_mult}x ATR, SL={args.sl_mult}x ATR, max={args.max_bars} bars)..."
        )
        labels = triple_barrier_labels(
            close=df["close"],
            high=df["high"],
            low=df["low"],
            atr=atr_14,
            tp_atr_mult=args.tp_mult,
            sl_atr_mult=args.sl_mult,
            max_holding_bars=args.max_bars,
        )
        labels["symbol"] = symbol

        # Print summary
        n = len(labels)
        if n > 0:
            tp_pct = (labels["exit_reason"] == "tp").mean() * 100
            sl_pct = (labels["exit_reason"] == "sl").mean() * 100
            time_pct = (labels["exit_reason"] == "time").mean() * 100
            win_rate = labels["label"].mean() * 100
            avg_ret = labels["return"].mean() * 100
            avg_hold = labels["holding_bars"].mean()

            print(f"  {symbol}: {n} labels")
            print(
                f"    TP exits: {tp_pct:.1f}% | SL exits: {sl_pct:.1f}% | Time exits: {time_pct:.1f}%"
            )
            print(
                f"    Win rate: {win_rate:.1f}% | Avg return: {avg_ret:+.3f}% | Avg hold: {avg_hold:.1f} bars"
            )
        else:
            print(f"  {symbol}: 0 labels (no valid bars)")

        all_labels.append(labels)

    if not all_labels:
        print("No labels generated!")
        return

    combined = pd.concat(all_labels, ignore_index=True)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(output_path)
    print(f"\nSaved {len(combined)} labels to {output_path}")

    # Overall summary
    print(f"\n{'=' * 60}")
    print("OVERALL LABEL SUMMARY")
    print(f"{'=' * 60}")
    print(f"Total labels: {len(combined)}")
    print(f"Win rate: {combined['label'].mean() * 100:.1f}%")
    print(f"Avg return: {combined['return'].mean() * 100:+.3f}%")
    print(f"Exit reasons:")
    for reason in ["tp", "sl", "time"]:
        cnt = (combined["exit_reason"] == reason).sum()
        pct = cnt / len(combined) * 100
        print(f"  {reason}: {cnt} ({pct:.1f}%)")


if __name__ == "__main__":
    main()
