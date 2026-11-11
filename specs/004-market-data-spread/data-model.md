# Data Model: Phase 3 — Market Data and Spread

**Date**: 2026-11-10

## Entities

### Tick

A single validated Bid/Ask observation.

| Field | Description | Constraints |
|-------|-------------|-------------|
| pair | Canonical symbol name | FK to CanonicalSymbol (Phase 2) |
| bid | Bid price | Positive, finite decimal |
| ask | Ask price | Positive, finite, >= bid |
| broker_timestamp | Broker-reported time | Advancing per pair; ISO 8601 |
| local_receipt_time | Monotonic local clock | Distinct from broker_timestamp |
| batch_sequence | Batch number from EA | Non-negative integer |
| run_counter | EA run identifier | Detects EA restarts |
| validation_status | Accepted or rejection reason | Enum: VALID, CROSSED, STALE, DUPLICATE, MALFORMED, REORDERED |

**Storage**: In-memory only. Not persisted to database.

### TickBatch

A group of ticks from one EA message.

| Field | Description | Constraints |
|-------|-------------|-------------|
| pair | Which pair this batch is for | FK to CanonicalSymbol |
| sequence_number | Batch sequence | Monotonically increasing per EA run |
| run_counter | EA run identifier | Matches ticks in batch |
| tick_count | Number of ticks in batch | Positive integer |
| has_gap | Whether a sequence gap was detected | Boolean |
| is_run_boundary | Whether this is a new EA run | Boolean |

### SpreadSnapshot

The current spread for a pair at a point in time.

| Field | Description | Constraints |
|-------|-------------|-------------|
| pair | Canonical symbol | FK to CanonicalSymbol |
| spread_pips | Spread in broker-correct pips | Non-negative decimal |
| bid | Bid used for calculation | From validated tick |
| ask | Ask used for calculation | From validated tick |
| timestamp | When calculated | From tick's broker_timestamp |

### SpreadStatistics

Rolling spread metrics for a pair (§12.1).

| Field | Description | Constraints |
|-------|-------------|-------------|
| pair | Canonical symbol | FK to CanonicalSymbol |
| current | Latest spread | Non-negative decimal (pips) |
| average | Rolling average spread | Non-negative decimal |
| median | Rolling median spread | Non-negative decimal |
| maximum | Rolling max spread | Non-negative decimal |
| minimum | Rolling min spread | Non-negative decimal |
| volatility | Spread standard deviation | Non-negative decimal |
| percentile | Current spread's percentile rank | 0–100 |
| trend | Spread direction indicator | Enum: WIDENING, NARROWING, STABLE |
| anomaly_flag | Whether current spread is anomalous | Boolean |
| window_size | Number of observations in window | Positive integer |

### SpreadGate

Per-pair spread protection configuration and state.

| Field | Description | Constraints |
|-------|-------------|-------------|
| pair | Canonical symbol | FK to CanonicalSymbol |
| manual_max_spread | Owner-set max spread (pips) | Positive decimal or NULL (unconfigured) |
| adaptive_threshold | Computed adaptive limit (pips) | Positive decimal or NULL (unconfigured) |
| manual_gate_passing | Is manual gate currently OK? | Boolean |
| adaptive_gate_passing | Is adaptive gate currently OK? | Boolean |
| entry_eligible | Both gates passing? | Boolean; false if either NULL |

### MarketHealthState

Per-pair market condition tracking.

| Field | Description | Constraints |
|-------|-------------|-------------|
| pair | Canonical symbol | FK to CanonicalSymbol |
| is_stale | No ticks within staleness threshold? | Boolean |
| last_tick_time | Time of most recent valid tick | Timestamp or NULL |
| staleness_threshold | Configurable per pair | Positive duration |
| tick_activity_level | Recent tick rate indicator | Enum: NORMAL, LOW, NONE |
| is_spread_abnormal | Spread gate currently failing? | Boolean |
| stability_timer_start | When stability recovery began | Timestamp or NULL |
| stability_duration | Required stable period | Default 60 seconds |
| is_recovering | In stability recovery period? | Boolean |
| is_entry_blocked | Any condition blocks entries? | Boolean |
| is_market_open | Latest EA market status, when supplied | Boolean or NULL |
| reopened_unstable | Ticks have resumed after observed NONE activity | Boolean |
| activity baseline | Observed tick rate over configured window | In-memory rolling observations |

**State transitions for spread recovery**:
- NORMAL → ABNORMAL: Spread gate violation detected
- ABNORMAL → RECOVERING: Spread returns within gate limits
- RECOVERING → NORMAL: 60s continuous stable spread elapsed
- RECOVERING → ABNORMAL: Spread spikes again (timer resets)

## Relationships

```
CanonicalSymbol (Phase 2) 1──1 SpreadStatistics
CanonicalSymbol 1──1 SpreadGate
CanonicalSymbol 1──1 MarketHealthState
CanonicalSymbol 1──* Tick (in-memory stream)
CanonicalSymbol 1──* SpreadSnapshot (rolling window)
```

## Notes

- All entities are in-memory for Phase 3. Aggregated SpreadSnapshots
  and SpreadStatistics may be persisted in later phases.
- Tick validation happens once at ingestion; downstream consumers
  (spread engine, strategies) receive only VALID ticks.
- Unapproved staleness, activity, rolling-window, trend, or anomaly
  settings remain unconfigured and block entry eligibility.
- Contract freshness is measured with the backend monotonic receive time;
  a missing freshness bound or timestamp makes spread calculation fail
  closed.
