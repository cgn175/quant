# Research Decisions: Harden Trading Strategies

## Decision 1: Profit Is a Hypothesis, Not a Deliverable

**Decision**: Treat zero eligible strategies as a valid successful outcome. Implementation quality and credible rejection are deliverables; profit is not guaranteed.

**Rationale**: The current repository has contradictory and non-reproducible performance claims. Market returns are non-stationary, and research evidence supports classes of strategies rather than this implementation or parameterization.

**Alternatives considered**:

- Optimize parameters until a profitable backtest appears — rejected as selection bias.
- Set return targets as implementation acceptance criteria — rejected because engineering cannot guarantee market returns.

## Decision 2: Funding Carry Is the First Economic Hypothesis

**Decision**: Research positive-funding long-spot/short-perpetual carry first, using expected net settlement income.

**Rationale**: Funding is an observable contractual transfer with a clear economic source. It is more directly measurable than directional prediction, but still carries execution, basis, margin, liquidity, and venue risks.

**Alternatives considered**:

- Directional high-funding short without spot — rejected because it is primarily a directional trade.
- Negative-funding long-perpetual/short-spot — deferred until borrow cost, availability, and recall risk are modeled.
- Cross-exchange carry — deferred until both venues support authenticated, tested execution and recovery.

## Decision 3: Simple Trend Is the Only Initial Directional Candidate

**Decision**: Evaluate a pre-registered 6/24/72-hour time-series momentum ensemble on completed one-hour bars, with volatility/covariance sizing and a 48-hour maximum planned hold; exclude ML regime selection and discretionary filters.

**Rationale**: Trend persistence has broader empirical support than the repository's RSI/HMM/filter combinations. Fewer degrees of freedom improve falsifiability and reduce backtest overfitting.

**Alternatives considered**:

- Repair HMM immediately — rejected because current inference is stateless and feature-incompatible, while regime labels add another selection layer.
- Cross-sectional momentum on four assets — rejected because four correlated survivors do not form a credible cross-section.
- Mean reversion — deferred because the current universe was selected using observed performance.

## Decision 4: Go Owns Canonical Runtime and Replay Semantics

**Decision**: Use Go for strategy decisions, event ordering, execution simulation, exposure, and ledgers. Use Python only for selection-aware statistical analysis of immutable artifacts.

**Rationale**: Maintaining separate Go live logic and Python backtest logic caused semantic drift. A single canonical lifecycle reduces parity failures while retaining Python's statistical ecosystem.

**Alternatives considered**:

- Python-only backtester with duplicated Go rules — rejected because parity would remain unprovable.
- Rewrite the runtime in Python — rejected as unnecessary scope expansion.

## Decision 5: Venue and Market Are Required Order Dimensions

**Decision**: Every order request explicitly identifies venue, market type, instrument, side, quantity, intent, and reduce-only behavior.

**Rationale**: A single untyped executor caused spot hedges to hit perpetual endpoints and perpetual shorts to hit spot endpoints.

**Alternatives considered**:

- Maintain separate constructors with the existing generic interface — rejected because callers can still pass the wrong executor.
- Infer market from strategy name or symbol — rejected as implicit and unsafe.

## Decision 6: Multi-Leg Trades Use a Durable State Machine

**Decision**: Persist every transition and compensating action for related legs under one transaction identifier.

**Rationale**: Network failures, partial fills, restarts, and out-of-order acknowledgments are normal. A series of independent calls cannot prove neutral exposure.

**Alternatives considered**:

- Best-effort immediate rollback without persistence — rejected because a crash can lose the recovery intent.
- Assume exchange-level atomicity — rejected because separate spot and perpetual markets do not offer atomic cross-market orders.

## Decision 7: Funding Comes From Authoritative Settlement Events

**Decision**: Reconcile uniquely identified income-history or account-ledger settlements; polling rates never creates revenue.

**Rationale**: Funding is paid only at venue-defined settlement times and intervals can change. Rate polling is a forecast/input, not a cash event.

**Alternatives considered**:

- Credit estimated funding each scan — rejected as materially false accounting.
- Infer settlement solely from wall-clock defaults — rejected because contract intervals and venue policies change.

## Decision 8: Shared Risk Uses an Atomic Local Ledger

**Decision**: For the current single-host scope, coordinate exposure through a shared SQLite ledger with atomic reservations, expiries, and reconciliation.

**Rationale**: Each bot currently has a private in-memory monitor. A local transactional ledger is the smallest change that coordinates multiple processes without adding a distributed service.

**Alternatives considered**:

- Keep per-process monitors — rejected because they cannot enforce portfolio limits.
- Add a network risk service now — deferred as unnecessary for the current scale; revisit before multi-host deployment.

## Decision 9: Replay Is Globally Chronological and Next-Event Executed

**Decision**: Merge all input events by timestamp, apply a stable event-priority rule, and execute close-derived signals no earlier than the next executable event.

**Rationale**: Same-close fills use information unavailable before the fill, while per-symbol index iteration distorts portfolio chronology.

**Alternatives considered**:

- Continue per-symbol loops — rejected for portfolio risk and concurrency analysis.
- Assume all fills at candle close — rejected as look-ahead/execution bias.

## Decision 10: Selection-Aware Evidence Gates

**Decision**: Track every hypothesis/parameter trial and report non-overlapping out-of-sample results, Deflated Sharpe Ratio, Probability of Backtest Overfitting, concentration, and stressed-cost results.

**Rationale**: Ordinary Sharpe and walk-forward averages do not account for multiple testing or overlapping observations.

**Alternatives considered**:

- One train/test split — insufficient after extensive historical experimentation.
- Win rate and profit factor alone — insufficient for path, concentration, and selection risk.

## Decision 11: Dated Futures Replace Perpetual-Premium Basis

**Decision**: Retire perpetual premium as a fixed-convergence basis strategy. If basis is revisited, use delivery futures with known expiry and annualize from remaining time.

**Rationale**: A perpetual has no maturity that locks convergence. Its premium and funding are parts of the same economic carry process.

**Alternatives considered**:

- Adjust the perpetual compounding formula — rejected because the convergence premise, not just the formula, is wrong.

## Decision 12: Unsupported Strategies Are Quarantined

**Decision**: Market making, liquidation cascade, mean reversion, sentiment alpha, HMM/regime ML, and cross-exchange execution remain research-only.

**Rationale**: Each lacks either correct execution, adequate data, credible validation, or all three. Market making additionally requires order-book replay, queue position, latency, and adverse-selection modeling outside this feature's scope.

**Alternatives considered**:

- Repair all strategies concurrently — rejected because it expands scope before the shared foundation is trustworthy.

## Decision 13: RSI and Fibonacci Are Challenger Signals Only

**Decision**: Pre-register at most one objective RSI rule and one algorithmically anchored Fibonacci rule, evaluate each independently against the frozen trend baseline, and include both in the total multiple-testing trial count.

The frozen challenger definitions are:

- **RSI-v1**: on one-hour bars, Wilder RSI(14); enter long at the next executable event after RSI crosses from at or below 30 to above 30, enter short after RSI crosses from at or above 70 to below 70, exit at RSI 50, a 2-ATR protective stop, or 10 completed one-hour bars, whichever occurs first.
- **Fibonacci-v1**: using only the previous 20 completed one-hour bars, identify the highest high and lowest low; their time order defines the impulse direction. After an upward impulse, enter long at the next executable event when price touches the 61.8% retracement and closes back above it; use the mirrored rule after a downward impulse. Exit at the prior impulse extreme, invalidation beyond the 78.6% retracement, or 10 completed one-hour bars. No discretionary anchors or alternative levels are allowed.

**Rationale**: RSI is a deterministic transformation of recent gains and losses that may capture conditional short-horizon reversal, but fixed thresholds and regimes create easy tuning degrees of freedom. Large crypto technical-rule studies find mixed asset-level out-of-sample persistence, including no Bitcoin predictability in one extensive study. Fibonacci levels introduce additional anchor and level choices; a peer-reviewed algorithmic study found price behavior at Fibonacci zones statistically indistinguishable from non-Fibonacci zones and no abnormal standalone profit. Familiarity is therefore insufficient for inclusion.

**Evidence**:

- [Hudson and Urquhart, *Technical trading and cryptocurrencies*](https://doi.org/10.1007/s10479-019-03357-1)
- [Tsinaslanidis, Guijarro and Voukelatos, *Automatic identification and evaluation of Fibonacci retracements*](https://www.sciencedirect.com/science/article/pii/S0957417421012495)
- [Brock, Lakonishok and LeBaron, *Simple Technical Trading Rules and the Stochastic Properties of Stock Returns*](https://doi.org/10.1111/j.1540-6261.1992.tb04681.x)

**Alternatives considered**:

- Combine RSI, Fibonacci, Bollinger Bands, and trend into one initial rule — rejected because attribution becomes impossible and the implicit trial count explodes.
- Tune RSI thresholds or Fibonacci anchors per asset — rejected as high-risk curve fitting.
- Exclude all technical challengers permanently — rejected because the new validation framework can test them cheaply and honestly after the baseline is frozen.

## Decision 14: Existing History Is Exploratory, Not Fresh OOS Evidence

**Decision**: Treat all periods already used or viewed during prior strategy development as exploratory. Pre-register candidates and reserve a later forward period that remains untouched until the rule and cost model are frozen. Historical replay may debug mechanics and estimate PBO/DSR, but it cannot by itself grant confirmatory eligibility.

**Rationale**: The repository has already tested many strategy families, filters, thresholds, and parameter combinations on the retained history. Calling another split of the same repeatedly inspected data “out of sample” does not erase researcher selection. A forward holdout is the cleanest remaining falsification opportunity.

**Alternatives considered**:

- Treat the latest historical segment as untouched — rejected because existing reports and model metadata already expose recent performance.
- Rely only on multiple-testing corrections — rejected because the exact number of informal and undocumented trials is uncertain.
- Wait indefinitely for new data before engineering — rejected; mechanics and exploratory replay can be built now, while eligibility remains research-only until forward evidence accumulates.

## Decision 15: Hourly Intraday Trading, Not HFT or Long-Horizon Trend

**Decision**: Evaluate after each completed one-hour bar, target ordinary holding periods of 6–24 hours, and enforce a 48-hour planned time stop. Funding carry may span one or two contract settlements but not become an open-ended weeks-long position. No strategy is required to trade every day.

**Rationale**: The requested operating horizon is hourly/daily. Academic evidence documents intraday Bitcoin predictability, but short-horizon gross effects are smaller and more sensitive to spread, fees, and timing. One-hour bars are compatible with the current architecture while avoiding false HFT claims. Skipping marginal signals is necessary because a daily trade quota converts costs into a certainty while edge remains uncertain.

**Evidence**:

- [Shen, Urquhart and Wang, *Bitcoin intraday time-series momentum*](https://doi.org/10.1111/fire.12290)
- [Hudson and Urquhart, *Technical trading and cryptocurrencies*](https://doi.org/10.1007/s10479-019-03357-1)

**Alternatives considered**:

- Sub-hour market making or latency arbitrage — rejected because the project lacks co-location, queue modeling, and tick-replay infrastructure.
- Four-hour to multi-week trend following — rejected because it does not match the requested turnover and holding horizon.
- Force at least one trade per day — rejected because signal absence is information and transaction costs are unavoidable.
