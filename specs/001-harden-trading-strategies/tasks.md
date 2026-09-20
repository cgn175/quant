---

description: "Dependency-ordered implementation tasks for hardening strategy execution and validation"
---

# Tasks: Harden Trading Strategies

**Input**: Design documents from `/specs/001-harden-trading-strategies/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Required. For behavior changes, add the named test first and confirm that it fails for the audited defect before implementing the fix.

**Organization**: Tasks are grouped by user story so each stage has an independently testable stop point. Profit is not an implementation acceptance condition; zero eligible strategies is valid.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel with adjacent marked tasks because it targets different files and has no dependency on their incomplete output.
- **[Story]**: Maps work to a user story in `spec.md`.
- Every task includes an exact file path.

## Phase 1: Setup and Test Scaffolding

**Purpose**: Establish artifact locations and deterministic fixtures without changing trading behavior.

- [ ] T001 Add generated research-artifact and temporary test-database exclusions to `.gitignore`
- [ ] T002 [P] Add Python test dependencies and pinned statistical packages to `scripts/requirements.txt`
- [ ] T003 [P] Create deterministic spot, perpetual, funding, partial-fill, rejection, delisting, and data-gap fixture documentation in `internal/testutil/testdata/README.md`
- [ ] T004 Create reusable Go fixture builders for venue markets, ordered events, fills, and settlements in `internal/testutil/market.go`

---

## Phase 2: Foundational Contracts and Persistence

**Purpose**: Define shared types and additive storage required by every user story.

**⚠️ CRITICAL**: No strategy migration starts until this phase is complete.

- [ ] T005 Define validated `Venue`, `MarketType`, `Instrument`, `OrderIntent`, `OrderRequest`, `OrderEvent`, and `Fill` types from `contracts/execution.md` in `internal/execution/market.go`
- [ ] T006 [P] Define multi-leg states and transition validation matching `data-model.md` in `internal/execution/multi_leg_state.go`
- [ ] T007 [P] Define strategy eligibility statuses, evidence references, and gate-policy structures in `internal/config/eligibility.go`
- [ ] T008 Create additive trading-state schema for venue markets, transactions, legs, positions, settlements, exposure reservations, and eligibility in `internal/data/migrations/001_trading_state.sql`
- [ ] T009 Implement migration application and rollback-safe version tracking in `internal/data/migrations.go`
- [ ] T010 Implement transactional CRUD and optimistic version checks for the new state entities in `internal/data/trading_store.go`
- [ ] T011 Add schema, constraint, idempotency, and migration tests using a temporary database in `internal/data/trading_store_test.go`
- [ ] T012 Add contract serialization and transition-validation tests for foundational types in `internal/execution/market_test.go` and `internal/execution/multi_leg_state_test.go`

**Checkpoint**: Shared contracts persist and round-trip without changing existing strategy behavior.

---

## Phase 3: User Story 1 — Safe and Truthful Trading Runtime (Priority: P1) 🎯 MVP

**Goal**: Correct market routing, fills, recovery, settlement accounting, shared limits, and live-mode blocking.

**Independent Test**: Run the execution/risk/data race-test suites against full-fill, partial-fill, rejected-leg, unknown-order, restart, and duplicate-settlement fixtures; all exposure must be managed and all unapproved live starts must fail before submission.

### Tests for User Story 1

- [ ] T013 [P] [US1] Add failing spot-versus-perpetual routing contract tests in `internal/execution/routing_test.go`
- [ ] T014 [P] [US1] Add failing nonzero market-fill, next-quote fill, partial-limit-fill, and fee tests in `internal/execution/paper_test.go`
- [ ] T015 [P] [US1] Add failing second-leg rejection, timeout, unknown-order, compensation, and reduce-only tests in `internal/execution/multi_leg_test.go`
- [ ] T016 [P] [US1] Add failing crash/restart recovery and cross-strategy ownership tests in `internal/data/trading_recovery_test.go`
- [ ] T017 [P] [US1] Add failing atomic total, symbol, correlation, expiry, and concurrent-reservation tests in `internal/risk/portfolio_ledger_test.go`
- [ ] T018 [P] [US1] Add failing settlement idempotency and polling-does-not-create-income tests in `internal/data/funding_settlement_test.go`
- [ ] T019 [P] [US1] Add failing research-only and live-mode startup guard tests in `internal/bot/eligibility_test.go`

### Implementation for User Story 1

- [ ] T020 [US1] Refactor the executor boundary to require explicit venue and market requests while retaining a temporary compatibility adapter in `internal/execution/engine.go`
- [ ] T021 [US1] Implement deterministic bid/ask market fills, configurable latency, partial limit fills, and fill-attached fees in `internal/execution/paper.go`
- [ ] T022 [US1] Split Binance spot and perpetual capabilities behind typed market adapters and enforce reduce-only closes in `internal/execution/live.go`
- [ ] T023 [US1] Implement the persisted multi-leg coordinator, compensation policy, and unknown-order reconciliation in `internal/execution/multi_leg.go`
- [ ] T024 [US1] Implement process-shared atomic exposure reservation, consumption, release, and expiry in `internal/risk/portfolio_ledger.go`
- [ ] T025 [US1] Implement restart reconciliation that compares nonterminal transactions and positions with executor state before enabling entries in `internal/execution/reconcile.go`
- [ ] T026 [US1] Implement idempotent authoritative funding-settlement ingestion without rate-poll accrual in `internal/data/funding_settlement.go`
- [ ] T027 [US1] Enforce `research_only`, `paper_eligible`, `live_eligible`, and `suspended` startup behavior, with live always blocked for this feature, in `internal/bot/common.go`
- [ ] T028 [US1] Wire trading-state storage and the shared portfolio ledger into bot setup without modifying secrets in `internal/bot/common.go`
- [ ] T029 [P] [US1] Add transaction state, delta mismatch, compensation, settlement discrepancy, and eligibility metrics in `internal/metrics/prometheus.go`
- [ ] T030 [US1] Remove the legacy assumption that submitting an order implies a filled position in `internal/execution/engine.go`
- [ ] T031 [US1] Run and document the User Story 1 race and recovery checkpoint in `specs/001-harden-trading-strategies/quickstart.md`

**Checkpoint**: The runtime is safe and truthful in paper mode even if no strategy is profitable or eligible.

---

## Phase 4: User Story 2 — Reproducible and Unbiased Strategy Validation (Priority: P2)

**Goal**: Produce deterministic, globally chronological, cost-complete, selection-aware strategy evidence.

**Independent Test**: Replay the same frozen fixture twice and obtain identical order, fill, settlement, position, daily-equity, and hash artifacts; known look-ahead, overlap, synthetic-evidence, and missing-cost fixtures must fail validation.

### Tests for User Story 2

- [ ] T032 [P] [US2] Add failing global chronology, stable same-time priority, and missing-symbol timestamp tests in `internal/backtest/events_test.go`
- [ ] T033 [P] [US2] Add failing next-event entry, bid/ask execution, and no-same-close-fill tests in `internal/backtest/fill_model_test.go`
- [ ] T034 [P] [US2] Add failing ambiguous intrabar, delisting, halt, funding, borrow, and doubled-cost tests in `internal/backtest/engine_v2_test.go`
- [ ] T035 [P] [US2] Add failing deterministic manifest and two-run artifact hash tests in `internal/backtest/reproducibility_test.go`
- [ ] T036 [P] [US2] Add known-distribution tests for Deflated Sharpe calculations in `scripts/tests/test_deflated_sharpe.py`
- [ ] T037 [P] [US2] Add known-overfit and low-overfit matrix tests for PBO calculations in `scripts/tests/test_probability_backtest_overfit.py`
- [ ] T038 [P] [US2] Add validator tests that reject overlapping OOS periods, missing trial counts, synthetic evidence, and incomplete artifacts in `scripts/tests/test_validate_strategy.py`

### Implementation for User Story 2

- [ ] T039 [US2] Define immutable bar, quote, fill, settlement, borrow, halt, and delisting events with stable ordering in `internal/backtest/events.go`
- [ ] T040 [US2] Implement a global multi-symbol event merge and replay loop using canonical strategy and execution boundaries in `internal/backtest/engine_v2.go`
- [ ] T041 [US2] Implement next-event bid/ask/depth fill rules and conservative ambiguous-intrabar handling in `internal/backtest/fill_model.go`
- [ ] T042 [US2] Emit order, fill, fee, settlement, position, exposure, trade, and daily-equity ledgers from replay in `internal/backtest/reporter_v2.go`
- [ ] T043 [US2] Inventory retained data, safely reacquire missing one-hour candles/quotes/funding history without overwriting training databases, and add immutable hashing, universe metadata, gap/duplicate checks, prior-inspection labels, and synthetic labeling in `scripts/build_dataset_manifest.py`
- [ ] T044 [P] [US2] Implement Deflated Sharpe Ratio with sample length, skew, kurtosis, and trial-count inputs in `scripts/deflated_sharpe.py`
- [ ] T045 [P] [US2] Implement combinatorially symmetric PBO calculation and diagnostics in `scripts/probability_backtest_overfit.py`
- [ ] T046 [US2] Implement manifest validation, base/doubled-cost comparison, concentration analysis, DSR/PBO reporting, exploratory-versus-confirmatory period enforcement, and invalid-run reasons in `scripts/validate_strategy.py`
- [ ] T047 [US2] Wire the v2 replay and artifact output into an explicit command path without silently using the legacy engine in `cmd/backtest/main.go`
- [ ] T048 [US2] Mark the default survivorship report as demonstration-only and prevent its simulated output from entering eligibility evaluation in `scripts/backtest_with_survivorship.py`
- [ ] T049 [US2] Add a point-in-time universe and delisting metadata contract to `docs/BACKTEST_DATA_REQUIREMENTS.md`
- [ ] T050 [US2] Run the reproducibility checkpoint twice and record artifact identifiers and hashes in `specs/001-harden-trading-strategies/quickstart.md`

**Checkpoint**: Strategy evidence is reproducible and can credibly reject a hypothesis.

---

## Phase 5: User Story 3 — Correct Delta-Neutral Funding Carry (Priority: P3)

**Goal**: Evaluate and paper-trade positive-funding long-spot/short-perpetual carry based on net expected settlement value.

**Independent Test**: Historical settlement/quote replay and paper scenarios produce equal-delta spot/perpetual legs, exact settlement cash, complete four-leg costs, compensation on leg failure, and no negative-funding entry without modeled borrow.

### Tests for User Story 3

- [ ] T051 [P] [US3] Add failing net-carry calculations for fees, spread, slippage, financing, basis buffer, and safety margin in `internal/strategy/funding_arb/carry_test.go`
- [ ] T052 [P] [US3] Add failing contract-specific interval, next-settlement, cap, and interval-change tests in `internal/strategy/funding_arb/settlement_test.go`
- [ ] T053 [P] [US3] Add failing positive-funding entry, negative-funding rejection, delta tolerance, one/two-settlement holding, and 48-hour time-stop tests in `internal/strategy/funding_arb/strategy_test.go`
- [ ] T054 [P] [US3] Add failing end-to-end spot/perpetual partial-fill and restart scenarios in `internal/bot/funding_integration_test.go`
- [ ] T055 [P] [US3] Add historical hourly carry replay fixtures, replay configuration, actual settlements, and expected ledgers in `internal/backtest/testdata/funding_carry/manifest.json` and `internal/backtest/testdata/funding_carry/config.yaml`

### Implementation for User Story 3

- [ ] T056 [US3] Implement expected net carry over the next one or two authoritative settlements, complete lifecycle costs, and a 48-hour planned maximum in `internal/strategy/funding_arb/carry.go`
- [ ] T057 [US3] Implement contract metadata refresh and settlement schedule handling without fixed three-payments-per-day assumptions in `internal/strategy/funding_arb/settlement.go`
- [ ] T058 [US3] Replace directional and inferred-accrual entry management with positive-funding neutral transaction intents in `internal/strategy/funding_arb/strategy.go`
- [ ] T059 [US3] Replace the single futures executor wiring with explicit Binance spot and perpetual paper adapters plus the multi-leg coordinator in `internal/bot/funding.go`
- [ ] T060 [US3] Migrate funding positions from ambiguous `arb_positions` ownership to typed transaction/position records in `internal/data/migrations/002_migrate_funding_positions.sql`
- [ ] T061 [US3] Add net-carry threshold, safety buffer, delta tolerance, financing, and eligibility settings while retaining `mode: paper` in `internal/config/config.go`
- [ ] T062 [US3] Update the funding example with paper-only corrected settings and remove unsupported return claims in `config.example.funding.yaml`
- [ ] T063 [US3] Add funding settlement, cost, delta mismatch, and rejected-opportunity attribution to run artifacts in `internal/backtest/reporter_v2.go`
- [ ] T064 [US3] Run the funding-carry replay and record pass/fail gate output without promoting on failure in `specs/001-harden-trading-strategies/quickstart.md`

**Checkpoint**: Funding carry has correct paper mechanics; it remains research-only unless empirical gates pass.

---

## Phase 6: User Story 4 — Simple Trend and Carry Portfolio Candidate (Priority: P4)

**Goal**: Test a frozen low-complexity trend hypothesis, isolated RSI/Fibonacci challengers, and an equal-risk trend/carry combination.

**Independent Test**: A pre-registration artifact fixes the baseline and challenger definitions before results; identical OOS periods/costs produce standalone and combined attribution, and failed challengers leave the baseline unchanged.

### Tests for User Story 4

- [ ] T065 [P] [US4] Add failing completed-one-hour-bar, 6/24/72-hour ensemble, 48-hour time-stop, no-ML, next-event signal, and no-forced-daily-trade tests in `internal/strategy/trend_candidate_test.go`
- [ ] T066 [P] [US4] Add failing inverse-volatility, covariance, leverage, and concentration sizing tests in `internal/risk/portfolio_allocator_test.go`
- [ ] T067 [P] [US4] Add failing frozen-definition and incremental-attribution tests for RSI and Fibonacci challengers in `scripts/tests/test_signal_challengers.py`
- [ ] T068 [P] [US4] Add failing standalone-versus-combined equal-risk attribution tests in `scripts/tests/test_portfolio_comparison.py`

### Implementation for User Story 4

- [ ] T069 [US4] Create and hash the pre-registration for the 6/24/72-hour one-hour-bar ensemble, 48-hour time stop, sizing policy, RSI-v1 and Fibonacci-v1 rules exactly as frozen in `research.md`, label all previously inspected history exploratory, and reserve the post-registration forward holdout in `research/hypotheses/trend_carry_v1.yaml`
- [ ] T070 [US4] Implement the frozen 6/24/72-hour sign ensemble on completed one-hour bars with a 48-hour time stop, without ADX, HMM, sentiment, forced daily entries, or discretionary filters in `internal/strategy/trend_candidate.go`
- [ ] T071 [US4] Implement configurable volatility target, covariance-aware risk scaling, leverage cap, and asset concentration limits in `internal/risk/portfolio_allocator.go`
- [ ] T072 [P] [US4] Implement RSI-v1 on one-hour bars with Wilder RSI(14), 30/70 recross entries, RSI-50/2-ATR/10-hour exits, next-event fills, and no parameter search in `scripts/signal_challenger_rsi.py`
- [ ] T073 [P] [US4] Implement Fibonacci-v1 on one-hour bars with prior-20-completed-bar impulse anchors, 61.8% touch/recross entry, 78.6% invalidation, prior-extreme/10-hour exit, next-event fills, and no discretionary swing selection in `scripts/signal_challenger_fibonacci.py`
- [ ] T074 [US4] Implement baseline-versus-challenger incremental IC, net PnL, doubled-cost, DSR/PBO, and rejection reporting in `scripts/compare_signal_challengers.py`
- [ ] T075 [US4] Implement identical-window standalone trend, carry, and equal-risk combined portfolio comparison in `scripts/compare_portfolio_candidates.py`
- [ ] T076 [US4] Add paper-only one-hour trend-candidate configuration with frozen hourly defaults, 48-hour maximum, optional zero-trade days, and disabled legacy ML in `config.example.trend.yaml`
- [ ] T077 [US4] Run exploratory baseline, challenger, and combined evaluations without retuning; retain `research_only` until the reserved forward holdout is complete and record every trial and rejection in `specs/001-harden-trading-strategies/quickstart.md`

**Checkpoint**: Candidate evidence exists with honest rejection paths; no indicator is included merely because it is familiar.

---

## Phase 7: User Story 5 — Quarantine or Replace Unsupported Strategies (Priority: P5)

**Goal**: Ensure unsupported strategies cannot be mistaken for deployable systems and retire perpetual-premium basis as fixed-maturity cash-and-carry.

**Independent Test**: The strategy registry blocks unsupported launch paths; perpetual basis cannot report an annualized fixed-convergence yield; every performance claim is labeled and linked to empirical artifacts or identified as a target.

### Tests for User Story 5

- [ ] T078 [P] [US5] Add failing registry tests for basis, market making, liquidation, mean reversion, cross-exchange, sentiment, and ML regime quarantine in `internal/bot/strategy_registry_test.go`
- [ ] T079 [P] [US5] Add failing tests that reject fixed-maturity annualization for perpetual instruments and validate log-basis annualization from actual delivery-future time to expiry in `internal/strategy/basis_trade/strategy_test.go`
- [ ] T080 [P] [US5] Add failing accounting-only market-making round-trip tests proving no extra order is submitted in `internal/strategy/market_making/strategy_test.go`
- [ ] T081 [P] [US5] Add documentation validation that flags unlabeled targets, simulated metrics, and unlinked performance claims in `scripts/tests/test_strategy_docs.py`

### Implementation for User Story 5

- [ ] T082 [US5] Centralize strategy status, prerequisites, and startup eligibility in `internal/bot/strategy_registry.go`
- [ ] T083 [US5] Route all bot strategy selection through the eligibility registry in `cmd/bot/main.go`
- [ ] T084 [US5] Disable perpetual-premium entry, return an explicit unsupported-instrument result, and add a pure delivery-futures annualization function using actual time to expiry without enabling execution in `internal/strategy/basis_trade/strategy.go`
- [ ] T085 [US5] Remove misleading perpetual cash-and-carry formulas and mark dated-futures basis as a separate future feature in `config.example.basis.yaml`
- [ ] T086 [US5] Separate market-making accounting from execution so completed quote fills are recorded without another close order in `internal/strategy/market_making/strategy.go`
- [ ] T087 [P] [US5] Mark liquidation cascade as alert/research-only with no expected-APY claim in `internal/bot/liquidation.go`
- [ ] T088 [P] [US5] Remove HMM/regime selection from eligible strategy paths while preserving offline model artifacts in `internal/strategy/trend.go`
- [ ] T089 [US5] Replace the current status table with evidence-linked measured, target, simulated, and rejected states in `docs/STRATEGY_STATUS.md`
- [ ] T090 [US5] Add a follow-up specification boundary for delivery-futures basis requiring expiry metadata and financing/roll modeling in `docs/DATED_FUTURES_BASIS_RESEARCH.md`

**Checkpoint**: Unsupported strategies are unmistakably quarantined, and no perpetual premium is presented as locked convergence yield.

---

## Phase 8: Polish and Cross-Cutting Quality Gates

**Purpose**: Verify the desired user stories together without broadening strategy scope.

- [ ] T091 [P] Add structured logging and alert context for transaction, leg, reservation, settlement, dataset, hypothesis, run, and eligibility IDs in `internal/execution/multi_leg.go`
- [ ] T092 [P] Add operator runbook for reconciliation failures, compensation, suspension, and artifact recovery in `docs/TRADING_SAFETY_RUNBOOK.md`
- [ ] T093 Implement the versioned eligibility evaluator for paper gates, DSR/PBO gates, eight consecutive reconciled paper weeks, configuration drift, and explicit operator approval while retaining the unconditional feature-level live block in `internal/config/eligibility.go`
- [ ] T094 Add task-relevant coverage enforcement for `internal/execution`, `internal/backtest`, `internal/bot`, `internal/risk`, and carry paths in `scripts/agent_workflow.sh`
- [ ] T095 Run `go build ./...`, `go test -race ./...`, Python syntax checks, and Python statistical tests; record results in `specs/001-harden-trading-strategies/quickstart.md`
- [ ] T096 Verify every FR/SC maps to implemented tests or an explicit deferred status and record the traceability matrix in `specs/001-harden-trading-strategies/traceability.md`
- [ ] T097 Verify the repository remains paper-only, no API keys changed, no training data deleted, and zero strategies are promoted without evidence in `docs/STRATEGY_STATUS.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 — Setup**: Starts immediately.
- **Phase 2 — Foundation**: Depends on Phase 1 and blocks every user story.
- **US1 / Phase 3**: Depends on Phase 2; mandatory MVP and blocks empirical strategy work.
- **US2 / Phase 4**: Depends on US1 because replay reuses the corrected execution and accounting contracts.
- **US3 / Phase 5**: Depends on US1 and US2.
- **US4 / Phase 6**: Depends on US2; combined portfolio comparison also depends on US3 artifacts.
- **US5 / Phase 7**: Registry and documentation tasks can start after US1, but basis/MM code tasks should avoid overlapping file edits with active migrations.
- **Phase 8 — Polish**: Depends on every user story selected for the release.

### User Story Dependencies

- **US1**: Independent safe-runtime MVP after Foundation.
- **US2**: Requires US1 lifecycle semantics; independently valuable even if no strategy passes.
- **US3**: Requires US1 execution and US2 evidence production.
- **US4**: Requires US2; portfolio combination requires US3 results but the trend baseline and challengers can be evaluated independently.
- **US5**: Quarantine is independently testable; optional dated-futures work is explicitly not implemented here.

### Within Each User Story

1. Add the named regression/contract tests and verify the audited behavior fails.
2. Implement the smallest contract or state transition that makes the tests pass.
3. Run the story's independent checkpoint.
4. Stop if the checkpoint fails; do not compensate by tuning strategy parameters.
5. Record evidence and rejection reasons before moving to the next story.

## Parallel Opportunities

- Phase 1 tasks T002 and T003 can run in parallel.
- Foundation type definitions T006 and T007 can run in parallel after T005's naming conventions are agreed.
- US1 regression tests T013–T019 can be authored in parallel because they target separate packages/files.
- US2 Go replay tests T032–T035 and Python statistic tests T036–T038 can run in parallel.
- US2 DSR and PBO implementations T044–T045 can run in parallel.
- US3 calculation/schedule/strategy tests T051–T053 can run in parallel.
- US4 trend, allocator, challenger, and portfolio tests T065–T068 can run in parallel.
- US4 RSI and Fibonacci implementations T072–T073 can run in parallel only after T069 freezes both definitions.
- US5 registry, basis, MM, and documentation tests T078–T081 can run in parallel.

## Parallel Example: User Story 2

```text
Task: T032 — global chronology tests in internal/backtest/events_test.go
Task: T033 — next-event fill tests in internal/backtest/fill_model_test.go
Task: T036 — DSR tests in scripts/tests/test_deflated_sharpe.py
Task: T037 — PBO tests in scripts/tests/test_probability_backtest_overfit.py
```

## Parallel Example: User Story 4

```text
First complete T069 to freeze all hypotheses.
Then in parallel:
Task: T070 — trend baseline in internal/strategy/trend_candidate.go
Task: T071 — allocator in internal/risk/portfolio_allocator.go
Task: T072 — RSI challenger in scripts/signal_challenger_rsi.py
Task: T073 — Fibonacci challenger in scripts/signal_challenger_fibonacci.py
```

## Implementation Strategy

### MVP First — Safe Runtime Only

1. Complete Phase 1.
2. Complete Phase 2.
3. Complete US1.
4. Stop and validate recovery, settlement, shared exposure, and live blocking.
5. Do not begin strategy profitability work until the MVP passes.

### Incremental Delivery

1. **Safe runtime**: truthful paper fills and managed multi-leg failure.
2. **Honest evidence**: deterministic replay and selection-aware statistics.
3. **Funding hypothesis**: corrected neutral carry, accepted or rejected.
4. **Trend hypothesis**: frozen simple trend plus isolated RSI/Fibonacci challengers.
5. **Quarantine cleanup**: unsupported strategies and claims remain blocked.

Each stage is useful even if all later strategy hypotheses fail.

## Notes

- `[P]` means different files and no dependency on an adjacent incomplete task; it does not authorize conflicting edits.
- No task changes `mode` to `live` or grants live approval.
- No task deletes historical or training data.
- Tests precede behavior changes and reproduce the audited defect where possible.
- Familiar indicators are not bundled: RSI and Fibonacci each consume a separate recorded trial.
- Do not tune after viewing OOS results; create a new hypothesis ID and charge it to the trial count.
- A failed profitability gate is a completed research result, not a reason to modify the gate.
