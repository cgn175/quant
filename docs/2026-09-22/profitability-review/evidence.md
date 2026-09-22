# Quant bot: audit of profitability evidence

Audit date: 2026-09-22. Scope: read-only review of committed results, strategy reports, and the code that produces them. I did not retrain models, run a full backtest, or alter market/trading data.

## Executive assessment for own capital below $1,000

There is no verified live or paper-trading net-PnL record in the checkout. The most auditable out-of-sample evidence is negative for the meta-label/ML strategy. Plan D has an attractive reported full-period result, but its raw trade/equity artifacts are absent, the positive walk-forward result is documented rather than independently reproducible from available artifacts here, and several “robustness” claims are in-sample. Funding arb and basis trade have no realized trades in the saved stats, and their example configurations require a $1,000 position each.

Decision implication: treat the bot as a research/paper system. For a sub-$1,000 account, Plan D is the only component that could plausibly be scaled down mechanically, but the repository does not yet prove positive net expectancy after actual fills. Do not infer that the advertised 8–40% annual targets are attainable with this account size.

## Five key findings

### 1. The saved OOS summaries provide adverse evidence for the historical ML/meta strategy

`results/walk_forward_summary.json:2-12` records 213 selected trades: 32.86% win rate, -0.4358% average net return per selected signal, profit factor 0.659, Sharpe -2.47, max drawdown 62.72%, and only 44.44% profitable months. The second run in `results_v2/walk_forward_summary.json:2-12` is worse: 181 trades, 21.55% win rate, -0.6830% average net return, profit factor 0.478, Sharpe -6.26, max drawdown 76.97%, and 33.33% profitable months.

The contemporaneous gate report confirms that Run 1 passed only the low-frequency criterion (1 of 7 gates), while Run 2 failed the other criteria and was worse (`docs/2026-02-08/PLAN_B_PROGRESS.md:112-183`). The second run has a particularly adverse tail: window 59 has 80 trades, 5% win rate, -106.6% summed trade returns, and PF 0.06 (`results_v2/walk_forward_summary.json:643-662`; report interpretation at `docs/2026-02-08/PLAN_B_PROGRESS.md:165-170`).

These are not direct account returns. `scripts/walk_forward.py:521-547` defines `overall_total_return` as the *sum* of per-trade returns, while max drawdown is computed from a compounded sequence. The walk-forward also subtracts only two 5-bps fees (`scripts/walk_forward.py:276-375`), with no slippage in that summary and no position-overlap/execution-capacity filter before appending all passing labels. Therefore the exact dollar loss for a $1,000 account cannot be inferred, but the sign and instability are sufficiently adverse to reject the ML filter until rebuilt.

### 2. Plan D has the best upside claim, but it is a report-level claim without raw proof in this checkout

`docs/2026-02-09/PLAN_D_PROGRESS.md:75-126` reports a six-year, four-symbol full backtest of +65.58% total return, 8.81% CAGR, Sharpe 2.25, 16.38% max drawdown, PF 1.40, 426 positions, and 47.9% profitable months. It also reports an OOS gate of 37.9% win rate, PF 1.43, Sharpe 1.61, 10.74% max drawdown, W/L 2.08, and 68.9% profitable windows (42/61), plus 36/36 parameter configurations profitable.

For scale, if the reported full-period CAGR were real and scalable, $1,000 implies about $88/year before tax and future decay; the reported 16.38% drawdown implies roughly $164 peak-to-trough. The +65.58% figure itself would be $656 cumulative on $1,000 over the stated six-year period, not $656 per year.

The raw `plan_d_*` equity/trade/walk-forward files are not present in `results/`; only the meta walk-forward summaries, a filter-ablation text file, and survivorship JSON are committed. Thus the Plan D numbers cannot currently be checked for timestamps, per-trade fills, benchmark, or exact OOS boundaries. The “100% robust” claim is also only a same-sample sweep: `scripts/param_sensitivity.py:35-47` defines the grid, and `scripts/param_sensitivity.py:243-266` counts profitable configurations from the combined sweep without a held-out period. A further audit flag is that `scripts/trend_signals.py:270-275` passes only `donchian_period` and `ema_trend_period` into the entry signal; the `ema_fast`/`ema_slow` values swept by `scripts/param_sensitivity.py:35-46` do not affect that main signal path. Treat Plan D as the leading hypothesis, not as validated profitability.

### 3. Filter ablation and momentum results show plausible mechanics but are not clean competitive evidence

The saved filter study reports, on 13,139 bars for BTC/ETH/BNB and 12,044 for SOL, baseline Sharpe 1.02 / PF 1.12 / +116.5% return over 1,823 trades versus “All filters” Sharpe 1.45 / PF 1.22 / +36.2% over 427 trades (`results/filter_ablation_1771110472.txt:5-32`). The implementation does model 0.04% fee per side and 5 bps slippage per side (`scripts/filter_ablation.py:166-190`; cost handling in `scripts/backtest_trend.py:133-184`). That is useful evidence that filters change risk/turnover, but it is not OOS despite the script docstring saying “OOS”: `scripts/filter_ablation.py:3-7` labels the study OOS, while `scripts/filter_ablation.py:158-190` loads the whole data set, generates all signals, and runs each variant on that same period. The filter choice is therefore exposed to full-period selection bias.

The cross-sectional momentum report claims baseline 20.0% return / Sharpe 0.93 versus filtered 18.4% / Sharpe 1.05 over 2,616 versus 1,908 trades (`docs/2026-02-19/PHASE_2_MOMENTUM_RESULTS.md:29-64`). Its underlying backtest has no fee or slippage model (`scripts/backtest_momentum.py:84-165`), and its Sharpe is computed from per-trade returns with `sqrt(252)` (`scripts/backtest_momentum.py:238-265`), not from an executable equity curve. This result is not comparable to Plan D or to a live small-account return.

### 4. Small-account economics are only partially modeled, and the arb configs do not fit the stated capital

The Plan D Python engine charges 0.04% per side and 5 bps slippage per side by default (`scripts/backtest_trend.py:89-98`, `:133-184`), and the entry is filled at the same bar’s close after the signal is computed (`scripts/backtest_trend.py:367-388`). The same-bar close assumption can be optimistic relative to a next-open order. Funding data is used to filter/scale signals (`scripts/trend_signals.py:180-221`, `:286-299`), but the trend backtester’s close path only charges entry/exit fees (`scripts/backtest_trend.py:176-184`); it does not book funding payments, borrow, or spot/perp hedge costs. At sub-$1,000 equity, a 1% risk budget is at most $10 per position; a round-trip fee plus modeled slippage is about 0.18% of notional, so a $333 notional position costs about $0.60 and a $1,000 notional position costs about $1.80 before funding or spread. This is 6–18% of the nominal $10 risk budget, depending on stop width.

Funding arb and basis trade are not capital-compatible as shipped: `config.example.funding.yaml:13-23` sets `position_size_usd: 1000` and `delta_neutral: false`, while `config.example.basis.yaml:13-39` also sets `position_size_usd: 1000`. The saved funding-arb snapshots show zero trades and zero PnL at three timestamps (`stats_funding_arb_1771102578.json:2-10`, `stats_funding_arb_1771103057.json:2-10`, `stats_funding_arb_1771103545.json:2-10`). The repository therefore contains no realized evidence that either carry strategy clears fees at the user’s capital level.

### 5. Survivorship/stress artifacts and paper status do not establish realized profitability

The survivorship JSON is directionally valuable as a warning: survivor-only output is +$3,500 net with Sharpe 0.85 and 25% drawdown, while the “full” universe is -$2,100 net, Sharpe 0.627, -5.25% CAGR, 41.41% drawdown, and 21 delisted trades (`results/survivorship_bias_analysis.json:23-66`). But the generator explicitly describes its default as a simplified demonstration (`scripts/backtest_with_survivorship.py:198-207`), and unless `--use-go-backtest` is passed it uses simulated results (`scripts/backtest_with_survivorship.py:430-468`). Dead-coin paths are synthesized when historical data is unavailable (`scripts/fetch_dead_coin_data.py:242-249`, `:390-411`). Use this as a bias warning, not as a measured PnL result.

Likewise, the stress report says 12/12 scenarios survived and 0.6% max drawdown (`docs/2026-02-19/STRESS_TEST_RESULT.md:20-36`), but the test assumes a single long position, fixed 3% stop, fixed 2x leverage, and a simplified equity calculation (`scripts/stress_test.py:83-159`). It does not run the actual multi-symbol Plan D engine, model fees/slippage/gaps, or demonstrate positive returns. Finally, the system status remains paper-only (`docs/STRATEGY_STATUS.md:1-5`) and its paper performance targets are still marked TBD (`docs/STRATEGY_STATUS.md:336-343`).

## Evidence ledger

| Component | Best evidence in checkout | Net-cost treatment | Confidence for own-capital profitability |
|---|---|---|---|
| ML/meta-label trend filter | Two raw walk-forward JSON summaries, both negative | Fees only in summary; no slippage; no execution overlap | **Negative evidence; reject for now** |
| Plan D pure trend | Reported +65.58% full period and positive reported OOS gate | Python engine models fee/slippage, but raw outputs absent and same-bar close entry | **Promising hypothesis, unverified** |
| Filter ablation | Raw text, +36.2% all-filter result | Fee/slippage modeled | **In-sample only** |
| Cross-sectional momentum | Reported Sharpe improvement | No fee/slippage in underlying script | **Not decision-grade** |
| Funding arb | Three saved snapshots | No trades | **No evidence** |
| Basis trade / market making / liquidation | Design docs and configs; no realized result artifact | Not demonstrated | **No evidence** |

## Minimum proof required before risking <$1,000

1. Recreate Plan D from immutable input snapshots and save per-trade/equity artifacts with signal timestamp, next-bar fill, fees, spread/slippage, and any funding/borrow cash flow.
2. Report both a true compounded account curve and unlevered BTC buy-and-hold benchmark; do not use summed trade returns as account return.
3. Enforce one-position-per-symbol and capital constraints during walk-forward; report non-overlapping trades and confidence intervals/bootstrap by non-overlapping test periods.
4. Run at least 8–12 weeks of paper execution with actual Binance fee tier, observed spread/slippage, order rejection/minimum-notional behavior, and a separate ledger for each strategy. Keep ML disabled until it beats the ADX/Plan D control after costs.
5. Before future eligibility, verify both hedge legs, settlement accounting, actual fees and available collateral end-to-end; only then evaluate sizes compatible with the account. Merely enabling a hedge flag is insufficient. No configuration was changed in this audit.
