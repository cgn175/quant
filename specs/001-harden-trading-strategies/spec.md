# Feature Specification: Harden Trading Strategies

**Feature Branch**: `main`

**Created**: 2026-09-20

**Status**: Draft

**Input**: User description: "Create a plan using SpecKit skills to implement the strategy-audit recommendations."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Safe and Truthful Trading Runtime (Priority: P1)

As the trading-system operator, I need every multi-leg strategy to use the intended market and venue, preserve neutral exposure through failures and restarts, and report only realized fills and settlements so that paper results cannot disguise unsafe live behavior.

**Why this priority**: Execution and accounting defects can create unintended directional exposure or fictitious profit. Nothing else is useful until these paths are safe and observable.

**Independent Test**: Run deterministic paper scenarios covering full fills, partial fills, rejected second legs, cancellation, shutdown, and restart. Verify that every order reaches the intended market, exposure remains within tolerance or is compensated, and no income is credited without an exchange settlement.

**Acceptance Scenarios**:

1. **Given** a two-leg spot/perpetual entry, **When** both legs fill, **Then** each order is routed to its declared market and the resulting net delta remains within the configured tolerance.
2. **Given** a first leg fill and second leg rejection or timeout, **When** compensation runs, **Then** the filled exposure is hedged or closed and the strategy records a failed entry rather than an open neutral position.
3. **Given** an open position at a funding settlement, **When** an authoritative settlement record is received, **Then** the exact payment is recorded once; polling between settlements records no payment.
4. **Given** a process restart with persisted open positions, **When** state is restored, **Then** each position is restored by strategy, venue, and market without being claimed by another strategy.
5. **Given** any strategy that has not passed deployment eligibility, **When** live mode is requested, **Then** startup fails before any order can be placed.

---

### User Story 2 - Reproducible and Unbiased Strategy Validation (Priority: P2)

As a quantitative researcher, I need a portfolio-level validation workflow that uses only information available at decision time, models realistic costs and settlements, and records every tested hypothesis so that reported performance is reproducible and statistically defensible.

**Why this priority**: Existing results mix synthetic data, same-close execution, overlapping samples, and strategy implementations that differ from runtime behavior.

**Independent Test**: Re-run a frozen dataset and configuration twice and confirm identical orders, trades, daily equity, and validation metrics. Introduce known look-ahead, overlapping evaluation, and missing-cost fixtures and verify that validation rejects them.

**Acceptance Scenarios**:

1. **Given** a close-derived signal, **When** the backtest executes it, **Then** the earliest allowed fill occurs after the signal bar using the configured execution rule.
2. **Given** a multi-symbol dataset with missing timestamps, **When** it is replayed, **Then** all events are processed in global chronological order without index-based time distortion.
3. **Given** fees, spreads, slippage, funding, borrowing, and delisting events, **When** a run completes, **Then** each cost or event is reflected in both trade records and the daily equity curve.
4. **Given** repeated parameter or model trials, **When** results are reported, **Then** the trial count, out-of-sample segmentation, Deflated Sharpe Ratio, and Probability of Backtest Overfitting are included.
5. **Given** a synthetic or demonstration result, **When** it is exported, **Then** it is unmistakably labeled and cannot be consumed as empirical strategy evidence.

---

### User Story 3 - Correct Delta-Neutral Funding Carry (Priority: P3)

As the trading-system operator, I need a paper-tradable funding carry strategy whose entries are based on expected net settlement income and whose two legs are managed atomically so that performance represents realizable carry rather than directional risk or duplicated accounting.

**Why this priority**: Funding carry has the strongest economic basis among the current strategies, but depends on User Stories 1 and 2 for safe execution and credible evidence.

**Independent Test**: Replay historical funding settlements and executable spot/perpetual quotes through the paper runtime. Verify entry thresholds from net expected carry, exact settlement accounting, leg-level PnL, compensation behavior, and portfolio exposure limits.

**Acceptance Scenarios**:

1. **Given** positive funding, **When** expected income after all entry, holding, and exit costs clears the safety threshold, **Then** the strategy buys spot and shorts the matching perpetual in equal delta.
2. **Given** expected carry that does not clear all modeled costs and safety buffer, **When** the opportunity is evaluated, **Then** no entry is created.
3. **Given** a contract-specific settlement interval or interval change, **When** yield is estimated, **Then** the actual interval and next settlement are used rather than a fixed payments-per-day assumption.
4. **Given** negative funding, **When** spot borrowing and recall risk are unavailable or unmodeled, **Then** the strategy declines the trade.
5. **Given** multiple strategy processes, **When** aggregate or per-symbol limits would be exceeded, **Then** a shared portfolio authority blocks the new position.

---

### User Story 4 - Simple Trend and Carry Portfolio Candidate (Priority: P4)

As a quantitative researcher, I need a low-complexity, volatility-targeted hourly momentum candidate evaluated alone and alongside short-horizon funding carry so that the project can test an intraday-to-daily portfolio without relying on HFT infrastructure or multi-week holding periods.

**Why this priority**: Trend following has broad evidence but the current implementation and reports are contradictory. It should be treated as a new frozen hypothesis after the validation foundation is trustworthy.

**Independent Test**: Pre-register a small fixed set of trend horizons and risk rules, evaluate them on non-overlapping out-of-sample periods, and compare trend, carry, and equal-risk combined sleeves after stressed costs.

**Acceptance Scenarios**:

1. **Given** a pre-registered set of trend horizons, **When** signals are calculated, **Then** no unregistered filters, parameter searches, or ML regime gates affect the result.
2. **Given** varying asset volatility and correlation, **When** positions are sized, **Then** risk is scaled to the portfolio target while leverage and concentration limits remain satisfied.
3. **Given** base and stressed cost assumptions, **When** the candidate is evaluated, **Then** the report presents both standalone sleeves and their combined daily equity with attribution by asset and year.
4. **Given** a candidate that fails any eligibility gate, **When** paper deployment is requested, **Then** it remains research-only.
5. **Given** no qualifying hourly setup, **When** a decision cycle completes, **Then** the system stays flat rather than forcing a daily trade.

---

### User Story 5 - Quarantine or Replace Unsupported Strategies (Priority: P5)

As the system owner, I need unsupported strategies clearly quarantined and the basis strategy reframed around contracts with a known expiry so that documentation, configuration, and runtime behavior do not imply nonexistent profitability or convergence guarantees.

**Why this priority**: Market making, liquidation cascade, mean reversion, HMM regime filtering, and perpetual-premium basis currently lack credible validation or correct production behavior.

**Independent Test**: Enumerate all strategies and verify that only eligible paper strategies can start, every experimental strategy exposes its evidence status, and any basis-yield calculation uses a known maturity.

**Acceptance Scenarios**:

1. **Given** market making, liquidation cascade, mean reversion, or HMM regime filtering, **When** the standard bot launcher is used, **Then** the strategy is blocked unless its required data and validation gates are explicitly satisfied.
2. **Given** a perpetual contract without expiry, **When** a basis opportunity is evaluated, **Then** it is not presented as fixed-maturity cash-and-carry.
3. **Given** a delivery future with a known expiry, **When** basis is annualized, **Then** time to expiry and all holding costs are included.
4. **Given** a documentation performance claim, **When** its supporting empirical artifact is absent or synthetic, **Then** the claim is removed or labeled as a target rather than evidence.

### Edge Cases

- A market order is accepted but returns no final fill before timeout.
- Both legs partially fill in unequal quantities, or fills arrive out of order.
- The process crashes between leg fills or between settlement receipt and persistence.
- Exchange funding intervals, caps, or settlement timestamps change while a position is open.
- Venue mark prices diverge or one venue becomes unavailable during a cross-venue position.
- A symbol is delisted, halted, renamed, or lacks borrow availability.
- Stop and target are both touched within one historical bar and intrabar order is unknown.
- Multi-symbol data has gaps, duplicates, out-of-order events, or different listing histories.
- Portfolio limits are checked concurrently by multiple strategy processes.
- A backtest has too few independent observations or most profit comes from one asset, year, or trade.
- A model endpoint is unavailable, supplies an unexpected feature set, or receives insufficient state history.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST represent venue and market type explicitly for every order leg.
- **FR-002**: The system MUST route spot, perpetual, and delivery-futures orders through market-specific execution capabilities.
- **FR-003**: The system MUST manage multi-leg entries and exits as recoverable state machines with pending, partially filled, hedged, compensated, open, and closed states.
- **FR-004**: The system MUST prevent a position from being considered neutral until filled quantities satisfy the configured delta tolerance.
- **FR-005**: The system MUST make closes reduce-only where the venue supports it and MUST reject any close that could increase exposure.
- **FR-006**: The paper runtime MUST produce realistic, nonzero market-order fills or explicit failures and MUST model partial limit fills, queue/latency assumptions, and fees according to the selected simulation fidelity.
- **FR-007**: Funding income MUST be derived from authoritative settlement events and recorded idempotently.
- **FR-008**: Expected funding yield MUST use each contract's next settlement time, current settlement interval, caps, and all modeled costs.
- **FR-009**: The system MUST maintain shared portfolio exposure across strategy processes, venues, markets, and symbols.
- **FR-010**: Persisted positions MUST include strategy, venue, market, leg, external order identifiers, and lifecycle state.
- **FR-011**: Strategy startup MUST reconcile persisted state with venue state before accepting new entries.
- **FR-012**: Live mode MUST remain unavailable to every strategy until explicit strategy eligibility and operator approval are both present.
- **FR-013**: The validation workflow MUST replay all symbols in global chronological order.
- **FR-014**: Signals derived from a completed bar MUST not fill before a subsequent executable event.
- **FR-015**: The validation workflow MUST model entry and exit fees, bid/ask spread, slippage, funding, borrowing, liquidation, delisting, and failed/partial execution where applicable.
- **FR-016**: Ambiguous intrabar stop/target ordering MUST use a declared conservative rule or higher-resolution data.
- **FR-017**: Empirical runs MUST use immutable, identifiable input data and configuration and MUST be reproducible.
- **FR-018**: Synthetic or demonstration results MUST be stored separately and prominently labeled.
- **FR-019**: Every research report MUST include daily equity, drawdown, turnover, exposure, costs, trade count, asset/year attribution, and concentration diagnostics.
- **FR-020**: Every selected strategy MUST report non-overlapping out-of-sample results, trial count, Deflated Sharpe Ratio, and Probability of Backtest Overfitting.
- **FR-021**: Strategy eligibility MUST be determined by explicit, machine-checkable research and paper-trading gates.
- **FR-022**: The funding carry strategy MUST enter only when expected net carry exceeds all modeled costs plus a safety buffer.
- **FR-023**: Negative-funding spot/perpetual trades MUST be rejected unless borrow availability, borrow cost, and recall risk are modeled and available.
- **FR-024**: The initial trend candidate MUST use a small, pre-registered set of fixed horizons and volatility-based sizing without ML regime filters.
- **FR-025**: Portfolio research MUST compare trend, funding carry, and their equal-risk combination under identical cost and data assumptions.
- **FR-026**: Perpetual premium MUST NOT be reported as fixed-maturity cash-and-carry yield.
- **FR-027**: Delivery-futures basis MUST use time to expiry and include fees, financing, borrow, margin, and roll assumptions.
- **FR-028**: Market making, liquidation cascade, mean reversion, cross-exchange execution, and ML regime filters MUST remain experimental until their strategy-specific data and eligibility gates pass.
- **FR-029**: Documentation and configuration MUST distinguish measured results, simulated demonstrations, targets, and unsupported expectations.
- **FR-030**: Automated tests MUST cover execution routing, multi-leg compensation, settlement idempotency, restart recovery, shared limits, chronological replay, and strategy eligibility gates.
- **FR-031**: The research workflow MUST treat "no eligible strategy" as a valid outcome and MUST NOT present any backtest, paper result, or eligibility gate as a guarantee of future profit.
- **FR-032**: RSI and Fibonacci signals MUST be evaluated only as pre-registered challenger hypotheses against the frozen simple-trend baseline, with objective anchor/threshold definitions, identical out-of-sample periods and costs, and their trials included in multiple-testing diagnostics.
- **FR-033**: Data and periods already inspected during prior strategy development MUST be labeled exploratory and MUST NOT alone grant confirmatory eligibility; promotion evidence MUST include a post-registration forward holdout that was not used to define or revise the candidate.
- **FR-034**: Initial directional and carry candidates MUST evaluate on completed one-hour information, target holding periods measured in hours, and use a 48-hour maximum planned holding period; the system MUST NOT impose a minimum daily trade count.

### Key Entities

- **Venue Market**: A specific exchange and market type with contract metadata, fee schedule, trading rules, settlement cadence, and execution capability.
- **Order Leg**: One intended order within a strategy transaction, including venue, market, side, quantity, status, and external identifiers.
- **Multi-Leg Transaction**: The recoverable lifecycle joining related order legs and any compensating actions.
- **Position**: Strategy-owned exposure composed of one or more filled legs and reconciled against venue state.
- **Funding Settlement**: An authoritative, uniquely identified payment or charge for a position at a specified settlement time.
- **Portfolio Exposure**: Shared aggregate delta and notional exposure by strategy, symbol, venue, market, and correlation group.
- **Dataset Snapshot**: Immutable market inputs, metadata, universe membership, and quality diagnostics used by a research run.
- **Strategy Hypothesis**: A frozen rule set with declared parameters, economic rationale, and trial identity.
- **Validation Run**: A reproducible evaluation connecting a hypothesis, dataset, execution assumptions, trades, daily equity, and statistical diagnostics.
- **Strategy Eligibility**: The current research, paper, or live status and the evidence gates supporting that status.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In all deterministic two-leg test scenarios, completed neutral positions remain within 0.5% delta mismatch by notional; failed entries end with no unmanaged exposure.
- **SC-002**: Funding settlement reconciliation records exactly one payment per authoritative settlement identifier and zero payments from ordinary polling events.
- **SC-003**: One hundred percent of unapproved live-start attempts fail before submitting an order.
- **SC-004**: Restart tests recover every open leg and lifecycle state without duplicate positions, orphaned exposure, or cross-strategy ownership errors.
- **SC-005**: Repeating a validation run with the same dataset and configuration produces identical orders, trades, daily equity, and summary metrics.
- **SC-006**: Every empirical performance report identifies its dataset, configuration, cost assumptions, trial count, non-overlapping out-of-sample periods, and statistical-selection diagnostics.
- **SC-007**: A strategy is not paper-eligible unless out-of-sample profit factor is at least 1.15 after base costs, remains above 1.0 at twice the base cost assumption, and no single asset-year contributes more than 30% of total profit.
- **SC-008**: A strategy is not live-eligible unless its Deflated Sharpe probability is at least 95%, its Probability of Backtest Overfitting is at most 20%, and at least 8 consecutive weeks of paper observations reconcile with modeled fills, costs, and settlements.
- **SC-009**: All published strategy-status documentation contains zero unlabeled simulated performance figures and zero performance claims without a linked empirical artifact.
- **SC-010**: The trend, funding carry, and combined portfolio candidates are evaluated on the same input periods and cost assumptions with standalone and combined attribution available by asset and year.
- **SC-011**: If every candidate fails its evidence gates, the program completes successfully with zero deployment-eligible strategies and a recorded rejection rationale for each candidate.
- **SC-012**: RSI or Fibonacci is incorporated into a candidate only if it adds positive net out-of-sample value over the frozen baseline at base and doubled costs after accounting for the expanded trial count; otherwise it is recorded as rejected.
- **SC-013**: Every paper-eligibility decision identifies at least one untouched post-registration forward holdout, or remains `research_only` with an explicit insufficient-confirmatory-data reason.
- **SC-014**: In deterministic candidate tests, decisions occur only after completed one-hour inputs, ordinary planned exits occur within 48 hours, and zero-signal days generate zero forced entries.

## Assumptions

- The entire implementation and validation program remains paper-only until the live-eligibility gates and explicit operator approval are satisfied.
- Binance is the first venue for corrected single-exchange funding carry; cross-exchange execution remains experimental.
- Positive-funding long-spot/short-perpetual carry is the initial funding scope. Negative-funding trades are out of scope until borrowing is modeled.
- The target is hourly evaluation and intraday-to-two-day holding, not HFT and not multi-week trend following; a trade is optional on every cycle.
- Delivery-futures basis is optional after funding carry; perpetual-premium basis is retired as a standalone convergence strategy.
- Market making, liquidation cascade, mean reversion, sentiment alpha, and ML regime selection are not part of the MVP.
- Existing strategy and execution components will be reused only where their behavior satisfies the new contracts and tests.
- Historical market data must be restored or reacquired before empirical validation can be completed.
- Tests are required because the work changes execution, accounting, persistence, and research correctness.
- Profit is not assumed. The program may terminate after validation with no strategy promoted beyond research status.
