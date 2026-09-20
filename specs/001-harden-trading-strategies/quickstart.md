# Quickstart Validation Guide: Harden Trading Strategies

This guide describes the end-to-end checks the completed feature must support. Commands name the intended test targets; implementation arrives through `tasks.md`.

## Prerequisites

- Paper mode configuration only.
- Restored immutable historical candles, executable quotes, funding-rate observations, and funding settlements.
- No API secrets are required for deterministic replay.
- A writable temporary Go build cache and temporary test databases.

## 1. Safety and execution contract

```bash
GOCACHE=/tmp/quant-go-build-cache go test -race ./internal/execution ./internal/risk ./internal/data
```

Expected outcome:

- spot and perpetual requests reach distinct test adapters;
- market orders receive nonzero deterministic fills or explicit failures;
- partial/rejected second legs trigger compensation;
- close operations cannot increase exposure;
- restarts resume every nonterminal multi-leg transaction.

## 2. Funding settlement integrity

```bash
GOCACHE=/tmp/quant-go-build-cache go test -run 'TestFundingSettlement|TestFundingInterval|TestSettlementIdempotency' ./internal/strategy/funding_arb ./internal/data
```

Expected outcome:

- polling creates no realized income;
- each authoritative settlement is recorded exactly once;
- contract-specific interval changes alter forecasts without duplicating cash events.

## 3. Chronological replay and no-look-ahead

```bash
GOCACHE=/tmp/quant-go-build-cache go test -run 'TestGlobalChronology|TestNextEventFill|TestAmbiguousIntrabar|TestDelisting' ./internal/backtest
```

Expected outcome:

- events from all symbols are globally ordered;
- close-derived signals cannot fill at that close;
- ambiguous stop/target bars follow the declared conservative rule;
- delisting and missing-data fixtures affect equity as expected.

## 4. Reproducibility

```bash
go run ./cmd/backtest -c internal/backtest/testdata/funding_carry/config.yaml
go run ./cmd/backtest -c internal/backtest/testdata/funding_carry/config.yaml
python3 scripts/validate_strategy.py --compare-latest 2
```

Expected outcome: both run manifests reference the same inputs and produce identical ordered trades, costs, settlements, daily equity, and hashes.

## 5. Selection-aware statistics

```bash
python3 -m pytest scripts/tests/test_deflated_sharpe.py scripts/tests/test_probability_backtest_overfit.py
python3 scripts/validate_strategy.py --run-id RUN_ID
```

Expected outcome: the report includes all required metrics, trial count, DSR, PBO, concentration, and doubled-cost results. Known overfit fixtures fail.

## 6. Eligibility and live guard

```bash
GOCACHE=/tmp/quant-go-build-cache go test -run 'TestStrategyEligibility|TestLiveModeBlocked' ./internal/config ./internal/bot
```

Expected outcome:

- failed evidence produces `research_only` with reasons;
- passing research gates can produce `paper_eligible`;
- all live-start attempts remain blocked before submission.

## 7. RSI and Fibonacci challenger isolation

```bash
python3 scripts/validate_strategy.py --baseline trend-v1 --challenger rsi-v1
python3 scripts/validate_strategy.py --baseline trend-v1 --challenger fibonacci-v1
```

Expected outcome: each challenger has one frozen definition, identical out-of-sample periods and costs, incremental performance attribution, and an updated total trial count. A challenger that fails corrected base- and doubled-cost gates is recorded as rejected and does not alter the baseline.

## 8. Full quality gates

```bash
GOCACHE=/tmp/quant-go-build-cache go build ./...
GOCACHE=/tmp/quant-go-build-cache go test -race ./...
python3 -m pytest scripts/tests
python3 -c "import ast; from pathlib import Path; [ast.parse(p.read_text()) for p in Path('scripts').glob('*.py')]"
```

Expected outcome: all build, test, race, syntax, reconciliation, reproducibility, and eligibility checks pass. Passing engineering checks does not imply that a strategy passes its profitability evidence gates.
