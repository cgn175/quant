# Contract: Market-Specific and Multi-Leg Execution

## Order request

Every submission must provide:

- unique client intent and transaction identifiers;
- strategy owner;
- venue and explicit market type (`spot`, `perpetual`, or `delivery_future`);
- venue-native instrument plus normalized symbol;
- side, positive quantity, order type, optional limit price;
- entry, exit, rebalance, or compensation intent;
- reduce-only flag;
- strategy eligibility reference;
- active exposure-reservation reference.

The execution boundary rejects requests with a missing market, invalid quantity step, expired reservation, ineligible strategy, unsupported venue capability, or a close that could increase exposure.

## Order result

Submission returns a durable acknowledgement containing the internal leg ID, venue order ID when available, accepted quantity, current status, event time, and an explicit unknown-state marker when venue outcome cannot be determined. Unknown is never treated as rejected or filled until reconciled.

## Multi-leg invariants

1. A first leg cannot be submitted without an active shared-risk reservation.
2. Intended orders do not create positions; reconciled fills do.
3. A transaction cannot enter `open` unless net delta is within its declared tolerance.
4. Failure of a required leg starts persisted compensation before the reservation is released.
5. Compensation and close orders are reduce-only where supported.
6. A restart resumes nonterminal transactions before accepting new strategy entries.
7. A strategy cannot directly mutate transaction, fill, or position state.

## Paper execution fidelity

- Market fills use the next eligible bid/ask or configured depth-walk price, never a zero placeholder or the signal close.
- Limit fills state queue, latency, crossing, and partial-fill assumptions explicitly.
- Fees and slippage attach to fill events.
- Identical ordered market events and configuration produce identical fills.
- A low-fidelity fill model is allowed for unit tests but its artifacts are labeled synthetic and cannot grant strategy eligibility.

## Funding settlement ingestion

- Rate observations and estimated next payments are forecasts only.
- Realized funding requires an authoritative account/income event.
- `(venue, external_settlement_id)` is unique and idempotent.
- Settlement notional, rate, amount, asset, and time are retained.
- Reconciliation discrepancies suspend new entries for the affected position and strategy.
