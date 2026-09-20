# Implementation Plan: Harden Trading Strategies

**Branch**: `main` | **Date**: 2026-09-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-harden-trading-strategies/spec.md`

## Summary

Deliver a safety-first, paper-only trading foundation that makes execution, settlement accounting, portfolio exposure, and research results auditable before any strategy can be promoted. The first implementable slice fixes market routing, multi-leg recovery, paper fills, settlement idempotency, and live-mode guards. A deterministic portfolio replay engine then evaluates corrected 8–48-hour funding carry and a frozen hourly momentum hypothesis under identical data and cost assumptions. This is intentionally not HFT and not multi-week position trading. The work is explicitly allowed to conclude that neither strategy has a deployable edge.

## Technical Context

**Language/Version**: Go 1.25.4 for runtime, execution, risk, and canonical replay; Python 3 for statistical analysis and research reporting

**Primary Dependencies**: Existing Go interfaces plus `modernc.org/sqlite`, `testify`, Cobra/Viper, Prometheus; existing Python NumPy, pandas, SciPy, and scikit-learn stack for diagnostics only

**Storage**: SQLite in WAL mode for durable order/position/exposure/settlement state; immutable Parquet or SQLite dataset snapshots with cryptographic manifests; JSON/Parquet validation artifacts

**Testing**: Go unit, contract, integration, race, and replay tests; Python tests for statistical diagnostics; deterministic golden fixtures for market events and expected ledgers

**Target Platform**: Linux and Docker on a single host, paper mode only during this feature

**Project Type**: Multi-process trading services with a shared execution/risk core and offline research tools

**Performance Goals**: Correctness and deterministic replay take priority over throughput; one decision cycle completes after each closed one-hour bar; multi-leg state is durably recorded before the next transition; research replay handles the full retained dataset without manual intervention; no HFT/market-making latency target is in scope

**Constraints**: Never enable live trading, legacy directional ML, or unsupported strategies; never modify secrets or delete training data; funding must come from settlement events; close operations must not increase exposure; every empirical claim must link to reproducible artifacts

**Scale/Scope**: Initial Binance spot and USDT perpetual paper paths for BTCUSDT, ETHUSDT, SOLUSDT, and BNBUSDT; one-hour inputs, expected 6–24-hour ordinary holds, 48-hour planned maximum; one host with multiple strategy processes; cross-exchange execution, negative-funding spot shorts, and market making are deferred

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

The repository constitution is an unratified placeholder and contains no enforceable project principles. The following project-level gates from `AGENTS.md` therefore govern this plan:

- **PASS — Paper safety**: No task enables live mode; unapproved live starts are blocked before order submission.
- **PASS — ML safety**: The overfit directional ML filter remains disabled; HMM/regime models are quarantined.
- **PASS — Data preservation**: No task deletes or rewrites training/candle data; dataset snapshots are immutable.
- **PASS — Verification**: Go changes require `go build ./...` and `go test ./...`; Python changes require syntax checks plus task-relevant tests.
- **PASS — Feature parity**: No new ML feature is planned. Any future feature work remains subject to Go/Python parity.
- **PASS — Scope**: Funding carry and simple trend are hypotheses, not promised profit; zero eligible strategies is an accepted outcome.

Post-design re-check: **PASS**. The contracts and data model preserve all gates and add explicit eligibility enforcement.

## Project Structure

### Documentation (this feature)

```text
specs/001-harden-trading-strategies/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── execution.md
│   ├── research-artifacts.md
│   └── strategy-eligibility.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
internal/
├── testutil/
│   └── market.go
├── execution/
│   ├── engine.go
│   ├── market.go
│   ├── multi_leg.go
│   ├── paper.go
│   └── live.go
├── data/
│   ├── trading_store.go
│   └── migrations/
├── risk/
│   ├── manager.go
│   └── portfolio_ledger.go
├── backtest/
│   ├── engine_v2.go
│   ├── events.go
│   ├── fill_model.go
│   └── reporter_v2.go
└── strategy/
    ├── funding_arb/
    │   ├── strategy.go
    │   ├── carry.go
    │   └── settlement.go
    └── trend_candidate.go

scripts/
├── build_dataset_manifest.py
├── validate_strategy.py
├── deflated_sharpe.py
└── probability_backtest_overfit.py

research/
└── hypotheses/
    └── trend_carry_v1.yaml

internal/**/**_test.go
scripts/tests/
config.example.funding.yaml
config.example.trend.yaml
docs/STRATEGY_STATUS.md
```

**Structure Decision**: Keep Go as the canonical source for market events, order lifecycle, exposure, and strategy decisions so paper, replay, and eventual live paths share behavior. Python consumes immutable run artifacts only for statistical diagnostics; it does not independently reimplement order execution or strategy rules.

## Delivery Phases

### Phase A — Quarantine and Safety Baseline

- Add startup eligibility checks and mark funding, basis, market making, liquidation, mean reversion, cross-exchange, and ML regime paths research-only until their prerequisites pass.
- Correct status documentation so targets, simulated demonstrations, and empirical results are distinguishable.
- Add regression tests that reproduce the discovered zero-fill, wrong-market, extra-order, duplicate-settlement, and state-ownership defects.

### Phase B — Execution, Accounting, and Shared Risk Foundation

- Introduce explicit venue/market order requests and separate spot/perpetual paper adapters.
- Persist multi-leg state before and after every side effect; compensate incomplete transactions.
- Replace inferred funding accrual with idempotent authoritative settlements.
- Add a process-shared exposure ledger with atomic reservations and restart reconciliation.

### Phase C — Trustworthy Research Replay

- Build one global event stream for bars, quotes, fills, settlements, halts, and delistings.
- Enforce next-event fills for close-derived signals and declared conservative handling of ambiguous intrabar paths.
- Produce immutable trade, cost, exposure, daily-equity, hypothesis, and trial artifacts.
- Compute selection-aware statistics and reject synthetic or overlapping evidence from eligibility decisions.

### Phase D — Funding Carry Candidate

- Implement positive-funding long-spot/short-perpetual carry around the next one or two settlements from expected net settlement value, with a 48-hour planned maximum.
- Include four-leg transaction costs, borrow/financing assumptions, margin headroom, basis risk, and a safety buffer.
- Run deterministic historical replay and paper settlement reconciliation before considering paper eligibility.

### Phase E — Simple Trend and Combined Portfolio Candidate

- Freeze a 6/24/72-hour momentum ensemble, a 48-hour time stop, and volatility/covariance sizing policy before looking at results.
- Evaluate one objective RSI challenger and one algorithmically anchored Fibonacci challenger only after the baseline is frozen; charge both against the total trial count and reject them unless they add net out-of-sample value.
- Evaluate trend, carry, and an equal-risk combination on identical non-overlapping out-of-sample periods and stressed costs.
- Promote only candidates satisfying the machine-checkable gates; allow all candidates to be rejected.

### Phase F — Optional Dated-Futures Basis and Deferred Research

- Add delivery-futures basis only after contract metadata and time-to-expiry execution exist.
- Keep market making, liquidation, mean reversion, cross-exchange execution, sentiment alpha, and ML regime filters deferred behind strategy-specific research plans.

## Key Architectural Boundaries

1. **Decision boundary**: Strategies emit intents; they never call an untyped executor directly.
2. **Execution boundary**: Execution validates venue, market, eligibility, quantity, and reduce-only semantics before submission.
3. **Transaction boundary**: Multi-leg coordination owns transitions and compensation; strategies observe the resulting position.
4. **Accounting boundary**: Only fills and authoritative settlements change realized ledgers.
5. **Risk boundary**: A shared atomic exposure reservation precedes any first leg.
6. **Research boundary**: Canonical replay emits artifacts; statistical tooling reads but cannot mutate them.
7. **Promotion boundary**: Eligibility is derived from versioned evidence plus explicit operator approval; profitability is never guaranteed.
8. **Indicator boundary**: Familiarity or chart popularity is not evidence; RSI and Fibonacci remain isolated challengers unless incremental corrected evidence passes.
9. **Frequency boundary**: Strategies evaluate hourly but never trade merely to satisfy a daily quota; no sub-hour latency or HFT claim is permitted.

## Complexity Tracking

No constitution violations require justification. New abstractions are limited to boundaries needed to prevent the audited wrong-market, duplicated-accounting, and cross-process-risk failures.
