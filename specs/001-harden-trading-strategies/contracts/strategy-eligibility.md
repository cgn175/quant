# Contract: Strategy Eligibility

## Statuses

- `research_only`: May be evaluated offline; may not submit paper or live orders through the standard launcher.
- `paper_eligible`: May submit paper orders under the evidence version that passed.
- `live_eligible`: Technically representable but remains blocked unless explicit operator approval is also recorded. This feature does not grant live approval.
- `suspended`: Previously eligible but blocked because evidence, reconciliation, configuration, or runtime health is invalid.

## Paper eligibility gates

All gates must pass for the exact strategy and rule version:

1. Empirical immutable dataset with valid quality report.
2. Non-overlapping out-of-sample evaluation.
3. Profit factor at least 1.15 after base costs.
4. Profit factor above 1.0 at twice base costs.
5. No single asset-year contributes more than 30% of total profit.
6. All required execution, settlement, recovery, and replay tests pass.
7. No unresolved reconciliation or data-integrity failure.

## Live eligibility gates

Live eligibility requires every paper gate plus:

1. Deflated Sharpe probability at least 95%.
2. Probability of Backtest Overfitting at most 20%.
3. At least eight consecutive weeks of reconciled paper observations.
4. Paper fills, fees, funding, and exposure reconcile with modeled assumptions within declared tolerances.
5. Explicit operator approval for the exact strategy, configuration, venue, and capital limit.

Live mode remains disabled for this feature even if the evidence fields are populated.

## Automatic suspension

A strategy is suspended on unknown or orphaned order state, settlement duplication/mismatch, unreconciled restart state, expired evidence, configuration drift, breached exposure limit, missing dataset/artifact, or changed rule version.

## No-profit guarantee

Eligibility records evidence-policy compliance. It is not a prediction or guarantee of future profitability. Zero paper-eligible strategies is a valid program result.
