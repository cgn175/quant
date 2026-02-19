#!/usr/bin/env python3
"""
Plan D: Information Coefficient (IC) Analysis for Trend Following Strategy

Calculates the predictive edge of the Plan D entry signal:
- Donchian breakout (20-period) + EMA(50) trend filter

IC = Spearman correlation between signal and forward returns

Usage:
    python3 scripts/analyze_signal_ic.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from trend_signals import combined_entry_signal, DEFAULT_PARAMS


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def load_symbol_data(data_dir: Path, symbol: str) -> pd.DataFrame:
    """Load OHLCV data for a symbol from parquet or CSV."""
    # Try parquet first
    parquet_path = data_dir / f"{symbol}_USDT_4h_2190d.parquet"
    if parquet_path.exists():
        df = pd.read_parquet(parquet_path)
    else:
        # Try CSV fallback
        csv_path = data_dir / f"{symbol}_USDT_4h_2190d.csv"
        if csv_path.exists():
            df = pd.read_csv(csv_path, parse_dates=["timestamp"], index_col="timestamp")
        else:
            raise FileNotFoundError(f"No data found for {symbol}")
    
    # Ensure proper column naming
    df.columns = [c.lower() for c in df.columns]
    return df


def load_all_data(symbols: list[str], data_dir: Path = None) -> dict[str, pd.DataFrame]:
    """Load OHLCV data for all specified symbols."""
    if data_dir is None:
        data_dir = Path(__file__).resolve().parent.parent / "data_4h"
    
    data_dict = {}
    for sym in symbols:
        try:
            df = load_symbol_data(data_dir, sym)
            data_dict[sym] = df
            print(f"  Loaded {sym}: {len(df):,} bars ({df.index[0].date()} to {df.index[-1].date()})")
        except FileNotFoundError as e:
            print(f"  Warning: {e}")
    
    return data_dict


# ---------------------------------------------------------------------------
# Signal & IC Calculation
# ---------------------------------------------------------------------------

def calculate_plan_d_signal(df: pd.DataFrame, params: dict = None) -> pd.Series:
    """
    Calculate Plan D entry signal:
    - Donchian breakout (20-period)
    - EMA trend filter (50-period)
    
    Signal: 1 (LONG), -1 (SHORT), 0 (no signal)
    """
    if params is None:
        params = DEFAULT_PARAMS
    
    return combined_entry_signal(
        df,
        donchian_period=params["donchian_period"],
        ema_trend_period=params["ema_trend_period"]
    )


def calculate_forward_returns(df: pd.DataFrame, periods: int = 1) -> pd.Series:
    """
    Calculate forward returns for the next N bars.
    
    Forward return = (future_close - current_close) / current_close
    """
    # Shift(-N) looks N bars ahead
    future_close = df["close"].shift(-periods)
    forward_return = (future_close - df["close"]) / df["close"]
    return forward_return


def calculate_ic_analysis(
    df: pd.DataFrame,
    signal: pd.Series,
    forward_periods: list[int] = None,
) -> dict:
    """
    Calculate IC (Information Coefficient) statistics.
    
    Returns dict with:
        - ic: Spearman correlation
        - t_stat: t-statistic
        - p_value: p-value from t-test
        - n_obs: number of observations
        - significant: boolean (|IC| > 0.02 AND t-stat > 2)
    """
    if forward_periods is None:
        forward_periods = [1]  # Default: next bar (4H)
    
    results = {}
    
    for fp in forward_periods:
        # Calculate forward returns
        fwd_returns = calculate_forward_returns(df, periods=fp)
        
        # Create analysis dataframe
        analysis_df = pd.DataFrame({
            "signal": signal,
            "forward_return": fwd_returns,
        }).dropna()
        
        # Filter to only signal bars (where signal != 0)
        signal_df = analysis_df[analysis_df["signal"] != 0].copy()
        
        if len(signal_df) < 30:
            results[fp] = {
                "ic": np.nan,
                "t_stat": np.nan,
                "p_value": np.nan,
                "n_obs": len(signal_df),
                "significant": False,
                "error": "Insufficient observations (< 30)"
            }
            continue
        
        # Calculate Spearman correlation (IC)
        ic, p_value = stats.spearmanr(
            signal_df["signal"], 
            signal_df["forward_return"]
        )
        
        # Calculate t-statistic: IC * sqrt(n) / sqrt(1 - IC^2)
        n = len(signal_df)
        if abs(ic) >= 1.0:
            t_stat = np.inf if ic > 0 else -np.inf
        else:
            t_stat = ic * np.sqrt(n) / np.sqrt(1 - ic**2)
        
        # Determine significance
        significant = (abs(ic) > 0.02) and (abs(t_stat) > 2.0)
        
        results[fp] = {
            "ic": ic,
            "t_stat": t_stat,
            "p_value": p_value,
            "n_obs": n,
            "significant": significant,
        }
    
    return results


def calculate_ic_by_year(
    df: pd.DataFrame,
    signal: pd.Series,
    forward_periods: int = 1,
) -> pd.DataFrame:
    """
    Calculate IC statistics broken down by year to check stability.
    """
    # Create analysis dataframe
    fwd_returns = calculate_forward_returns(df, periods=forward_periods)
    
    analysis_df = pd.DataFrame({
        "signal": signal,
        "forward_return": fwd_returns,
    }, index=df.index)
    
    analysis_df["year"] = analysis_df.index.year
    
    # Filter to signal bars only
    signal_df = analysis_df[analysis_df["signal"] != 0].dropna()
    
    yearly_results = []
    
    for year, grp in signal_df.groupby("year"):
        if len(grp) < 10:  # Skip years with too few signals
            continue
        
        ic, p_value = stats.spearmanr(grp["signal"], grp["forward_return"])
        n = len(grp)
        
        if abs(ic) >= 1.0:
            t_stat = np.inf if ic > 0 else -np.inf
        else:
            t_stat = ic * np.sqrt(n) / np.sqrt(1 - ic**2) if abs(ic) < 0.999 else np.nan
        
        yearly_results.append({
            "year": year,
            "ic": ic,
            "t_stat": t_stat,
            "p_value": p_value,
            "n_obs": n,
            "significant": (abs(ic) > 0.02) and (abs(t_stat) > 2.0) if not np.isnan(t_stat) else False,
            "n_longs": (grp["signal"] == 1).sum(),
            "n_shorts": (grp["signal"] == -1).sum(),
        })
    
    return pd.DataFrame(yearly_results).sort_values("year")


def calculate_long_short_separate_ic(
    df: pd.DataFrame,
    signal: pd.Series,
    forward_periods: int = 1,
) -> dict:
    """
    Calculate edge separately for LONG and SHORT signals.
    Uses one-sample t-test of returns (vs 0) rather than correlation
    since signal is constant within each group.
    """
    fwd_returns = calculate_forward_returns(df, periods=forward_periods)
    
    analysis_df = pd.DataFrame({
        "signal": signal,
        "forward_return": fwd_returns,
    }).dropna()
    
    results = {}
    
    for direction, label in [(1, "LONG"), (-1, "SHORT")]:
        dir_df = analysis_df[analysis_df["signal"] == direction]
        
        if len(dir_df) < 10:
            results[label] = {
                "mean_return": np.nan,
                "std_return": np.nan,
                "t_stat": np.nan,
                "p_value": np.nan,
                "n_obs": len(dir_df),
                "significant": False,
                "error": "Insufficient observations"
            }
            continue
        
        returns = dir_df["forward_return"]
        
        # For shorts: we expect negative returns to be profitable
        # So we negate returns to test if mean < 0
        if direction == -1:
            returns = -returns
        
        # One-sample t-test: H0: mean return = 0
        mean_return = returns.mean()
        std_return = returns.std()
        n = len(returns)
        
        # t-statistic for one-sample t-test
        t_stat = mean_return / (std_return / np.sqrt(n)) if std_return > 0 else 0
        
        # Two-tailed p-value
        p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1)) if std_return > 0 else 1.0
        
        results[label] = {
            "mean_return": mean_return if direction == 1 else -mean_return,  # Report actual return
            "std_return": std_return,
            "t_stat": t_stat,
            "p_value": p_value,
            "n_obs": n,
            "significant": abs(t_stat) > 2.0,
        }
    
    return results


# ---------------------------------------------------------------------------
# Analysis & Reporting
# ---------------------------------------------------------------------------

def print_ic_results(symbol: str, results: dict, yearly_df: pd.DataFrame = None, 
                     ls_results: dict = None):
    """Pretty-print IC analysis results."""
    print()
    print("=" * 70)
    print(f"IC ANALYSIS: {symbol}")
    print("=" * 70)
    
    # Overall IC results
    print("\n--- Overall IC Statistics ---")
    print(f"{'Forward':<12} {'IC':>10} {'t-stat':>10} {'p-value':>10} {'n_obs':>8} {'Significant':<12}")
    print("-" * 70)
    
    for fp, res in sorted(results.items()):
        fp_label = f"{fp*4}H" if fp < 6 else f"{fp*4//24}D"
        sig_marker = "✅ YES" if res.get("significant") else "❌ NO"
        error = res.get("error", "")
        
        if error:
            print(f"{fp_label:<12} {error}")
        else:
            print(f"{fp_label:<12} {res['ic']:>+10.4f} {res['t_stat']:>+10.2f} "
                  f"{res['p_value']:>10.4f} {res['n_obs']:>8} {sig_marker:<12}")
    
    # Long/Short breakdown
    if ls_results:
        print("\n--- Directional Edge (Long vs Short) ---")
        print(f"{'Direction':<10} {'Mean Ret':>12} {'t-stat':>10} {'n_obs':>8} {'Significant':<12}")
        print("-" * 60)
        for direction, res in ls_results.items():
            if "error" in res:
                print(f"{direction:<10} {res['error']}")
            else:
                sig_marker = "✅ YES" if res.get("significant") else "❌ NO"
                print(f"{direction:<10} {res['mean_return']:>+12.4f} {res['t_stat']:>+10.2f} "
                      f"{res['n_obs']:>8} {sig_marker:<12}")
    
    # Yearly breakdown
    if yearly_df is not None and not yearly_df.empty:
        print("\n--- IC by Year (Stability Check) ---")
        print(f"{'Year':<8} {'IC':>10} {'t-stat':>10} {'n_obs':>8} {'Signif':<8} {'Signals (L/S)':<20}")
        print("-" * 70)
        
        positive_years = 0
        significant_years = 0
        
        for _, row in yearly_df.iterrows():
            sig_marker = "✅" if row["significant"] else "❌"
            if row["ic"] > 0:
                positive_years += 1
            if row["significant"]:
                significant_years += 1
            
            signal_str = f"{row['n_longs']}/{row['n_shorts']}"
            print(f"{int(row['year']):<8} {row['ic']:>+10.4f} {row['t_stat']:>+10.2f} "
                  f"{int(row['n_obs']):>8} {sig_marker:<8} {signal_str:<20}")
        
        total_years = len(yearly_df)
        print("-" * 70)
        print(f"Positive IC: {positive_years}/{total_years} years ({positive_years/total_years*100:.1f}%)")
        print(f"Significant: {significant_years}/{total_years} years ({significant_years/total_years*100:.1f}%)")


def print_aggregate_results(all_results: dict):
    """Print aggregate IC results across all symbols."""
    print()
    print("=" * 70)
    print("AGGREGATE IC RESULTS ACROSS ALL SYMBOLS")
    print("=" * 70)
    
    # Collect IC values from 4H forward returns
    ic_values = []
    t_stats = []
    n_obs_total = 0
    significant_count = 0
    
    for sym, data in all_results.items():
        if 1 in data["ic_results"] and "ic" in data["ic_results"][1]:
            res = data["ic_results"][1]
            if not np.isnan(res["ic"]):
                ic_values.append(res["ic"])
                t_stats.append(res["t_stat"])
                n_obs_total += res["n_obs"]
                if res["significant"]:
                    significant_count += 1
    
    if not ic_values:
        print("No valid IC results to aggregate.")
        return
    
    print(f"\nSymbols analyzed: {len(ic_values)}")
    print(f"Total observations: {n_obs_total:,}")
    print(f"\nMean IC: {np.mean(ic_values):+.4f}")
    print(f"Median IC: {np.median(ic_values):+.4f}")
    print(f"IC Std Dev: {np.std(ic_values):.4f}")
    print(f"Mean |IC|: {np.mean(np.abs(ic_values)):.4f}")
    print(f"\nMean t-stat: {np.mean(t_stats):+.2f}")
    print(f"Median t-stat: {np.median(t_stats):+.2f}")
    print(f"Symbols with significant IC: {significant_count}/{len(ic_values)}")


def print_final_conclusion(all_results: dict, aggregate_ic: float = None):
    """Print final conclusion on signal edge."""
    print()
    print("=" * 70)
    print("FINAL CONCLUSION")
    print("=" * 70)
    
    # Collect all 4H IC results
    ic_4h_list = []
    significant_symbols = []
    
    for sym, data in all_results.items():
        if 1 in data["ic_results"] and "ic" in data["ic_results"][1]:
            res = data["ic_results"][1]
            if not np.isnan(res["ic"]):
                ic_4h_list.append((sym, res["ic"], res["t_stat"], res["significant"]))
                if res["significant"]:
                    significant_symbols.append(sym)
    
    if not ic_4h_list:
        print("\n❌ INSUFFICIENT DATA")
        print("   Could not calculate IC for any symbols.")
        return
    
    # Calculate statistics
    ics = [x[1] for x in ic_4h_list]
    mean_ic = np.mean(ics)
    median_ic = np.median(ics)
    
    print(f"\nPlan D Signal: Donchian(20) + EMA(50) Trend Filter")
    print(f"Forward Return: 4H (next candle)")
    print()
    print(f"Mean IC: {mean_ic:+.4f}")
    print(f"Median IC: {median_ic:+.4f}")
    print(f"Symbols with significant edge: {len(significant_symbols)}/{len(ic_4h_list)}")
    
    if significant_symbols:
        print(f"   Edge found in: {', '.join(significant_symbols)}")
    
    # Per-symbol breakdown
    print("\nPer-Symbol IC:")
    for sym, ic, t_stat, sig in sorted(ic_4h_list, key=lambda x: x[1], reverse=True):
        status = "✅ EDGE" if sig else "❌ NO EDGE"
        print(f"   {sym:12s} IC={ic:+.4f} t={t_stat:+6.2f} {status}")
    
    # Final verdict
    print()
    print("-" * 70)
    
    # Criteria for edge:
    # 1. Mean |IC| > 0.02 (standard quant threshold)
    # 2. At least one symbol has significant IC
    # 3. Majority of symbols have positive IC
    
    positive_ics = sum(1 for ic in ics if ic > 0)
    has_edge = (
        abs(mean_ic) > 0.02 and 
        len(significant_symbols) > 0 and
        positive_ics >= len(ics) / 2
    )
    
    if has_edge:
        print("🟢 SIGNAL HAS EDGE")
        print()
        print("   The Plan D signal demonstrates statistically significant")
        print("   predictive power (IC > 0.02, t-stat > 2).")
        print()
        print("   Recommendation: Continue development with focus on:")
        print("   - Entry timing refinement")
        print("   - Exit optimization")
        print("   - Position sizing improvements")
    else:
        print("🔴 SIGNAL HAS NO EDGE - RECOMMEND SHUTTING DOWN")
        print()
        if abs(mean_ic) <= 0.02:
            print(f"   Mean IC ({mean_ic:+.4f}) below threshold (0.02)")
        if len(significant_symbols) == 0:
            print(f"   No symbols show statistically significant predictive power")
        if positive_ics < len(ics) / 2:
            print(f"   Less than half of symbols ({positive_ics}/{len(ics)}) have positive IC")
        print()
        print("   The Plan D signal lacks predictive edge. The negative walk-forward")
        print("   results (-2.47 Sharpe, -93% return) are confirmed by this analysis.")
        print()
        print("   Recommendation:")
        print("   - STOP paper trading immediately")
        print("   - Do NOT proceed to live trading")
        print("   - Consider fundamental strategy redesign or abandonment")
    
    print("=" * 70)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("Plan D: Information Coefficient (IC) Analysis")
    print("=" * 70)
    print()
    print("Strategy: Donchian Breakout (20) + EMA(50) Trend Filter")
    print("Metric: Spearman correlation between signal and forward 4H returns")
    print()
    
    # Configuration
    symbols = ["BTC", "ETH", "SOL", "BNB"]
    forward_periods = [1, 2, 3, 6]  # 4H, 8H, 12H, 24H
    
    # Load data
    print("Loading data...")
    data_dir = Path(__file__).resolve().parent.parent / "data_4h"
    data_dict = load_all_data(symbols, data_dir)
    
    if not data_dict:
        print("ERROR: No data loaded!")
        sys.exit(1)
    
    # Analyze each symbol
    all_results = {}
    
    for sym, df in data_dict.items():
        print(f"\nAnalyzing {sym}...")
        
        # Calculate signal
        signal = calculate_plan_d_signal(df)
        
        # Count signals
        n_longs = (signal == 1).sum()
        n_shorts = (signal == -1).sum()
        print(f"   Signals: {n_longs:,} LONG, {n_shorts:,} SHORT")
        
        # Calculate IC analysis
        ic_results = calculate_ic_analysis(df, signal, forward_periods)
        
        # Calculate yearly breakdown
        yearly_df = calculate_ic_by_year(df, signal, forward_periods=1)
        
        # Calculate long/short separate analysis
        ls_results = calculate_long_short_separate_ic(df, signal, forward_periods=1)
        
        # Print results
        print_ic_results(sym, ic_results, yearly_df, ls_results)
        
        # Store for aggregate
        all_results[sym] = {
            "ic_results": ic_results,
            "yearly_df": yearly_df,
            "ls_results": ls_results,
        }
    
    # Print aggregate results
    print_aggregate_results(all_results)
    
    # Final conclusion
    print_final_conclusion(all_results)
    
    # Save detailed results to CSV
    results_dir = Path(__file__).resolve().parent.parent / "results"
    results_dir.mkdir(exist_ok=True)
    
    # Save per-symbol IC summary
    summary_rows = []
    for sym, data in all_results.items():
        if 1 in data["ic_results"]:
            res = data["ic_results"][1]
            if "ic" in res:
                summary_rows.append({
                    "symbol": sym,
                    "ic_4h": res.get("ic"),
                    "t_stat": res.get("t_stat"),
                    "p_value": res.get("p_value"),
                    "n_obs": res.get("n_obs"),
                    "significant": res.get("significant"),
                })
    
    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)
        summary_path = results_dir / "plan_d_ic_analysis.csv"
        summary_df.to_csv(summary_path, index=False)
        print(f"\nDetailed results saved to: {summary_path}")


if __name__ == "__main__":
    main()
