#!/usr/bin/env python3
"""
Mean Reversion Strategy Backtest for Ranging Markets.

Strategy Rules:
- Entry: RSI(14) < 25 buy / > 75 sell on 4H candles, with BB(20,2) touch confirmation
- Exit: BB middle band touch or fixed 1R stop
- Regime gate: only active when ADX < 20
- Expected: 55-65% WR, 0.8-1.0 Sharpe

This strategy complements the trend following strategy by activating
when markets are ranging (ADX < 20).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Symbols to backtest - easily extensible
DEFAULT_SYMBOLS = {
    "BTC/USDT": "BTC_USDT_4h_2190d.parquet",
    "ETH/USDT": "ETH_USDT_4h_2190d.parquet",
    "SOL/USDT": "SOL_USDT_4h_2190d.parquet",
    "BNB/USDT": "BNB_USDT_4h_2190d.parquet",
    "NEAR/USDT": "NEAR_USDT_4h_2190d.parquet",
    "EGLD/USDT": "EGLD_USDT_4h_2190d.parquet",
    "XRP/USDT": "XRP_USDT_4h_2190d.parquet",
}

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
    stop_price: float  # 1R stop
    target_price: float  # BB middle band
    initial_risk_r: float  # dollar risk per unit (|entry - stop|)
    position_id: int = 0


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
    exit_reason: str  # "target", "stop", "end_of_data"
    fees: float = 0.0
    position_id: int = 0


@dataclass
class BacktestResult:
    equity_curve: list  # [(timestamp, equity), ...]
    trades: list[Trade]
    metrics: dict


# ---------------------------------------------------------------------------
# Technical Indicators
# ---------------------------------------------------------------------------


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI(period)."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_val = 100 - (100 / (1 + rs))
    return rsi_val


def bollinger_bands(
    df: pd.DataFrame, period: int = 20, std_dev: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate Bollinger Bands.

    Returns: (upper_band, middle_band, lower_band)
    """
    middle = df["close"].rolling(window=period).mean()
    std = df["close"].rolling(window=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper, middle, lower


def _true_range(df: pd.DataFrame) -> pd.Series:
    """True Range = max(H-L, |H-prev_C|, |L-prev_C|)."""
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift(1)).abs()
    lc = (df["low"] - df["close"].shift(1)).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1)


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate ADX(period).

    Returns: ADX series (0-100)
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    # Directional movement
    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr = _true_range(df)

    # Wilder smoothing (alpha = 1/period)
    alpha = 1.0 / period
    atr_smooth = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = (
        100
        * plus_dm.ewm(alpha=alpha, adjust=False).mean()
        / atr_smooth.replace(0, np.nan)
    )
    minus_di = (
        100
        * minus_dm.ewm(alpha=alpha, adjust=False).mean()
        / atr_smooth.replace(0, np.nan)
    )

    # DX and ADX
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = dx.ewm(alpha=alpha, adjust=False).mean()

    return adx_val


# ---------------------------------------------------------------------------
# Signal Generation
# ---------------------------------------------------------------------------


def generate_mean_reversion_signals(
    df: pd.DataFrame,
    rsi_period: int = 14,
    rsi_oversold: float = 30.0,  # Relaxed from 25
    rsi_overbought: float = 70.0,  # Relaxed from 75
    bb_period: int = 20,
    bb_std: float = 2.0,
    adx_period: int = 14,
    adx_threshold: float = 20.0,
    use_reversal_confirmation: bool = True,  # Wait for reversal candle
) -> pd.DataFrame:
    """Generate mean reversion signals for ranging markets.

    Entry conditions:
    - LONG: RSI < oversold (for prev bar) AND current bar is bullish (close > open)
            AND price was near or below BB lower AND ADX < threshold
    - SHORT: RSI > overbought (for prev bar) AND current bar is bearish (close < open)
             AND price was near or above BB upper AND ADX < threshold

    Returns DataFrame with:
        - signal: 1 (long), -1 (short), 0 (none)
        - rsi: RSI value
        - adx: ADX value
        - bb_upper, bb_middle, bb_lower: Bollinger Bands
        - entry_price: recommended entry price
    """
    # Calculate indicators
    rsi_val = rsi(df["close"], rsi_period)
    bb_upper, bb_middle, bb_lower = bollinger_bands(df, bb_period, bb_std)
    adx_val = adx(df, adx_period)

    # Candle direction
    bullish_candle = df["close"] > df["open"]
    bearish_candle = df["close"] < df["open"]

    # Price proximity to BB (within 0.5% of band)
    near_lower = df["low"] <= bb_lower * 1.005  # Within 0.5% of lower band
    near_upper = df["high"] >= bb_upper * 0.995  # Within 0.5% of upper band

    if use_reversal_confirmation:
        # Wait for reversal confirmation - RSI extreme on previous bar, reversal on current
        prev_rsi_oversold = rsi_val.shift(1) < rsi_oversold
        prev_rsi_overbought = rsi_val.shift(1) > rsi_overbought

        # Long: Previous RSI oversold + current bullish candle + near BB lower + ADX low
        long_condition = (
            prev_rsi_oversold & bullish_candle & near_lower & (adx_val < adx_threshold)
        )

        # Short: Previous RSI overbought + current bearish candle + near BB upper + ADX low
        short_condition = (
            prev_rsi_overbought
            & bearish_candle
            & near_upper
            & (adx_val < adx_threshold)
        )
    else:
        # Original: immediate entry on RSI extreme
        long_condition = (
            (rsi_val < rsi_oversold)
            & (df["low"] <= bb_lower)
            & (adx_val < adx_threshold)
        )

        short_condition = (
            (rsi_val > rsi_overbought)
            & (df["high"] >= bb_upper)
            & (adx_val < adx_threshold)
        )

    signal = pd.Series(0, index=df.index, dtype=int)
    signal[long_condition] = 1
    signal[short_condition] = -1

    # Build output
    result = pd.DataFrame(index=df.index)
    result["signal"] = signal
    result["rsi"] = rsi_val
    result["adx"] = adx_val
    result["bb_upper"] = bb_upper
    result["bb_middle"] = bb_middle
    result["bb_lower"] = bb_lower

    return result


# ---------------------------------------------------------------------------
# Backtester
# ---------------------------------------------------------------------------


class MeanReversionBacktester:
    """Event-driven mean reversion backtester."""

    def __init__(
        self,
        initial_equity: float = 10_000,
        risk_per_trade: float = 0.01,  # 1% risk per trade
        fee_rate: float = 0.0004,  # 0.04%
        slippage_bps: float = 5.0,  # 5 bps
        max_positions: int = 4,
        max_daily_loss: float = 0.03,  # 3% daily loss cap
        stop_mult: float = 1.5,  # Stop distance as multiple of BB width to middle
    ):
        self.initial_equity = initial_equity
        self.risk_per_trade = risk_per_trade
        self.fee_rate = fee_rate
        self.slippage_bps = slippage_bps
        self.max_positions = max_positions
        self.max_daily_loss = max_daily_loss
        self.stop_mult = stop_mult

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

    def _close_position(
        self, symbol: str, exit_price: float, exit_time: pd.Timestamp, reason: str
    ):
        """Close a position."""
        if symbol not in self.positions:
            return

        pos = self.positions[symbol]

        # Apply slippage to exit
        fill_price = self._apply_slippage(exit_price, pos.direction, is_exit=True)

        # PnL calculation
        raw_pnl = pos.direction * (fill_price - pos.entry_price) * pos.size
        entry_fees = self._calc_fees(pos.entry_price * pos.size)
        exit_fees = self._calc_fees(fill_price * pos.size)
        total_fees = entry_fees + exit_fees
        net_pnl = raw_pnl - total_fees

        # R-multiple (based on 1R stop distance)
        r_mult = 0.0
        if pos.initial_risk_r > 0:
            r_mult = (
                pos.direction * (fill_price - pos.entry_price)
            ) / pos.initial_risk_r

        pnl_pct = net_pnl / self.equity if self.equity > 0 else 0.0

        trade = Trade(
            symbol=symbol,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=fill_price,
            entry_time=pos.entry_time,
            exit_time=exit_time,
            size=pos.size,
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

        # Remove position
        del self.positions[symbol]

    def _check_exits(
        self,
        symbol: str,
        bar: pd.Series,
        signals: pd.DataFrame,
        timestamp: pd.Timestamp,
    ):
        """Check if position should exit on BB middle band touch or 1R stop."""
        if symbol not in self.positions:
            return

        pos = self.positions[symbol]
        bb_middle = signals.loc[timestamp, "bb_middle"]

        if pos.direction == 1:  # Long position
            # Exit on BB middle band touch (high >= middle) OR 1R stop hit (low <= stop)
            if bar["high"] >= bb_middle:
                self._close_position(symbol, bb_middle, timestamp, "target")
            elif bar["low"] <= pos.stop_price:
                self._close_position(symbol, pos.stop_price, timestamp, "stop")
        else:  # Short position
            # Exit on BB middle band touch (low <= middle) OR 1R stop hit (high >= stop)
            if bar["low"] <= bb_middle:
                self._close_position(symbol, bb_middle, timestamp, "target")
            elif bar["high"] >= pos.stop_price:
                self._close_position(symbol, pos.stop_price, timestamp, "stop")

    def _enter_position(
        self,
        symbol: str,
        direction: int,
        entry_price: float,
        entry_time: pd.Timestamp,
        stop_price: float,
        target_price: float,
    ):
        """Enter a new position with 1R stop."""
        # Calculate position size based on 1R risk
        risk_amount = self.equity * self.risk_per_trade
        stop_dist = abs(entry_price - stop_price)

        if stop_dist <= 0:
            return

        # Size = risk_amount / stop_distance (in base units)
        size = risk_amount / stop_dist

        # Cap by available equity (assume max 1x leverage for mean reversion)
        max_notional = self.equity
        max_size = max_notional / entry_price
        size = min(size, max_size)

        if size <= 0:
            return

        # Apply entry slippage
        fill_price = self._apply_slippage(entry_price, direction, is_exit=False)

        # Recalculate stop based on actual fill
        if direction == 1:  # long
            adjusted_stop = fill_price - stop_dist
        else:  # short
            adjusted_stop = fill_price + stop_dist

        pos = Position(
            symbol=symbol,
            direction=direction,
            entry_price=fill_price,
            entry_time=entry_time,
            size=size,
            stop_price=adjusted_stop,
            target_price=target_price,
            initial_risk_r=stop_dist,
            position_id=self._next_position_id,
        )
        self._next_position_id += 1
        self.positions[symbol] = pos

    def run(
        self,
        signals_dict: dict[str, pd.DataFrame],
        ohlcv_dict: dict[str, pd.DataFrame],
    ) -> BacktestResult:
        """Run backtest across all symbols."""
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

                # 1. Check exits for existing positions
                self._check_exits(sym, bar, sig_df, ts)

                # 2. Check for new entries (only if no position in this symbol)
                if self._is_halted():
                    continue
                if sym in self.positions:
                    continue
                if len(self.positions) >= self.max_positions:
                    continue

                signal = int(sig_row["signal"])
                if signal == 0:
                    continue

                # Entry price: use close for simplicity
                entry_price = bar["close"]

                # Calculate stop distance - use a fraction of distance to BB middle
                # This is tighter than going beyond the BB band
                bb_middle = sig_row["bb_middle"]
                bb_lower = sig_row["bb_lower"]
                bb_upper = sig_row["bb_upper"]

                if signal == 1:  # long
                    # Stop at some fraction toward the middle from entry
                    # Distance from entry to middle
                    dist_to_middle = bb_middle - entry_price
                    if dist_to_middle <= 0:
                        continue  # Already past middle, skip
                    # Risk is distance to middle times multiplier (stop wider than target)
                    stop_price = entry_price - self.stop_mult * dist_to_middle
                    target_price = bb_middle
                else:  # short
                    dist_to_middle = entry_price - bb_middle
                    if dist_to_middle <= 0:
                        continue  # Already past middle, skip
                    stop_price = entry_price + self.stop_mult * dist_to_middle
                    target_price = bb_middle

                self._enter_position(
                    symbol=sym,
                    direction=signal,
                    entry_price=entry_price,
                    entry_time=ts,
                    stop_price=stop_price,
                    target_price=target_price,
                )

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
                [
                    (trades[0].entry_time, self.initial_equity),
                    (trades[-1].exit_time, self.equity),
                ],
                columns=["timestamp", "equity"],
            )

        total_return = (self.equity - self.initial_equity) / self.initial_equity

        # Daily returns for Sharpe/Sortino
        eq_df = eq_df.set_index("timestamp").sort_index()
        eq_df = eq_df[~eq_df.index.duplicated(keep="last")]
        daily_eq = eq_df.resample("1D").last().dropna()
        daily_returns = daily_eq["equity"].pct_change().dropna()

        # Annualized Sharpe (crypto trades 365 days/year)
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

        # Trade stats
        pnls = [t.pnl for t in trades]
        winners = [p for p in pnls if p > 0]
        losers = [p for p in pnls if p <= 0]

        win_rate = len(winners) / len(pnls) if pnls else 0.0

        avg_winner = np.mean(winners) if winners else 0.0
        avg_loser = abs(np.mean(losers)) if losers else 0.0
        avg_wl_ratio = avg_winner / avg_loser if avg_loser > 0 else float("inf")

        profit_factor = (
            sum(winners) / abs(sum(losers))
            if losers and sum(losers) != 0
            else float("inf")
        )

        expectancy = np.mean(pnls) if pnls else 0.0
        expectancy_pct = expectancy / self.initial_equity * 100

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
        trade_df = pd.DataFrame(
            [{"exit_time": t.exit_time, "pnl": t.pnl} for t in trades]
        )
        if len(trade_df) > 0:
            trade_df = trade_df.set_index("exit_time")
            monthly = trade_df.resample("ME")["pnl"].sum()
            profitable_months = (monthly > 0).sum()
            total_months = len(monthly)
            profitable_months_pct = (
                profitable_months / total_months if total_months > 0 else 0.0
            )
        else:
            profitable_months_pct = 0.0

        total_fees = sum(t.fees for t in trades)

        # Exit reason breakdown
        exits_by_reason = {}
        for t in trades:
            reason = t.exit_reason
            exits_by_reason[reason] = exits_by_reason.get(reason, 0) + 1

        return {
            "total_return": total_return,
            "total_return_pct": total_return * 100,
            "cagr": cagr,
            "sharpe": sharpe,
            "sortino": sortino,
            "calmar": calmar,
            "max_drawdown": max_dd,
            "max_drawdown_pct": max_dd * 100,
            "win_rate": win_rate,
            "win_rate_pct": win_rate * 100,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "expectancy_pct": expectancy_pct,
            "avg_winner": avg_winner,
            "avg_loser": avg_loser,
            "avg_winner_loser_ratio": avg_wl_ratio,
            "avg_r_multiple": avg_r,
            "max_consecutive_losses": max_consec_loss,
            "num_trades": len(trades),
            "trades_per_month": trades_per_month,
            "profitable_months_pct": profitable_months_pct * 100,
            "total_fees": total_fees,
            "final_equity": self.equity,
            "exit_reasons": exits_by_reason,
        }


# ---------------------------------------------------------------------------
# Data Loading Helpers
# ---------------------------------------------------------------------------


def load_all_data(
    data_dir: Path = None, symbols: dict[str, str] = None
) -> dict[str, pd.DataFrame]:
    """Load OHLCV data for specified symbols.

    Args:
        data_dir: Path to data directory. Defaults to ../data_4h relative to script.
        symbols: Dictionary mapping symbol names to parquet filenames.
                Defaults to DEFAULT_SYMBOLS.

    Returns:
        Dictionary mapping symbol names to DataFrames.
    """
    if data_dir is None:
        data_dir = Path(__file__).resolve().parent.parent / "data_4h"

    if symbols is None:
        symbols = DEFAULT_SYMBOLS

    ohlcv_dict = {}

    for sym, fname in symbols.items():
        fpath = data_dir / fname
        if fpath.exists():
            ohlcv_dict[sym] = pd.read_parquet(fpath)
            print(f"  Loaded {sym}: {len(ohlcv_dict[sym]):,} bars")
        else:
            print(f"  Skipping {sym}: {fname} not found")

    return ohlcv_dict


def print_metrics(metrics: dict):
    """Pretty-print backtest metrics."""
    print()
    print("=" * 60)
    print("BACKTEST RESULTS — Mean Reversion Strategy")
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
    print(
        f"  Expectancy/trade:   ${metrics['expectancy']:.2f} ({metrics['expectancy_pct']:.3f}%)"
    )
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

    # Exit reason breakdown
    if "exit_reasons" in metrics and metrics["exit_reasons"]:
        print()
        print("  Exit breakdown:")
        for reason, count in sorted(metrics["exit_reasons"].items()):
            pct = count / metrics["num_trades"] * 100
            print(f"    {reason}: {count} ({pct:.1f}%)")

    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    print("Mean Reversion Strategy Backtest")
    print("=" * 60)
    print("Strategy: RSI(14) extremes + BB(20,2) touch + ADX < 20 filter")
    print("Entry: RSI < 30 (prev bar) + bullish candle + near BB band + ADX < 20")
    print("Exit: BB middle band touch OR stop (1x dist to middle)")
    print("=" * 60)

    # Load data
    print("\nLoading data...")
    ohlcv_dict = load_all_data()

    if not ohlcv_dict:
        print("ERROR: No OHLCV data found in data_4h/")
        sys.exit(1)

    # Generate signals for each symbol
    print("\nGenerating signals...")
    signals_dict = {}
    for sym, df in ohlcv_dict.items():
        signals = generate_mean_reversion_signals(
            df,
            rsi_oversold=30.0,  # Relaxed from 25
            rsi_overbought=70.0,  # Relaxed from 75
            use_reversal_confirmation=True,  # Wait for reversal candle
        )
        signals_dict[sym] = signals
        n_signals = (signals["signal"] != 0).sum()
        longs = (signals["signal"] == 1).sum()
        shorts = (signals["signal"] == -1).sum()
        print(f"  {sym}: {n_signals} signals ({longs} L / {shorts} S)")

    # Run backtest
    print("\nRunning backtest...")
    bt = MeanReversionBacktester(
        initial_equity=10_000,
        risk_per_trade=0.01,  # 1% per trade
        fee_rate=0.0004,
        slippage_bps=5.0,
        max_positions=4,
        max_daily_loss=0.03,
        stop_mult=1.0,  # Stop distance = 1x distance to middle (tighter stop)
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
    eq_path = results_dir / "mean_reversion_equity.csv"
    eq_df.to_csv(eq_path, index=False)
    print(f"\nEquity curve saved to {eq_path}")

    # Trade log
    trades_data = []
    for t in result.trades:
        trades_data.append(
            {
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
            }
        )
    trades_df = pd.DataFrame(trades_data)
    trades_path = results_dir / "mean_reversion_trades.csv"
    trades_df.to_csv(trades_path, index=False)
    print(f"Trade log saved to {trades_path}")

    # Per-symbol breakdown
    print("\n--- Per-Symbol Breakdown ---")
    for sym in sorted(ohlcv_dict.keys()):
        sym_trades = [t for t in result.trades if t.symbol == sym]
        if sym_trades:
            sym_pnl = sum(t.pnl for t in sym_trades)
            sym_wr = len([t for t in sym_trades if t.pnl > 0]) / len(sym_trades) * 100
            print(
                f"  {sym}: {len(sym_trades)} trades, PnL ${sym_pnl:.2f}, WR {sym_wr:.1f}%"
            )
        else:
            print(f"  {sym}: 0 trades")

    # Check against expectations
    print("\n--- Expectations Check ---")
    wr = result.metrics["win_rate_pct"]
    sharpe = result.metrics["sharpe"]

    wr_ok = 55 <= wr <= 65
    sharpe_ok = sharpe >= 0.8  # At least 0.8, higher is fine

    print(f"  Win rate:     {wr:.1f}% (expected: 55-65%) {'✅' if wr_ok else '❌'}")
    print(
        f"  Sharpe:       {sharpe:.2f} (expected: >= 0.8) {'✅' if sharpe_ok else '❌'}"
    )

    if wr_ok and sharpe_ok:
        print("\n  ✅ Strategy meets performance expectations!")
    else:
        print("\n  ⚠️  Strategy does not meet all expectations")
        print("     May need parameter tuning or additional filters")


if __name__ == "__main__":
    main()
