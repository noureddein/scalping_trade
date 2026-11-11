# Research: Phase 3 — Market Data and Spread

**Date**: 2026-11-10

No NEEDS CLARIFICATION items in the technical context. Research covers
design patterns for the tick processing and spread intelligence layers.

## Findings

### Tick Validation Strategy

- **Decision**: Validate each tick at the point of ingestion with a
  deterministic checklist: structural validity, finite/positive values,
  ask >= bid, correct pair, advancing broker timestamp, fresh receipt
  time. Invalid ticks are rejected with a structured reason enum, not
  silently dropped.
- **Rationale**: The strategy design document §2 step 1 specifies this
  exact validation sequence. Downstream consumers (spread engine,
  strategy) must never see an invalid tick.
- **Alternatives considered**: Deferred validation (validate at
  consumer) was rejected — it spreads responsibility and risks
  inconsistent rejection behavior.

### Batch and Deduplication Approach

- **Decision**: Track per-pair batch sequence numbers and EA run
  counters. Detect gaps (missing sequences), overwrites (ring-buffer
  wrap), and run boundaries (EA restart). Deduplicate by pair +
  broker timestamp. Mark gap intervals as degraded.
- **Rationale**: The EA batches ticks in a ring buffer. Sequence gaps
  and EA restarts invalidate rolling indicator history. The master plan
  Phase 3 status explicitly mentions batching/deduplication as
  implemented functionality to validate.
- **Alternatives considered**: Content-based dedup (hash of Bid/Ask/
  time) was considered but broker timestamp uniqueness per pair is
  sufficient and simpler.

### Spread Calculation Units

- **Decision**: Calculate spread as `(Ask - Bid) / point` where
  `point` comes from the broker's contract specification for that
  symbol. Express spread in broker-correct pips.
- **Rationale**: The master plan §12 requires spread "in pips using
  the broker's actual symbol specifications." The strategy design §3
  warns against hardcoded pip assumptions and requires units declared
  per feature.
- **Alternatives considered**: Raw price-difference spread was rejected
  — it is not comparable across pairs with different decimal places.

### Rolling Statistics Window

- **Decision**: Rolling statistics use an observation-indexed window
  (last N ticks) for the pilot. The strategy design §3.2 notes that
  tick-count windows do not represent fixed elapsed time; this is
  documented as a known limitation.
- **Rationale**: Simplest correct implementation for the pilot. A
  time-based window is a valid alternative to compare in Phase 7
  (backtesting). The choice affects indicator semantics but not spread
  safety gates.
- **Alternatives considered**: Fixed-time windows were considered but
  require handling empty intervals (no-tick periods), which is a
  separate design decision (strategy design §3.2 "empty-interval
  indicator semantics").

### Hybrid Spread Gate Design

- **Decision**: Two independent gates per pair — manual max and
  adaptive baseline. Both must pass. Missing either gate means
  fail-closed (no entry). The adaptive mechanism is implemented but
  its threshold values are deferred to owner approval (§19#2).
- **Rationale**: §12.2 requires both manual and adaptive protection
  with per-pair granularity. Constitution Principle II requires
  fail-closed on missing configuration.
- **Alternatives considered**: A single combined threshold was rejected
  — the master plan explicitly requires both gates.

### Stability Recovery Timer

- **Decision**: 60-second continuous stability after a spread
  abnormality before re-enabling entries. Reset on any new spike.
  Per-pair isolation. Configurable in Phase 6 dashboard.
- **Rationale**: §12.3 specifies 60 seconds, continuous verification,
  timer reset, and future configurability.
- **Alternatives considered**: None — the requirement is prescriptive.
