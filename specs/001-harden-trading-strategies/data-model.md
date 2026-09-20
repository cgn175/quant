# Data Model: Harden Trading Strategies

## 1. VenueMarket

Represents one tradeable market on one venue.

| Field | Constraint |
|---|---|
| `venue` | Required stable venue identifier |
| `market_type` | Required enum: `spot`, `perpetual`, `delivery_future` |
| `instrument` | Required venue-native instrument identifier |
| `base_asset` / `quote_asset` | Required normalized assets |
| `contract_multiplier` | Positive; defaults to 1 only when verified |
| `expiry_time` | Required for delivery futures; prohibited for spot/perpetual |
| `funding_interval` / `next_funding_time` | Required when a perpetual carry opportunity is evaluated |
| `price_tick` / `quantity_step` / `min_notional` | Positive venue constraints |
| `fee_schedule_version` | Required reference to the applied fee assumptions |

## 2. MultiLegTransaction

Groups related order legs and recovery actions.

| Field | Constraint |
|---|---|
| `transaction_id` | Globally unique and immutable |
| `strategy_id` | Required; ownership cannot change after creation |
| `purpose` | Enum: `entry`, `exit`, `rebalance`, `compensation` |
| `state` | Required lifecycle state |
| `target_delta` | Required target exposure after completion |
| `delta_tolerance_pct` | Positive and no greater than 0.5% for neutral carry |
| `created_at` / `updated_at` | Monotonic timestamps |
| `failure_reason` | Required for failed or compensated terminal states |
| `version` | Incremented on every transition for optimistic concurrency control |

### State transitions

```text
planned -> reserved -> submitting -> partially_filled -> hedged -> open
                                      |                  |
                                      v                  v
                                 compensating ------> compensated
                                      |
                                      v
                                    failed

open -> closing -> partially_closed -> closed
                     |
                     v
                compensating -> failed
```

Only `open`, `compensated`, `failed`, and `closed` are stable terminal/checkpoint states. A restart must resume every other state.

## 3. OrderLeg

One intended venue order belonging to a multi-leg transaction.

| Field | Constraint |
|---|---|
| `leg_id` | Globally unique and immutable |
| `transaction_id` | Required parent reference |
| `venue_market_id` | Required explicit market reference |
| `side` | Enum: `buy`, `sell` |
| `quantity` | Positive and aligned to quantity step |
| `order_type` | Enum: `market`, `limit` |
| `limit_price` | Required only for limit orders |
| `reduce_only` | Required boolean; closes must be true when supported |
| `status` | Enum: `planned`, `submitted`, `partial`, `filled`, `cancelled`, `rejected`, `unknown` |
| `external_order_id` | Unique per venue when assigned |
| `filled_quantity` | Between zero and requested quantity |
| `average_fill_price` | Positive when filled quantity is positive |
| `fee_amount` / `fee_asset` | Required for any nonzero fee |
| `submitted_at` / `last_update_at` | Required after submission |

## 4. Position

Strategy-owned exposure derived from filled legs, never from intended orders.

| Field | Constraint |
|---|---|
| `position_id` | Globally unique |
| `strategy_id` | Required owner |
| `symbol` | Required normalized symbol |
| `state` | Enum: `pending`, `open`, `closing`, `closed`, `orphaned` |
| `opened_at` / `closed_at` | Consistent with state |
| `net_delta` | Computed from reconciled filled legs |
| `gross_notional` | Nonnegative |
| `realized_pnl` | Derived from fills and settlements |
| `reconciliation_time` | Required before new entries after restart |

Relationship: a position has one or more `OrderLeg` records and zero or more `FundingSettlement` records.

## 5. FundingSettlement

Authoritative funding cash movement.

| Field | Constraint |
|---|---|
| `venue` / `instrument` | Required |
| `external_settlement_id` | Required idempotency key, unique with venue |
| `position_id` | Required reconciled position reference |
| `settlement_time` | Required venue settlement time |
| `rate` | Signed decimal rate |
| `notional` | Positive settlement notional |
| `amount` / `asset` | Signed realized cash movement and asset |
| `source` | Required authoritative account or income ledger source |
| `recorded_at` | Required ingestion time |

## 6. ExposureReservation

Process-shared pre-trade risk reservation.

| Field | Constraint |
|---|---|
| `reservation_id` | Unique |
| `transaction_id` | Unique active reservation per transaction |
| `strategy_id` / `symbol` | Required |
| `delta` / `gross_notional` | Proposed exposure |
| `correlation_group` | Required normalized group |
| `state` | Enum: `active`, `consumed`, `released`, `expired` |
| `expires_at` | Required for active reservations |
| `created_at` | Required |

Reservations are created atomically only if total, per-symbol, and correlation limits remain valid.

## 7. DatasetSnapshot

Immutable research input identity.

| Field | Constraint |
|---|---|
| `dataset_id` | Content-derived or globally unique immutable identifier |
| `created_at` | Required |
| `source_manifest` | Required list of files/tables and hashes |
| `symbols` / `time_range` | Required |
| `universe_method` | Required point-in-time selection description |
| `quality_report` | Required gaps, duplicates, outliers, and delistings summary |
| `synthetic` | Required boolean |

## 8. StrategyHypothesis

Frozen research definition.

| Field | Constraint |
|---|---|
| `hypothesis_id` | Unique and immutable |
| `strategy_type` | Required |
| `economic_rationale` | Required |
| `rule_version` | Required immutable version |
| `parameters` | Complete frozen parameter map |
| `registered_at` | Must precede evaluated out-of-sample period |
| `parent_hypothesis_id` | Required for every derived trial |

## 9. ValidationRun

Connects one hypothesis to one dataset and execution model.

| Field | Constraint |
|---|---|
| `run_id` | Unique |
| `hypothesis_id` / `dataset_id` | Required immutable references |
| `execution_assumptions` | Required fees, spreads, slippage, borrow, funding, and fill rules |
| `oos_windows` | Required non-overlapping evaluation intervals |
| `trial_count` | Positive and includes rejected trials |
| `artifact_hashes` | Required trade, ledger, exposure, and equity artifact hashes |
| `metrics` | Required return, risk, cost, concentration, DSR, and PBO outputs |
| `status` | Enum: `complete`, `invalid`, `rejected`, `passed` |
| `invalid_reason` | Required when invalid |

## 10. StrategyEligibility

Versioned promotion decision.

| Field | Constraint |
|---|---|
| `strategy_id` | Required |
| `status` | Enum: `research_only`, `paper_eligible`, `live_eligible`, `suspended` |
| `evidence_run_id` | Required for paper/live eligibility |
| `gate_policy_version` | Required |
| `gate_results` | Complete pass/fail results |
| `operator_approval` | Required and true only for live eligibility |
| `decided_at` | Required |
| `reason` | Required for rejection or suspension |

Eligibility never implies guaranteed future profit; it only records that a versioned evidence policy passed.
