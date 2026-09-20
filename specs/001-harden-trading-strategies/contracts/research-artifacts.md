# Contract: Reproducible Research Artifacts

Every empirical validation run emits one immutable manifest plus referenced artifacts.

## Manifest requirements

- run, hypothesis, rule-version, dataset, and gate-policy identifiers;
- creation time and source revision;
- full frozen parameter and execution-assumption maps;
- input file/table hashes and point-in-time universe method;
- non-overlapping train, validation, and test intervals;
- total number of hypotheses and parameter trials considered;
- synthetic-data flag;
- artifact names and hashes;
- completion or invalidation status with reason.

## Required artifacts

1. Ordered market-event ledger.
2. Order-intent and order-event ledger.
3. Fill and fee ledger.
4. Funding and borrow ledger.
5. Position and exposure timeline.
6. Daily marked and realized equity.
7. Closed-trade table.
8. Data-quality report.
9. Performance and selection-aware statistics.
10. Eligibility-gate report.

## Required metrics

- net and gross return, volatility, Sharpe, Sortino, maximum drawdown, Calmar;
- profit factor, expectancy, turnover, trade/settlement count, holding period;
- fees, spread, slippage, funding, borrow, and other cost attribution;
- exposure and leverage distribution;
- profit attribution by asset, year, and largest trades;
- base-cost and doubled-cost results;
- Deflated Sharpe Ratio probability and Probability of Backtest Overfitting;
- percentage of profitable independent test intervals.

## Integrity rules

- Repeating a run from its manifest must reproduce ordered trades and daily equity exactly.
- Synthetic artifacts must include `synthetic: true` and cannot satisfy empirical gates.
- Overlapping test intervals cannot be counted as independent observations.
- Missing inputs or hashes make the run invalid rather than partially valid.
- Reports must link to artifacts instead of copying unsupported headline claims.
