#!/usr/bin/env python3
"""Enhanced trade-level backtester with position sizing, TP/SL exits, and profitability gate.

Fixes from old backtest.py:
  - Time-based split (no random shuffle)
  - Correct annualization for 4h bars: sqrt(365*6)
  - Proper trade simulation with ATR-scaled TP/SL
  - Slippage + fee on BOTH entry and exit
  - Max 1 position per symbol, daily loss cap

Usage:
    python scripts/backtest_v2.py \\
        --trades results/walk_forward_results.parquet \\
        --data-dir data_4h \\
        --symbols BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT \\
        --initial-capital 10000 \\
        --report
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# 4h bars per year: 365 days * 6 bars/day = 2190
BARS_PER_YEAR_4H = 365 * 6


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TradeRecord:
    """Single completed trade."""

    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    symbol: str
    side: int  # 1 = long
    entry_price: float
    exit_price: float
    position_size: float  # in quote currency (notional)
    pnl: float
    pnl_pct: float
    holding_bars: int
    exit_reason: str  # "tp", "sl", "time"
    confidence: float
    signal_type: str
    fees_paid: float


# ---------------------------------------------------------------------------
# MetaLabelBacktester
# ---------------------------------------------------------------------------


class MetaLabelBacktester:
    """Trade-level backtester with position sizing, TP/SL, and profitability gate.

    Simulates trades bar-by-bar with:
      - ATR-scaled take-profit and stop-loss
      - Slippage on entry and exit
      - Fees on both legs
      - Max 1 position per symbol at a time
      - Daily loss cap (skip new trades if exceeded)
      - Risk-based position sizing
    """

    def __init__(
        self,
        initial_capital: float = 10_000,
        fee_pct: float = 0.0006,
        slippage_bps: float = 5.0,
        risk_per_trade_pct: float = 1.0,
        max_daily_loss_pct: float = 5.0,
        tp_atr_mult: float = 2.0,
        sl_atr_mult: float = 1.0,
        max_holding_bars: int = 20,
    ) -> None:
        self.initial_capital = initial_capital
        self.fee_pct = fee_pct
        self.slippage_bps = slippage_bps
        self.risk_per_trade_pct = risk_per_trade_pct / 100.0  # convert to decimal
        self.max_daily_loss_pct = max_daily_loss_pct / 100.0
        self.tp_atr_mult = tp_atr_mult
        self.sl_atr_mult = sl_atr_mult
        self.max_holding_bars = max_holding_bars

        # State — populated after run()
        self._trades: list[TradeRecord] = []
        self._equity_series: list[dict] = []
        self._ohlcv_data: dict[str, pd.DataFrame] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        trades_df: pd.DataFrame,
        ohlcv_data: dict[str, pd.DataFrame],
    ) -> list[TradeRecord]:
        """Run the backtest simulation.

        Args:
            trades_df: DataFrame with columns:
                - entry_time (datetime): signal timestamp
                - symbol (str): e.g. "BTC/USDT"
                - side (int): 1 = long (only long supported for now)
                - confidence (float): model confidence
                - signal_type (str): "trend", "breakout", "both"
            ohlcv_data: dict of {symbol: DataFrame} where each DataFrame has
                columns [open, high, low, close, volume, atr_14] and a
                DatetimeIndex.

        Returns:
            List of TradeRecord objects.
        """
        self._trades = []
        self._equity_series = []
        self._ohlcv_data = ohlcv_data

        if trades_df is None or trades_df.empty:
            return self._trades

        # Validate required columns
        required = {"entry_time", "symbol", "side", "confidence", "signal_type"}
        missing = required - set(trades_df.columns)
        if missing:
            raise ValueError(f"trades_df missing columns: {missing}")

        # Sort signals chronologically
        signals = trades_df.sort_values("entry_time").reset_index(drop=True)

        # Pre-index OHLCV data for fast positional access
        ohlcv_arrays: dict[str, dict] = {}
        for sym, df in ohlcv_data.items():
            df = df.sort_index()
            ohlcv_arrays[sym] = {
                "index": df.index,
                "open": df["open"].values,
                "high": df["high"].values,
                "low": df["low"].values,
                "close": df["close"].values,
                "atr": df["atr_14"].values if "atr_14" in df.columns else None,
                "ts_to_pos": {ts: i for i, ts in enumerate(df.index)},
                "n": len(df),
            }

        equity = self.initial_capital
        # Track the exit bar position per symbol so overlapping signals
        # during an open position are skipped.  Value = bar index at which
        # the current position exits (inclusive).
        position_exit_bar: dict[str, int] = {}
        daily_pnl: dict[str, float] = {}  # date_str -> cumulative daily pnl
        slippage_mult = self.slippage_bps / 10_000.0

        for _, sig in signals.iterrows():
            symbol = sig["symbol"]
            entry_time = pd.Timestamp(sig["entry_time"])
            side = int(sig["side"])
            confidence = float(sig["confidence"])
            signal_type = str(sig.get("signal_type", ""))

            # Skip if no OHLCV data for this symbol
            if symbol not in ohlcv_arrays:
                continue

            arr = ohlcv_arrays[symbol]

            # Find next bar after signal time for entry
            entry_bar_pos = self._find_next_bar(arr, entry_time)
            if entry_bar_pos is None or entry_bar_pos >= arr["n"] - 1:
                continue  # no bar available for entry

            # Skip if still in a position for this symbol (entry bar is
            # before or on the exit bar of the previous trade).
            if symbol in position_exit_bar:
                if entry_bar_pos <= position_exit_bar[symbol]:
                    continue
                # Previous position has been exited — clean up
                del position_exit_bar[symbol]

            # ATR at signal time — use the bar at or before the signal
            signal_bar_pos = self._find_bar_at_or_before(arr, entry_time)
            if signal_bar_pos is None:
                continue
            if arr["atr"] is None:
                continue
            atr_val = arr["atr"][signal_bar_pos]
            if np.isnan(atr_val) or atr_val <= 0:
                continue

            # Entry price = next bar's open + slippage
            raw_entry = arr["open"][entry_bar_pos]
            if side == 1:
                entry_price = raw_entry * (1.0 + slippage_mult)
            else:
                entry_price = raw_entry * (1.0 - slippage_mult)

            # TP / SL levels
            if side == 1:
                tp_price = entry_price + self.tp_atr_mult * atr_val
                sl_price = entry_price - self.sl_atr_mult * atr_val
            else:
                tp_price = entry_price - self.tp_atr_mult * atr_val
                sl_price = entry_price + self.sl_atr_mult * atr_val

            sl_distance_pct = abs(entry_price - sl_price) / entry_price
            if sl_distance_pct <= 0:
                continue

            # Position sizing: risk-based
            risk_amount = equity * self.risk_per_trade_pct
            position_size = risk_amount / sl_distance_pct  # notional in quote

            # Don't allow position larger than current equity
            position_size = min(position_size, equity)
            if position_size <= 0:
                continue

            # Daily loss cap check
            date_key = entry_time.strftime("%Y-%m-%d")
            day_loss = daily_pnl.get(date_key, 0.0)
            if day_loss < -(self.max_daily_loss_pct * self.initial_capital):
                continue  # daily loss cap hit, skip trade

            # Entry fee
            entry_fee = position_size * self.fee_pct

            # Simulate forward bar-by-bar
            max_exit_pos = min(entry_bar_pos + self.max_holding_bars, arr["n"] - 1)
            exit_pos = max_exit_pos
            exit_reason = "time"
            exit_price = arr["close"][max_exit_pos]

            for j in range(entry_bar_pos + 1, max_exit_pos + 1):
                if side == 1:
                    # SL check (conservative: SL checked first)
                    if arr["low"][j] <= sl_price:
                        exit_pos = j
                        exit_price = sl_price
                        exit_reason = "sl"
                        break
                    # TP check
                    if arr["high"][j] >= tp_price:
                        exit_pos = j
                        exit_price = tp_price
                        exit_reason = "tp"
                        break
                else:  # short
                    if arr["high"][j] >= sl_price:
                        exit_pos = j
                        exit_price = sl_price
                        exit_reason = "sl"
                        break
                    if arr["low"][j] <= tp_price:
                        exit_pos = j
                        exit_price = tp_price
                        exit_reason = "tp"
                        break

            # For time exit, apply slippage to close price
            if exit_reason == "time":
                if side == 1:
                    exit_price = arr["close"][exit_pos] * (1.0 - slippage_mult)
                else:
                    exit_price = arr["close"][exit_pos] * (1.0 + slippage_mult)

            # Exit fee
            exit_fee = position_size * self.fee_pct
            total_fees = entry_fee + exit_fee

            # PnL calculation
            if side == 1:
                raw_pnl = position_size * (exit_price / entry_price - 1.0)
            else:
                raw_pnl = position_size * (1.0 - exit_price / entry_price)

            net_pnl = raw_pnl - total_fees
            pnl_pct = net_pnl / position_size if position_size > 0 else 0.0

            holding_bars = exit_pos - entry_bar_pos
            exit_time = arr["index"][exit_pos]

            # Update equity
            equity += net_pnl

            # Track that this symbol is occupied until exit_pos
            position_exit_bar[symbol] = exit_pos

            # Update daily PnL tracker
            exit_date_key = exit_time.strftime("%Y-%m-%d")
            daily_pnl[exit_date_key] = daily_pnl.get(exit_date_key, 0.0) + net_pnl

            # Record trade
            trade = TradeRecord(
                entry_time=arr["index"][entry_bar_pos],
                exit_time=exit_time,
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                exit_price=exit_price,
                position_size=position_size,
                pnl=net_pnl,
                pnl_pct=pnl_pct,
                holding_bars=holding_bars,
                exit_reason=exit_reason,
                confidence=confidence,
                signal_type=signal_type,
                fees_paid=total_fees,
            )
            self._trades.append(trade)

            # Record equity point
            self._equity_series.append(
                {
                    "timestamp": exit_time,
                    "equity": equity,
                }
            )

        return self._trades

    def run_from_parquet(
        self,
        trades_path: str | Path,
        data_dir: str | Path,
        symbols: list[str],
    ) -> list[TradeRecord]:
        """Convenience method: load signals and OHLCV from files, then run.

        Args:
            trades_path: Path to parquet file with trade signals.
            data_dir: Directory containing 4h OHLCV parquet files.
            symbols: List of symbols (e.g. ["BTC/USDT", "ETH/USDT"]).

        Returns:
            List of TradeRecord objects.
        """
        import ta as ta_lib

        trades_path = Path(trades_path)
        data_dir = Path(data_dir)

        if not trades_path.exists():
            raise FileNotFoundError(f"Trades file not found: {trades_path}")

        trades_df = pd.read_parquet(trades_path)
        print(f"Loaded {len(trades_df)} trade signals from {trades_path}")

        ohlcv_data: dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            pattern = f"{symbol.replace('/', '_')}_*.parquet"
            files = sorted(data_dir.glob(pattern))
            if not files:
                print(f"WARNING: No OHLCV data for {symbol} in {data_dir}")
                continue

            dfs = []
            for f in files:
                dfs.append(pd.read_parquet(f))
            df = pd.concat(dfs).sort_index()
            df = df[~df.index.duplicated(keep="last")]

            # Compute ATR if not present
            if "atr_14" not in df.columns:
                df["atr_14"] = ta_lib.volatility.average_true_range(
                    df["high"], df["low"], df["close"], window=14
                )

            ohlcv_data[symbol] = df
            print(f"Loaded {symbol}: {len(df)} bars ({df.index[0]} to {df.index[-1]})")

        return self.run(trades_df, ohlcv_data)

    # ------------------------------------------------------------------
    # Output methods
    # ------------------------------------------------------------------

    def trade_log(self) -> pd.DataFrame:
        """Return a DataFrame of all completed trades."""
        if not self._trades:
            return pd.DataFrame(
                columns=[
                    "entry_time",
                    "exit_time",
                    "symbol",
                    "side",
                    "entry_price",
                    "exit_price",
                    "pnl",
                    "pnl_pct",
                    "holding_bars",
                    "exit_reason",
                    "confidence",
                    "signal_type",
                    "fees_paid",
                    "position_size",
                ]
            )

        records = []
        for t in self._trades:
            records.append(
                {
                    "entry_time": t.entry_time,
                    "exit_time": t.exit_time,
                    "symbol": t.symbol,
                    "side": t.side,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "pnl": t.pnl,
                    "pnl_pct": t.pnl_pct,
                    "holding_bars": t.holding_bars,
                    "exit_reason": t.exit_reason,
                    "confidence": t.confidence,
                    "signal_type": t.signal_type,
                    "fees_paid": t.fees_paid,
                    "position_size": t.position_size,
                }
            )
        return pd.DataFrame(records)

    def equity_curve(self) -> pd.DataFrame:
        """Return equity curve with drawdown percentage.

        Returns:
            DataFrame with columns: timestamp, equity, drawdown_pct
        """
        if not self._equity_series:
            return pd.DataFrame(columns=["timestamp", "equity", "drawdown_pct"])

        df = pd.DataFrame(self._equity_series)

        # Prepend initial equity
        first_ts = df["timestamp"].iloc[0] - pd.Timedelta(hours=4)
        initial_row = pd.DataFrame(
            [{"timestamp": first_ts, "equity": self.initial_capital}]
        )
        df = pd.concat([initial_row, df], ignore_index=True)

        df["peak"] = df["equity"].cummax()
        df["drawdown_pct"] = (df["equity"] - df["peak"]) / df["peak"]
        df = df.drop(columns=["peak"])

        return df

    def summary(self) -> dict[str, Any]:
        """Compute all key performance metrics.

        Returns:
            Dictionary of metrics.
        """
        log = self.trade_log()

        if log.empty:
            return self._empty_summary()

        total_trades = len(log)
        wins = log[log["pnl"] > 0]
        losses = log[log["pnl"] <= 0]
        n_wins = len(wins)
        n_losses = len(losses)

        # Basic metrics
        net_pnl = log["pnl"].sum()
        total_return = net_pnl / self.initial_capital
        final_equity = self.initial_capital + net_pnl
        win_rate = n_wins / total_trades if total_trades > 0 else 0.0

        # Profit factor
        gross_profit = wins["pnl"].sum() if n_wins > 0 else 0.0
        gross_loss = abs(losses["pnl"].sum()) if n_losses > 0 else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Expectancy per trade (as fraction of position size)
        expectancy = log["pnl_pct"].mean() if total_trades > 0 else 0.0

        # Sharpe ratio — annualized for 4h bars
        # Use per-trade returns, annualize by sqrt(trades_per_year)
        # But more standard: use bar-level equity returns
        pnl_series = log["pnl_pct"]
        if len(pnl_series) > 1 and pnl_series.std() > 0:
            # Estimate trades per year from actual trading period
            trading_days = (
                log["exit_time"].max() - log["entry_time"].min()
            ).total_seconds() / 86400.0
            if trading_days > 0:
                trades_per_year = total_trades / trading_days * 365.0
            else:
                trades_per_year = BARS_PER_YEAR_4H
            sharpe = pnl_series.mean() / pnl_series.std() * np.sqrt(trades_per_year)
        else:
            sharpe = 0.0

        # Annualized return
        trading_days = (
            log["exit_time"].max() - log["entry_time"].min()
        ).total_seconds() / 86400.0
        if trading_days > 0:
            annualized_return = (1.0 + total_return) ** (365.0 / trading_days) - 1.0
        else:
            annualized_return = 0.0

        # Max drawdown
        eq = self.equity_curve()
        if not eq.empty:
            max_dd_pct = eq["drawdown_pct"].min()
            # Drawdown duration in days
            dd_duration_days = self._max_drawdown_duration(eq)
        else:
            max_dd_pct = 0.0
            dd_duration_days = 0.0

        # Trades per day
        avg_trades_per_day = total_trades / trading_days if trading_days > 0 else 0.0

        # Monthly PnL
        monthly_pnl = self._monthly_pnl(log)
        n_months = len(monthly_pnl)
        profitable_months = (monthly_pnl["pnl"] > 0).sum() if n_months > 0 else 0
        profitable_months_pct = profitable_months / n_months if n_months > 0 else 0.0

        # Average holding
        avg_holding_bars = log["holding_bars"].mean()

        # Total fees
        total_fees = log["fees_paid"].sum()

        return {
            "initial_capital": self.initial_capital,
            "final_equity": final_equity,
            "net_pnl": net_pnl,
            "total_return": total_return,
            "annualized_return": annualized_return,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "sharpe": sharpe,
            "max_drawdown_pct": max_dd_pct,
            "max_dd_duration_days": dd_duration_days,
            "avg_trades_per_day": avg_trades_per_day,
            "avg_holding_bars": avg_holding_bars,
            "total_fees": total_fees,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "n_wins": n_wins,
            "n_losses": n_losses,
            "profitable_months_pct": profitable_months_pct,
            "trading_days": trading_days,
        }

    def print_report(self) -> None:
        """Print a formatted performance report."""
        s = self.summary()
        log = self.trade_log()

        print()
        print("=" * 70)
        print("  BACKTEST REPORT")
        print("=" * 70)

        if s["total_trades"] == 0:
            print("  No trades executed.")
            print("=" * 70)
            return

        # --- Overall ---
        print(f"\n{'─' * 70}")
        print("  OVERALL PERFORMANCE")
        print(f"{'─' * 70}")
        print(f"  Initial Capital:       ${s['initial_capital']:>12,.2f}")
        print(f"  Final Equity:          ${s['final_equity']:>12,.2f}")
        print(f"  Net PnL:               ${s['net_pnl']:>12,.2f}")
        print(f"  Total Return:          {s['total_return']:>12.2%}")
        print(f"  Annualized Return:     {s['annualized_return']:>12.2%}")
        print(f"  Total Fees Paid:       ${s['total_fees']:>12,.2f}")
        print(f"  Trading Period:        {s['trading_days']:>10.0f} days")

        # --- Trade stats ---
        print(f"\n{'─' * 70}")
        print("  TRADE STATISTICS")
        print(f"{'─' * 70}")
        print(f"  Total Trades:          {s['total_trades']:>12d}")
        print(f"  Win Rate:              {s['win_rate']:>12.2%}")
        print(f"  Profit Factor:         {s['profit_factor']:>12.2f}")
        print(f"  Expectancy/Trade:      {s['expectancy']:>12.4%}")
        print(f"  Sharpe Ratio:          {s['sharpe']:>12.2f}")
        print(f"  Avg Trades/Day:        {s['avg_trades_per_day']:>12.2f}")
        print(f"  Avg Holding (bars):    {s['avg_holding_bars']:>12.1f}")
        print(f"  Wins:                  {s['n_wins']:>12d}")
        print(f"  Losses:                {s['n_losses']:>12d}")
        print(f"  Gross Profit:          ${s['gross_profit']:>12,.2f}")
        print(f"  Gross Loss:            ${s['gross_loss']:>12,.2f}")

        # --- Risk ---
        print(f"\n{'─' * 70}")
        print("  RISK METRICS")
        print(f"{'─' * 70}")
        print(f"  Max Drawdown:          {s['max_drawdown_pct']:>12.2%}")
        print(f"  Max DD Duration:       {s['max_dd_duration_days']:>10.1f} days")
        print(f"  Profitable Months:     {s['profitable_months_pct']:>12.2%}")

        # --- Exit reason breakdown ---
        print(f"\n{'─' * 70}")
        print("  EXIT REASON BREAKDOWN")
        print(f"{'─' * 70}")
        if not log.empty:
            for reason in ["tp", "sl", "time"]:
                subset = log[log["exit_reason"] == reason]
                n = len(subset)
                if n == 0:
                    continue
                pct = n / len(log) * 100
                wr = (subset["pnl"] > 0).mean() * 100 if n > 0 else 0
                avg_pnl = subset["pnl"].mean()
                print(
                    f"  {reason.upper():6s}: {n:5d} ({pct:5.1f}%) | "
                    f"WR={wr:5.1f}% | Avg PnL=${avg_pnl:+.2f}"
                )

        # --- Monthly PnL ---
        monthly = self._monthly_pnl(log)
        if not monthly.empty:
            print(f"\n{'─' * 70}")
            print("  MONTHLY PnL")
            print(f"{'─' * 70}")
            print(f"  {'Month':>10s}  {'Trades':>7s}  {'PnL':>12s}  {'Cum PnL':>12s}")
            cum = 0.0
            for _, row in monthly.iterrows():
                cum += row["pnl"]
                marker = "+" if row["pnl"] > 0 else " "
                print(
                    f"  {row['month']:>10s}  {int(row['trades']):>7d}  "
                    f"${marker}{row['pnl']:>10,.2f}  ${cum:>11,.2f}"
                )

        # --- Per-symbol breakdown ---
        if not log.empty:
            print(f"\n{'─' * 70}")
            print("  PER-SYMBOL BREAKDOWN")
            print(f"{'─' * 70}")
            print(
                f"  {'Symbol':>12s}  {'Trades':>7s}  {'WR':>7s}  "
                f"{'PnL':>12s}  {'PF':>7s}  {'Avg PnL':>10s}"
            )
            for sym in sorted(log["symbol"].unique()):
                sym_log = log[log["symbol"] == sym]
                n = len(sym_log)
                wr = (sym_log["pnl"] > 0).mean()
                pnl = sym_log["pnl"].sum()
                gp = sym_log.loc[sym_log["pnl"] > 0, "pnl"].sum()
                gl = abs(sym_log.loc[sym_log["pnl"] <= 0, "pnl"].sum())
                pf = gp / gl if gl > 0 else float("inf")
                avg = sym_log["pnl"].mean()
                print(
                    f"  {sym:>12s}  {n:>7d}  {wr:>6.1%}  "
                    f"${pnl:>11,.2f}  {pf:>7.2f}  ${avg:>9,.2f}"
                )

        # --- Buy-and-hold comparison ---
        bh = self._buy_and_hold_return(log)
        if bh is not None:
            print(f"\n{'─' * 70}")
            print("  BUY-AND-HOLD COMPARISON (equal-weight portfolio)")
            print(f"{'─' * 70}")
            print(f"  Strategy Return:       {s['total_return']:>12.2%}")
            print(f"  Buy & Hold Return:     {bh:>12.2%}")
            alpha = s["total_return"] - bh
            print(f"  Alpha:                 {alpha:>12.2%}")

        print()
        print("=" * 70)

    def profitability_gate(self) -> dict[str, Any]:
        """Check pass/fail for each profitability criterion.

        Returns:
            Dictionary with each criterion name -> {value, threshold, pass}.
            Plus 'overall_pass' (True only if ALL pass).
        """
        s = self.summary()

        gates = {
            "win_rate": {
                "value": s["win_rate"],
                "threshold": 0.45,
                "op": ">=",
                "pass": s["win_rate"] >= 0.45,
            },
            "expectancy": {
                "value": s["expectancy"],
                "threshold": 0.003,
                "op": ">=",
                "pass": s["expectancy"] >= 0.003,
            },
            "profit_factor": {
                "value": s["profit_factor"],
                "threshold": 1.3,
                "op": ">=",
                "pass": s["profit_factor"] >= 1.3,
            },
            "sharpe": {
                "value": s["sharpe"],
                "threshold": 1.0,
                "op": ">=",
                "pass": s["sharpe"] >= 1.0,
            },
            "max_drawdown_pct": {
                "value": abs(s["max_drawdown_pct"]),
                "threshold": 0.25,
                "op": "<",
                "pass": abs(s["max_drawdown_pct"]) < 0.25,
            },
            "avg_trades_per_day": {
                "value": s["avg_trades_per_day"],
                "threshold": 3.0,
                "op": "<",
                "pass": s["avg_trades_per_day"] < 3.0,
            },
            "profitable_months_pct": {
                "value": s["profitable_months_pct"],
                "threshold": 0.60,
                "op": ">=",
                "pass": s["profitable_months_pct"] >= 0.60,
            },
        }

        overall = all(g["pass"] for g in gates.values())
        gates["overall_pass"] = overall

        return gates

    def print_profitability_gate(self) -> None:
        """Print the profitability gate results."""
        gates = self.profitability_gate()
        overall = gates.pop("overall_pass")

        print()
        print("=" * 70)
        print("  PROFITABILITY GATE")
        print("=" * 70)
        print(
            f"  {'Criterion':<25s}  {'Value':>10s}  {'Threshold':>10s}  {'Result':>8s}"
        )
        print(f"  {'─' * 60}")

        for name, g in gates.items():
            val_str = f"{g['value']:.4f}"
            thresh_str = f"{g['op']} {g['threshold']}"
            status = "PASS" if g["pass"] else "FAIL"
            marker = "  " if g["pass"] else "**"
            print(
                f"{marker}{name:<25s}  {val_str:>10s}  {thresh_str:>10s}  {status:>8s}"
            )

        print(f"  {'─' * 60}")
        overall_str = "ALL PASS" if overall else "FAILED"
        print(f"  Overall: {overall_str}")
        print("=" * 70)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_next_bar(self, arr: dict, ts: pd.Timestamp) -> int | None:
        """Find the position of the first bar strictly after ts."""
        idx = arr["index"]
        pos = idx.searchsorted(ts, side="right")
        if pos >= arr["n"]:
            return None
        return int(pos)

    def _find_bar_at_or_before(self, arr: dict, ts: pd.Timestamp) -> int | None:
        """Find the position of the bar at or just before ts."""
        idx = arr["index"]
        pos = idx.searchsorted(ts, side="right") - 1
        if pos < 0:
            return None
        return int(pos)

    def _empty_summary(self) -> dict[str, Any]:
        """Return an empty summary dict when no trades."""
        return {
            "initial_capital": self.initial_capital,
            "final_equity": self.initial_capital,
            "net_pnl": 0.0,
            "total_return": 0.0,
            "annualized_return": 0.0,
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "sharpe": 0.0,
            "max_drawdown_pct": 0.0,
            "max_dd_duration_days": 0.0,
            "avg_trades_per_day": 0.0,
            "avg_holding_bars": 0.0,
            "total_fees": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "n_wins": 0,
            "n_losses": 0,
            "profitable_months_pct": 0.0,
            "trading_days": 0.0,
        }

    def _monthly_pnl(self, log: pd.DataFrame) -> pd.DataFrame:
        """Compute monthly PnL table from trade log."""
        if log.empty:
            return pd.DataFrame(columns=["month", "trades", "pnl"])

        log_copy = log.copy()
        log_copy["month"] = log_copy["exit_time"].dt.to_period("M").astype(str)
        monthly = (
            log_copy.groupby("month")
            .agg(trades=("pnl", "count"), pnl=("pnl", "sum"))
            .reset_index()
        )
        return monthly

    def _max_drawdown_duration(self, eq: pd.DataFrame) -> float:
        """Compute the longest drawdown duration in days."""
        if eq.empty or len(eq) < 2:
            return 0.0

        peak = eq["equity"].cummax()
        in_dd = eq["equity"] < peak

        if not in_dd.any():
            return 0.0

        # Find contiguous drawdown periods
        max_duration = 0.0
        dd_start = None

        for i in range(len(eq)):
            if in_dd.iloc[i]:
                if dd_start is None:
                    dd_start = eq["timestamp"].iloc[i]
            else:
                if dd_start is not None:
                    duration = (
                        eq["timestamp"].iloc[i] - dd_start
                    ).total_seconds() / 86400.0
                    max_duration = max(max_duration, duration)
                    dd_start = None

        # Handle case where drawdown extends to the end
        if dd_start is not None:
            duration = (eq["timestamp"].iloc[-1] - dd_start).total_seconds() / 86400.0
            max_duration = max(max_duration, duration)

        return max_duration

    def _buy_and_hold_return(self, log: pd.DataFrame) -> float | None:
        """Compute equal-weight buy-and-hold return over the backtest period."""
        if log.empty or not self._ohlcv_data:
            return None

        start = log["entry_time"].min()
        end = log["exit_time"].max()

        returns = []
        for sym, df in self._ohlcv_data.items():
            df_period = df[(df.index >= start) & (df.index <= end)]
            if len(df_period) < 2:
                continue
            bh_ret = df_period["close"].iloc[-1] / df_period["close"].iloc[0] - 1.0
            returns.append(bh_ret)

        if not returns:
            return None

        # Equal-weight portfolio
        return float(np.mean(returns))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enhanced trade-level backtester with TP/SL and profitability gate"
    )
    parser.add_argument(
        "--trades",
        type=str,
        required=True,
        help="Path to parquet file with trade signals",
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
        "--initial-capital",
        type=float,
        default=10_000,
        help="Initial capital in USD (default: 10000)",
    )
    parser.add_argument(
        "--fee-pct",
        type=float,
        default=0.0006,
        help="Fee per trade leg as decimal (default: 0.0006 = 0.06%%)",
    )
    parser.add_argument(
        "--slippage-bps",
        type=float,
        default=5.0,
        help="Slippage in basis points (default: 5)",
    )
    parser.add_argument(
        "--risk-pct",
        type=float,
        default=1.0,
        help="Risk per trade as %% of equity (default: 1.0)",
    )
    parser.add_argument(
        "--max-daily-loss",
        type=float,
        default=5.0,
        help="Max daily loss as %% of initial capital (default: 5.0)",
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
        "--max-holding",
        type=int,
        default=20,
        help="Max holding period in bars (default: 20)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print detailed performance report",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Print profitability gate results",
    )
    parser.add_argument(
        "--save-trades",
        type=str,
        default=None,
        help="Save trade log to this parquet path",
    )
    parser.add_argument(
        "--save-equity",
        type=str,
        default=None,
        help="Save equity curve to this parquet path",
    )

    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")]

    bt = MetaLabelBacktester(
        initial_capital=args.initial_capital,
        fee_pct=args.fee_pct,
        slippage_bps=args.slippage_bps,
        risk_per_trade_pct=args.risk_pct,
        max_daily_loss_pct=args.max_daily_loss,
        tp_atr_mult=args.tp_mult,
        sl_atr_mult=args.sl_mult,
        max_holding_bars=args.max_holding,
    )

    bt.run_from_parquet(args.trades, args.data_dir, symbols)

    if args.report:
        bt.print_report()

    if args.gate:
        bt.print_profitability_gate()

    if not args.report and not args.gate:
        # Print summary by default
        s = bt.summary()
        print(f"\nBacktest complete: {s['total_trades']} trades")
        print(f"Net PnL: ${s['net_pnl']:,.2f} ({s['total_return']:.2%})")
        print(f"Sharpe: {s['sharpe']:.2f} | Win Rate: {s['win_rate']:.2%}")
        print(f"Max DD: {s['max_drawdown_pct']:.2%}")

    # Save outputs
    if args.save_trades:
        tl = bt.trade_log()
        save_path = Path(args.save_trades)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        tl.to_parquet(save_path, index=False)
        print(f"\nTrade log saved to {save_path}")

    if args.save_equity:
        ec = bt.equity_curve()
        save_path = Path(args.save_equity)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        ec.to_parquet(save_path, index=False)
        print(f"Equity curve saved to {save_path}")


if __name__ == "__main__":
    main()
