#!/usr/bin/env python3
"""
Plan D: Event-Driven Trend Following Backtester.

Processes bars chronologically with:
- Chandelier trailing stops (ATR-based, never moves against position)
- Partial exits at 3R and 6R
- Daily loss cap
- Multi-symbol portfolio with correlation limits
- Realistic fees and slippage
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from trend_signals import DEFAULT_PARAMS, generate_signals

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Position:
    symbol: str
    direction: int  # 1 = long, -1 = short
    entry_price: float
    entry_time: pd.Timestamp
    size: float  # in base units
    initial_stop: float
    trailing_stop: float
    initial_risk_r: float  # dollar risk per unit (|entry - stop|)
    partial_exits_done: set = field(default_factory=set)  # {"3R", "6R"}
    original_size: float = 0.0
    position_id: int = 0  # unique ID for grouping partial trades

    def __post_init__(self):
        if self.original_size == 0.0:
            self.original_size = self.size


@dataclass
class Trade:
    symbol: str
    direction: int
    entry_price: float
    exit_price: float
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    size: float
    pnl: float
    pnl_pct: float
    r_multiple: float
    exit_reason: str  # "stop", "partial_3R", "partial_6R"
    fees: float = 0.0
    position_id: int = 0  # links partial trades to same position


@dataclass
class BacktestResult:
    equity_curve: list  # [(timestamp, equity), ...]
    trades: list[Trade]
    metrics: dict


# Correlation buckets for crypto
CORRELATED_BUCKETS = {
    "BTCUSDT": "btc_group",
    "BTC/USDT": "btc_group",
    "ETHUSDT": "btc_group",
    "ETH/USDT": "btc_group",
    "SOLUSDT": "alt_group",
    "SOL/USDT": "alt_group",
    "BNBUSDT": "alt_group",
    "BNB/USDT": "alt_group",
}


# ---------------------------------------------------------------------------
# Backtester
# ---------------------------------------------------------------------------

class TrendFollowingBacktester:
    def __init__(
        self,
        initial_equity: float = 10_000,
        risk_per_trade: float = 0.01,
        atr_stop_mult: float = 3.0,
        max_leverage: float = 2.0,
        max_daily_loss: float = 0.03,
        fee_rate: float = 0.0004,
        slippage_bps: float = 5.0,
        max_positions: int = 4,
        max_correlated: int = 2,
        chandelier_lookback: int = 10,
    ):
        self.initial_equity = initial_equity
        self.risk_per_trade = risk_per_trade
        self.atr_stop_mult = atr_stop_mult
        self.max_leverage = max_leverage
        self.max_daily_loss = max_daily_loss
        self.fee_rate = fee_rate
        self.slippage_bps = slippage_bps
        self.max_positions = max_positions
        self.max_correlated = max_correlated
        self.chandelier_lookback = chandelier_lookback

        # State
        self.equity = initial_equity
        self.positions: dict[str, Position] = {}  # symbol -> Position
        self.trades: list[Trade] = []
        self.equity_curve: list[tuple] = []
        self.daily_pnl: float = 0.0
        self.current_day = None
        self.halted = False
        self._next_position_id = 1

    def reset(self):
        self.equity = self.initial_equity
        self.positions = {}
        self.trades = []
        self.equity_curve = [(None, self.initial_equity)]
        self.daily_pnl = 0.0
        self.current_day = None
        self.halted = False
        self._next_position_id = 1

    def _apply_slippage(self, price: float, direction: int, is_exit: bool) -> float:
        """Apply slippage. For entries: adverse; for exits: adverse."""
        slip = price * self.slippage_bps / 10_000
        if is_exit:
            direction = -direction  # exit is opposite
        return price + direction * slip  # buy higher, sell lower

    def _calc_fees(self, notional: float) -> float:
        return notional * self.fee_rate

    def _calc_position_size(self, entry_price: float, atr_val: float,
                            size_multiplier: float = 1.0) -> float:
        """ATR-based position sizing. risk_per_trade % of equity per 1R."""
        stop_dist = self.atr_stop_mult * atr_val
        stop_dist_pct = stop_dist / entry_price
        if stop_dist_pct <= 0:
            return 0.0

        risk_amount = self.equity * self.risk_per_trade * size_multiplier
        size = risk_amount / (entry_price * stop_dist_pct)

        # Cap by leverage
        max_notional = self.equity * self.max_leverage
        max_size = max_notional / entry_price
        return min(size, max_size)

    def _count_correlated(self, symbol: str, direction: int) -> int:
        """Count open positions in same direction within same correlation bucket."""
        bucket = CORRELATED_BUCKETS.get(symbol, symbol)
        count = 0
        for sym, pos in self.positions.items():
            if pos.direction == direction:
                if CORRELATED_BUCKETS.get(sym, sym) == bucket:
                    count += 1
        return count

    def _close_position(self, symbol: str, exit_price: float,
                        exit_time: pd.Timestamp, reason: str,
                        partial_pct: float = 1.0):
        """Close (or partially close) a position."""
        pos = self.positions[symbol]
        close_size = pos.size * partial_pct

        # Apply slippage to exit
        fill_price = self._apply_slippage(exit_price, pos.direction, is_exit=True)

        # PnL
        raw_pnl = pos.direction * (fill_price - pos.entry_price) * close_size
        entry_fees = self._calc_fees(pos.entry_price * close_size)
        exit_fees = self._calc_fees(fill_price * close_size)
        total_fees = entry_fees + exit_fees
        net_pnl = raw_pnl - total_fees

        # R-multiple
        r_mult = 0.0
        if pos.initial_risk_r > 0:
            r_mult = (pos.direction * (fill_price - pos.entry_price)) / pos.initial_risk_r

        pnl_pct = net_pnl / self.equity if self.equity > 0 else 0.0

        trade = Trade(
            symbol=symbol,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=fill_price,
            entry_time=pos.entry_time,
            exit_time=exit_time,
            size=close_size,
            pnl=net_pnl,
            pnl_pct=pnl_pct,
            r_multiple=r_mult,
            exit_reason=reason,
            fees=total_fees,
            position_id=pos.position_id,
        )
        self.trades.append(trade)

        # Update equity
        self.equity += net_pnl
        self.daily_pnl += net_pnl
        self.equity_curve.append((exit_time, self.equity))

        # Update or remove position
        if partial_pct >= 0.999:
            del self.positions[symbol]
        else:
            pos.size -= close_size

    def _check_stops(self, symbol: str, bar: pd.Series, timestamp: pd.Timestamp):
        """Check if trailing stop was hit using bar high/low."""
        if symbol not in self.positions:
            return
        pos = self.positions[symbol]

        hit = False
        if pos.direction == 1:  # long
            if bar["low"] <= pos.trailing_stop:
                hit = True
                exit_price = pos.trailing_stop
        else:  # short
            if bar["high"] >= pos.trailing_stop:
                hit = True
                exit_price = pos.trailing_stop

        if hit:
            self._close_position(symbol, exit_price, timestamp, "stop")

    def _update_trailing_stop(self, symbol: str, highs: pd.Series,
                              lows: pd.Series, atr_val: float):
        """Update Chandelier trailing stop (never moves against position)."""
        if symbol not in self.positions:
            return
        pos = self.positions[symbol]

        if len(highs) < self.chandelier_lookback:
            return

        recent_highs = highs.iloc[-self.chandelier_lookback:]
        recent_lows = lows.iloc[-self.chandelier_lookback:]

        if pos.direction == 1:  # long
            new_stop = recent_highs.max() - self.atr_stop_mult * atr_val
            if new_stop > pos.trailing_stop:
                pos.trailing_stop = new_stop
        else:  # short
            new_stop = recent_lows.min() + self.atr_stop_mult * atr_val
            if new_stop < pos.trailing_stop:
                pos.trailing_stop = new_stop

    def _check_partial_exits(self, symbol: str, bar: pd.Series,
                             timestamp: pd.Timestamp):
        """Check for partial exits at 3R and 6R."""
        if symbol not in self.positions:
            return
        pos = self.positions[symbol]

        current_price = bar["close"]
        price_move = pos.direction * (current_price - pos.entry_price)
        r_current = price_move / pos.initial_risk_r if pos.initial_risk_r > 0 else 0

        # 3R partial exit
        if "3R" not in pos.partial_exits_done and r_current >= 3.0:
            self._close_position(symbol, current_price, timestamp, "partial_3R",
                                 partial_pct=0.25)
            if symbol in self.positions:
                pos = self.positions[symbol]
                pos.partial_exits_done.add("3R")
                # Move stop to breakeven
                pos.trailing_stop = pos.entry_price

        # 6R partial exit
        if symbol in self.positions:
            pos = self.positions[symbol]
            if "6R" not in pos.partial_exits_done and r_current >= 6.0:
                self._close_position(symbol, current_price, timestamp, "partial_6R",
                                     partial_pct=0.25 / (1 - 0.25))  # 25% of remaining 75%
                if symbol in self.positions:
                    self.positions[symbol].partial_exits_done.add("6R")

    def _check_daily_reset(self, timestamp: pd.Timestamp):
        """Reset daily PnL tracker and halt flag at day boundary."""
        day = timestamp.date()
        if self.current_day != day:
            self.current_day = day
            self.daily_pnl = 0.0
            self.halted = False

    def _is_halted(self) -> bool:
        """Check daily loss cap."""
        if self.halted:
            return True
        if self.equity > 0 and self.daily_pnl < -self.max_daily_loss * self.equity:
            self.halted = True
            return True
        return False

    def run(self, signals_dict: dict[str, pd.DataFrame],
            ohlcv_dict: dict[str, pd.DataFrame]) -> BacktestResult:
        """Run backtest across all symbols.

        Args:
            signals_dict: {symbol: DataFrame from generate_signals()}
            ohlcv_dict: {symbol: raw OHLCV DataFrame}

        Returns:
            BacktestResult with equity curve, trades, and metrics.
        """
        self.reset()

        # Get all unique timestamps across all symbols, sorted
        all_timestamps = set()
        for sym in signals_dict:
            all_timestamps.update(signals_dict[sym].index)
        all_timestamps = sorted(all_timestamps)

        symbols = sorted(signals_dict.keys())

        for ts in all_timestamps:
            self._check_daily_reset(ts)

            for sym in symbols:
                sig_df = signals_dict[sym]
                ohlcv_df = ohlcv_dict[sym]

                if ts not in sig_df.index:
                    continue

                bar = ohlcv_df.loc[ts]
                sig_row = sig_df.loc[ts]

                # 1. Check stops on existing positions
                self._check_stops(sym, bar, ts)

                # 2. Update trailing stops
                if sym in self.positions:
                    # Get historical highs/lows up to current bar
                    idx = ohlcv_df.index.get_loc(ts)
                    start = max(0, idx - self.chandelier_lookback + 1)
                    highs = ohlcv_df["high"].iloc[start:idx + 1]
                    lows = ohlcv_df["low"].iloc[start:idx + 1]
                    atr_val = sig_row["atr"] if not np.isnan(sig_row["atr"]) else 0
                    self._update_trailing_stop(sym, highs, lows, atr_val)

                # 3. Check partial exits
                self._check_partial_exits(sym, bar, ts)

                # 4. Check for new entries
                if self._is_halted():
                    continue
                if sym in self.positions:
                    continue  # already have position in this symbol
                if len(self.positions) >= self.max_positions:
                    continue

                signal = int(sig_row["signal"])
                if signal == 0:
                    continue

                atr_val = sig_row["atr"]
                if np.isnan(atr_val) or atr_val <= 0:
                    continue

                # Correlation check
                if self._count_correlated(sym, signal) >= self.max_correlated:
                    continue

                # Position sizing
                entry_price = bar["close"]
                size_mult = sig_row["size_multiplier"]
                size = self._calc_position_size(entry_price, atr_val, size_mult)
                if size <= 0:
                    continue

                # Apply entry slippage
                fill_price = self._apply_slippage(entry_price, signal, is_exit=False)

                # Calculate stop
                stop_dist = self.atr_stop_mult * atr_val
                initial_risk_r = stop_dist  # per-unit dollar risk
                if signal == 1:
                    initial_stop = fill_price - stop_dist
                else:
                    initial_stop = fill_price + stop_dist

                # Create position
                pos = Position(
                    symbol=sym,
                    direction=signal,
                    entry_price=fill_price,
                    entry_time=ts,
                    size=size,
                    initial_stop=initial_stop,
                    trailing_stop=initial_stop,
                    initial_risk_r=initial_risk_r,
                    position_id=self._next_position_id,
                )
                self._next_position_id += 1
                self.positions[sym] = pos

        # Close any remaining positions at last bar close
        for sym in list(self.positions.keys()):
            if sym in ohlcv_dict and len(ohlcv_dict[sym]) > 0:
                last_bar = ohlcv_dict[sym].iloc[-1]
                last_ts = ohlcv_dict[sym].index[-1]
                self._close_position(sym, last_bar["close"], last_ts, "end_of_data")

        metrics = self._compute_metrics()
        return BacktestResult(
            equity_curve=self.equity_curve,
            trades=self.trades,
            metrics=metrics,
        )

    def _compute_metrics(self) -> dict:
        """Compute performance metrics."""
        trades = self.trades
        if not trades:
            return {"total_return": 0, "num_trades": 0, "error": "no trades"}

        # Equity curve to series
        eq_df = pd.DataFrame(self.equity_curve, columns=["timestamp", "equity"])
        eq_df = eq_df.dropna(subset=["timestamp"])
        if len(eq_df) < 2:
            eq_df = pd.DataFrame(
                [(trades[0].entry_time, self.initial_equity),
                 (trades[-1].exit_time, self.equity)],
                columns=["timestamp", "equity"],
            )

        total_return = (self.equity - self.initial_equity) / self.initial_equity

        # Daily returns for Sharpe/Sortino
        eq_df = eq_df.set_index("timestamp").sort_index()
        eq_df = eq_df[~eq_df.index.duplicated(keep="last")]
        daily_eq = eq_df.resample("1D").last().dropna()
        daily_returns = daily_eq["equity"].pct_change().dropna()

        # Annualized Sharpe
        if len(daily_returns) > 1 and daily_returns.std() > 0:
            sharpe = daily_returns.mean() / daily_returns.std() * np.sqrt(365)
        else:
            sharpe = 0.0

        # Sortino
        downside = daily_returns[daily_returns < 0]
        if len(downside) > 0 and downside.std() > 0:
            sortino = daily_returns.mean() / downside.std() * np.sqrt(365)
        else:
            sortino = 0.0

        # Max drawdown
        eq_series = eq_df["equity"]
        running_max = eq_series.cummax()
        drawdown = (eq_series - running_max) / running_max
        max_dd = abs(drawdown.min()) if len(drawdown) > 0 else 0.0

        # CAGR
        if len(eq_df) > 1:
            days = (eq_df.index[-1] - eq_df.index[0]).days
            if days > 0 and self.equity > 0:
                cagr = (self.equity / self.initial_equity) ** (365 / days) - 1
            else:
                cagr = 0.0
        else:
            cagr = 0.0

        # Calmar
        calmar = cagr / max_dd if max_dd > 0 else 0.0

        # Trade stats — POSITION-LEVEL aggregation
        # Group partial trades into positions for correct W/L ratio
        pos_pnls = {}  # position_id -> total_pnl
        for t in trades:
            pid = t.position_id
            if pid not in pos_pnls:
                pos_pnls[pid] = 0.0
            pos_pnls[pid] += t.pnl

        pos_pnl_list = list(pos_pnls.values())
        pos_winners = [p for p in pos_pnl_list if p > 0]
        pos_losers = [p for p in pos_pnl_list if p <= 0]
        pos_win_rate = len(pos_winners) / len(pos_pnl_list) if pos_pnl_list else 0.0

        pos_avg_winner = np.mean(pos_winners) if pos_winners else 0.0
        pos_avg_loser = abs(np.mean(pos_losers)) if pos_losers else 0.0
        pos_avg_wl_ratio = pos_avg_winner / pos_avg_loser if pos_avg_loser > 0 else float("inf")

        pos_profit_factor = sum(pos_winners) / abs(sum(pos_losers)) if pos_losers and sum(pos_losers) != 0 else float("inf")

        pos_expectancy = np.mean(pos_pnl_list) if pos_pnl_list else 0.0
        pos_expectancy_pct = pos_expectancy / self.initial_equity * 100

        # Also keep per-trade stats for reference
        pnls = [t.pnl for t in trades]
        winners = [p for p in pnls if p > 0]
        losers = [p for p in pnls if p <= 0]

        # R-multiples
        r_mults = [t.r_multiple for t in trades]
        avg_r = np.mean(r_mults) if r_mults else 0.0

        # Consecutive losses
        max_consec_loss = 0
        curr_consec = 0
        for p in pnls:
            if p <= 0:
                curr_consec += 1
                max_consec_loss = max(max_consec_loss, curr_consec)
            else:
                curr_consec = 0

        # Trades per month
        if len(eq_df) > 1:
            days = (eq_df.index[-1] - eq_df.index[0]).days
            months = max(days / 30.44, 1)
            trades_per_month = len(trades) / months
        else:
            trades_per_month = 0.0

        # Profitable months
        trade_df = pd.DataFrame([{
            "exit_time": t.exit_time, "pnl": t.pnl
        } for t in trades])
        if len(trade_df) > 0:
            trade_df = trade_df.set_index("exit_time")
            monthly = trade_df.resample("ME")["pnl"].sum()
            profitable_months = (monthly > 0).sum()
            total_months = len(monthly)
            profitable_months_pct = profitable_months / total_months if total_months > 0 else 0.0
        else:
            profitable_months_pct = 0.0

        total_fees = sum(t.fees for t in trades)

        return {
            "total_return": total_return,
            "total_return_pct": total_return * 100,
            "cagr": cagr,
            "sharpe": sharpe,
            "sortino": sortino,
            "calmar": calmar,
            "max_drawdown": max_dd,
            "max_drawdown_pct": max_dd * 100,
            "win_rate": pos_win_rate,
            "win_rate_pct": pos_win_rate * 100,
            "profit_factor": pos_profit_factor,
            "expectancy": pos_expectancy,
            "expectancy_pct": pos_expectancy_pct,
            "avg_winner": pos_avg_winner,
            "avg_loser": pos_avg_loser,
            "avg_winner_loser_ratio": pos_avg_wl_ratio,
            "avg_r_multiple": avg_r,
            "max_consecutive_losses": max_consec_loss,
            "num_trades": len(pos_pnl_list),  # position count, not partial trade count
            "num_trade_records": len(trades),  # includes partials
            "trades_per_month": trades_per_month,
            "profitable_months_pct": profitable_months_pct * 100,
            "total_fees": total_fees,
            "final_equity": self.equity,
        }


# ---------------------------------------------------------------------------
# Data Loading Helpers
# ---------------------------------------------------------------------------

def load_symbol_data(data_dir: Path, symbol_file: str) -> pd.DataFrame:
    """Load OHLCV data from parquet or CSV."""
    parquet = data_dir / symbol_file
    if parquet.exists():
        df = pd.read_parquet(parquet)
    else:
        csv = parquet.with_suffix(".csv")
        df = pd.read_csv(csv, parse_dates=["timestamp"], index_col="timestamp")
    return df


def load_all_data(data_dir: Path = None, funding_dir: Path = None):
    """Load all 4 symbols' OHLCV and funding data.

    Returns: (ohlcv_dict, funding_dict)
    """
    if data_dir is None:
        data_dir = Path(__file__).resolve().parent.parent / "data_4h"
    if funding_dir is None:
        funding_dir = data_dir / "funding"

    symbols_files = {
        "BTC/USDT": "BTC_USDT_4h_2190d.parquet",
        "ETH/USDT": "ETH_USDT_4h_2190d.parquet",
        "SOL/USDT": "SOL_USDT_4h_2190d.parquet",
        "BNB/USDT": "BNB_USDT_4h_2190d.parquet",
    }
    funding_files = {
        "BTC/USDT": "BTC_USDT_funding_2190d.parquet",
        "ETH/USDT": "ETH_USDT_funding_2190d.parquet",
        "SOL/USDT": "SOL_USDT_funding_2190d.parquet",
        "BNB/USDT": "BNB_USDT_funding_2190d.parquet",
    }

    ohlcv_dict = {}
    funding_dict = {}

    for sym, fname in symbols_files.items():
        fpath = data_dir / fname
        if fpath.exists():
            ohlcv_dict[sym] = pd.read_parquet(fpath)
            print(f"  Loaded {sym}: {len(ohlcv_dict[sym]):,} bars")

    for sym, fname in funding_files.items():
        fpath = funding_dir / fname
        if fpath.exists():
            funding_dict[sym] = pd.read_parquet(fpath)

    return ohlcv_dict, funding_dict


def print_metrics(metrics: dict):
    """Pretty-print backtest metrics."""
    print()
    print("=" * 60)
    print("BACKTEST RESULTS — Plan D: Trend Following")
    print("=" * 60)
    print(f"  Final equity:       ${metrics['final_equity']:,.2f}")
    print(f"  Total return:       {metrics['total_return_pct']:+.2f}%")
    print(f"  CAGR:               {metrics['cagr'] * 100:+.2f}%")
    print(f"  Sharpe ratio:       {metrics['sharpe']:.2f}")
    print(f"  Sortino ratio:      {metrics['sortino']:.2f}")
    print(f"  Calmar ratio:       {metrics['calmar']:.2f}")
    print(f"  Max drawdown:       {metrics['max_drawdown_pct']:.2f}%")
    print()
    print(f"  Win rate:           {metrics['win_rate_pct']:.1f}%")
    print(f"  Profit factor:      {metrics['profit_factor']:.2f}")
    print(f"  Expectancy/trade:   ${metrics['expectancy']:.2f} ({metrics['expectancy_pct']:.3f}%)")
    print(f"  Avg winner:         ${metrics['avg_winner']:.2f}")
    print(f"  Avg loser:          ${metrics['avg_loser']:.2f}")
    print(f"  Winner/loser ratio: {metrics['avg_winner_loser_ratio']:.2f}")
    print(f"  Avg R-multiple:     {metrics['avg_r_multiple']:.2f}")
    print()
    print(f"  Num trades:         {metrics['num_trades']}")
    print(f"  Trades/month:       {metrics['trades_per_month']:.1f}")
    print(f"  Max consec losses:  {metrics['max_consecutive_losses']}")
    print(f"  Profitable months:  {metrics['profitable_months_pct']:.1f}%")
    print(f"  Total fees:         ${metrics['total_fees']:.2f}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    print("Plan D: Trend Following Backtest")
    print("-" * 40)

    # Load data
    print("Loading data...")
    ohlcv_dict, funding_dict = load_all_data()

    if not ohlcv_dict:
        print("ERROR: No OHLCV data found in data_4h/")
        sys.exit(1)

    # Generate signals for each symbol
    print("\nGenerating signals...")
    signals_dict = {}
    for sym, df in ohlcv_dict.items():
        funding = funding_dict.get(sym)
        signals = generate_signals(df, funding)
        signals_dict[sym] = signals
        n_signals = (signals["signal"] != 0).sum()
        print(f"  {sym}: {n_signals} signals")

    # Run backtest
    print("\nRunning backtest...")
    bt = TrendFollowingBacktester(
        initial_equity=10_000,
        risk_per_trade=0.01,
        atr_stop_mult=3.0,
        max_leverage=2.0,
        max_daily_loss=0.03,
        fee_rate=0.0004,
        slippage_bps=5.0,
    )
    result = bt.run(signals_dict, ohlcv_dict)

    # Print results
    print_metrics(result.metrics)

    # Save results
    results_dir = Path(__file__).resolve().parent.parent / "results"
    results_dir.mkdir(exist_ok=True)

    # Equity curve
    eq_df = pd.DataFrame(result.equity_curve, columns=["timestamp", "equity"])
    eq_df = eq_df.dropna(subset=["timestamp"])
    eq_path = results_dir / "plan_d_equity.csv"
    eq_df.to_csv(eq_path, index=False)
    print(f"\nEquity curve saved to {eq_path}")

    # Trade log
    trades_data = []
    for t in result.trades:
        trades_data.append({
            "symbol": t.symbol,
            "direction": "LONG" if t.direction == 1 else "SHORT",
            "entry_time": t.entry_time,
            "exit_time": t.exit_time,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "size": t.size,
            "pnl": round(t.pnl, 2),
            "pnl_pct": round(t.pnl_pct * 100, 3),
            "r_multiple": round(t.r_multiple, 2),
            "exit_reason": t.exit_reason,
            "fees": round(t.fees, 2),
        })
    trades_df = pd.DataFrame(trades_data)
    trades_path = results_dir / "plan_d_trades.csv"
    trades_df.to_csv(trades_path, index=False)
    print(f"Trade log saved to {trades_path}")

    # Per-symbol breakdown
    print("\n--- Per-Symbol Breakdown ---")
    for sym in sorted(ohlcv_dict.keys()):
        sym_trades = [t for t in result.trades if t.symbol == sym]
        if sym_trades:
            sym_pnl = sum(t.pnl for t in sym_trades)
            sym_wr = len([t for t in sym_trades if t.pnl > 0]) / len(sym_trades) * 100
            print(f"  {sym}: {len(sym_trades)} trades, PnL ${sym_pnl:.2f}, WR {sym_wr:.1f}%")
        else:
            print(f"  {sym}: 0 trades")


if __name__ == "__main__":
    main()
