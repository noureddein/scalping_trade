# Feature Specification: Phase 3 — Market Data and Spread

**Feature Branch**: `004-market-data-spread`

**Created**: 2026-11-10

**Status**: Draft

**Input**: User description: "Create a specification for the Phase 3: Market data and spread"

**Master Plan Reference**: Phase 3 (line 1063), §12 Spread Intelligence Engine, §3 strategy design data conventions

## User Scenarios & Testing

### User Story 1 - Receive and Validate Live Ticks (Priority: P1)

The system receives live Bid/Ask ticks from the EA for each active
pair, validates them (structurally valid, finite, positive, ask >= bid,
correct pair, advancing broker timestamp, fresh local receipt), and
rejects invalid ticks without crashing or polluting downstream
consumers.

**Why this priority**: Every subsequent component — spread calculation,
strategy signals, execution decisions — depends on a validated tick
stream. Invalid ticks flowing downstream can trigger incorrect trades.

**Independent Test**: Send a stream of ticks (valid and invalid)
through the system. Verify valid ticks are accepted and invalid ticks
are rejected with structured reasons.

**Acceptance Scenarios**:

1. **Given** an active broker connection, **When** the EA sends a valid
   Bid/Ask tick, **Then** the system accepts it, records Bid, Ask,
   broker timestamp, and local receipt time.
2. **Given** a tick with ask < bid, **When** processed, **Then** the
   system rejects it with a "crossed spread" reason and does not
   forward it.
3. **Given** a tick with a broker timestamp that does not advance,
   **When** processed, **Then** the system rejects it as duplicate or
   reordered.
4. **Given** a tick arriving after a configurable staleness threshold,
   **When** processed, **Then** the system marks the data as stale and
   blocks new signal generation.

---

### User Story 2 - Handle Tick Batching and Deduplication (Priority: P1)

The system handles tick batches from the EA (which may contain
multiple ticks per message), detects and discards duplicates, tracks
batch sequence gaps and EA ring-buffer overwrites, and marks affected
intervals as degraded.

**Why this priority**: The EA batches ticks for efficiency. Without
proper batch handling and deduplication, the system may process the
same tick twice or miss gaps that invalidate indicator calculations.

**Independent Test**: Send batches with duplicates, gaps, and out-of-
order ticks. Verify deduplication, gap detection, and degraded-interval
marking.

**Acceptance Scenarios**:

1. **Given** a batch with duplicate ticks, **When** processed, **Then**
   duplicates are discarded and only unique ticks proceed.
2. **Given** a sequence gap between batches, **When** detected, **Then**
   the system marks the gap interval as degraded and logs the event.
3. **Given** an EA restart (new run counter), **When** detected,
   **Then** the system recognizes the run boundary, resets or
   quarantines rolling indicators as needed, and logs the transition.

---

### User Story 3 - Calculate Live Spread Per Pair (Priority: P1)

For each active pair, the system calculates the current spread from
live Bid/Ask prices using the broker's actual contract specifications
(not hardcoded pip assumptions). It also tracks rolling spread
statistics: average, median, max, min, volatility, percentile, trend,
and anomalies.

**Why this priority**: Spread is a primary trading gate — entries are
blocked when spread exceeds safe thresholds. Incorrect spread
calculation or stale statistics can either block valid opportunities
or allow dangerous entries.

**Independent Test**: Feed a known tick sequence for a pair. Verify
the calculated spread matches expected values using the broker's
contract spec. Verify rolling statistics update correctly.

**Acceptance Scenarios**:

1. **Given** a valid tick with Bid and Ask, **When** spread is
   calculated, **Then** the result is in broker-correct pips using the
   symbol's contract specification (digits, point).
2. **Given** a sequence of ticks, **When** rolling statistics are
   queried, **Then** all 9 metrics from §12.1 are available: current,
   average, median, max, min, volatility, percentile, trend, anomalies.
3. **Given** a pair with no recent ticks, **When** spread is queried,
   **Then** the system reports the data as stale rather than returning
   a cached value as if it were fresh.

---

### User Story 4 - Enforce Spread Protection Gates (Priority: P1)

The system blocks new trade entries when the spread exceeds safe
conditions, using a hybrid approach: a manual maximum spread threshold
per pair AND an adaptive threshold per pair (owner-configured; the
algorithm for deriving recommended values is deferred to §19#2). Both
gates must pass for an entry to proceed.

**Why this priority**: Spread protection is a critical safety gate.
Trading during wide spreads directly impacts profitability and risk.
Constitution Principle II requires fail-closed when configuration is
missing.

**Independent Test**: Set a manual threshold and feed ticks with
spreads above and below it. Verify entries are blocked when either
the manual or adaptive gate fails.

**Acceptance Scenarios**:

1. **Given** a pair with a manual max spread of 2.0 pips, **When** the
   current spread is 2.5 pips, **Then** the system blocks new entries
   for that pair.
2. **Given** a pair with an adaptive baseline, **When** the spread
   exceeds the adaptive threshold, **Then** the system blocks new
   entries even if the manual threshold is not exceeded.
3. **Given** no manual threshold or no adaptive baseline configured for
   a pair, **When** an entry is attempted, **Then** the system fails
   closed — no entry without both gates configured.

---

### User Story 5 - Spread Stability Recovery (Priority: P2)

After a spread abnormality is detected, the system requires 60
seconds of stable spread conditions before re-enabling entries. If
the spread becomes abnormal again during recovery, the stability
timer resets.

**Why this priority**: Prevents premature re-entry after a spread
spike, which often occurs in rapid succession during volatile periods.

**Independent Test**: Trigger a spread spike, then feed 60 seconds of
stable ticks. Verify entries are re-enabled. Feed a second spike during
recovery and verify the timer resets.

**Acceptance Scenarios**:

1. **Given** a spread abnormality, **When** 60 seconds of stable
   spread pass, **Then** entries are re-enabled for that pair.
2. **Given** a recovery period in progress, **When** the spread spikes
   again, **Then** the stability timer resets to zero.
3. **Given** multiple pairs, **When** one pair has an abnormal spread,
   **Then** only that pair's entries are blocked; other pairs are
   unaffected.

---

### User Story 6 - Detect Market Anomalies and Stale Data (Priority: P2)

The system detects reduced tick activity, unusually wide spreads,
stale market data, abnormal volatility, market closure, and unstable
reopening conditions. It does not assume every holiday has identical
effects — it uses actual observed data.

**Why this priority**: Trading during low-liquidity or anomalous
conditions carries elevated risk. The system must detect these
conditions and block entries, not silently proceed.

**Independent Test**: Simulate a period with no ticks, then sudden
ticks with wide spreads. Verify the system flags both the stale period
and the unstable reopening.

**Acceptance Scenarios**:

1. **Given** no new ticks for a pair beyond the staleness threshold,
   **When** staleness is checked, **Then** the pair is marked stale
   per US1 staleness detection and entries are blocked (cross-ref
   US1-AS4).
2. **Given** a sudden return of ticks after a quiet period, **When**
   the first ticks arrive, **Then** the system treats the reopening
   as potentially unstable and requires stability confirmation before
   entries.
3. **Given** unusually wide spreads combined with low tick activity,
   **When** both are detected, **Then** the system identifies a
   potential low-liquidity condition.

---

### Edge Cases

- What happens if a spread spike occurs while an existing position is
  open? The spread spike does NOT force-close the position. Spread
  protection applies only to new entries (§12.4).
- What happens if the contract specification changes mid-session
  (e.g., digits change)? Spread calculations must use the latest
  contract spec; stale specs invalidate spread results.
- What happens if tick-by-tick storage is requested? Not approved
  without a measured need per §14.2. In-memory processing with
  aggregated storage is the default.
- What happens if adaptive thresholds have not been calibrated? The
  system fails closed — no entry until both manual and adaptive gates
  are configured. Adaptive threshold values are deferred to owner
  approval (§19 decision #2).

## Requirements

### Functional Requirements

- **FR-001**: The system MUST receive, validate, and reject or accept
  each tick based on: structural validity, finite/positive values,
  ask >= bid, correct pair mapping, advancing broker timestamp, and
  fresh local receipt time.
- **FR-002**: The system MUST handle tick batches, detect and discard
  duplicates, track batch sequence gaps, detect EA run boundaries, and
  mark degraded intervals.
- **FR-003**: The system MUST calculate spread from live Bid/Ask using
  the broker's contract specification (digits, point). No hardcoded
  pip assumptions.
- **FR-004**: The system MUST track all 9 rolling spread metrics per
  pair: current, average, median, max, min, volatility, percentile,
  trend, anomalies (§12.1).
- **FR-005**: The system MUST enforce a hybrid spread gate per pair:
  manual max spread AND adaptive threshold. Both MUST pass for entry
  eligibility. The adaptive threshold is an owner-configured value
  per pair; the computation algorithm for deriving recommended values
  is deferred to §19 decision #2.
- **FR-006**: The system MUST fail closed when either spread gate is
  not configured for a pair — no entry without both gates.
- **FR-007**: After a spread abnormality, the system MUST require 60
  seconds of stable spread before re-enabling entries. A second spike
  resets the timer.
- **FR-008**: Spread protection MUST apply only to new entries. A
  spread spike MUST NOT force-close an existing position.
- **FR-009**: The system MUST detect stale market data (no ticks beyond
  a configurable staleness threshold) and block signal generation.
- **FR-010**: The system MUST detect reduced tick activity, market
  closure, unusually wide spreads, abnormal volatility, and unstable
  reopening conditions using observed data, not assumed schedules.
- **FR-011**: Tick processing MUST be in-memory. Tick-by-tick storage
  is not approved without measured need. Aggregated spread statistics
  may be stored.
- **FR-012**: Broker time and local monotonic receipt time MUST be kept
  distinct. The system MUST NOT interpolate missing ticks and treat
  them as observed data.

### Key Entities

- **Tick**: A single Bid/Ask observation with broker timestamp, local
  receipt time, pair identifier, and validation status.
- **Tick Batch**: A group of ticks received in one EA message, with
  sequence number and run counter for gap/boundary detection.
- **Spread Snapshot**: The current spread for a pair at a point in
  time, in broker-correct pips.
- **Spread Statistics**: Rolling metrics for a pair: average, median,
  max, min, volatility, percentile, trend, anomaly flags.
- **Spread Gate**: The combination of manual max threshold and
  adaptive baseline for a pair. Both must be configured and passing.
- **Market Health State**: Per-pair state capturing staleness, tick
  activity level, liquidity indicators, and stability recovery timer.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Every valid tick is processed and available to downstream
  consumers within 100 milliseconds of receipt.
- **SC-002**: Invalid ticks (crossed, stale, duplicate, malformed) are
  rejected 100% of the time with a structured reason.
- **SC-003**: Spread calculations match manual verification against the
  broker's contract specification for every tested symbol.
- **SC-004**: All 9 spread metrics are populated per pair after a
  minimum warm-up period and update on each new valid tick.
- **SC-005**: Entries are blocked within 1 tick of a spread gate
  violation and re-enabled only after 60 seconds of confirmed stable
  spread.
- **SC-006**: Stale data is detected within the configured staleness
  threshold and blocks all signal generation for the affected pair.
- **SC-007**: The system correctly distinguishes EA run boundaries,
  sequence gaps, and normal batch processing in test scenarios.

## Assumptions

- Tick processing is in-memory; no PostgreSQL storage for individual
  ticks in Phase 3. Aggregated spread snapshots/statistics may be
  persisted in later phases.
- Adaptive spread threshold values are not approved. Phase 3
  implements the adaptive gate mechanism; the actual threshold values
  require owner approval (§19 decision #2).
- The 60-second spread stability period is the initial value per §12.3.
  It will be configurable via the dashboard in Phase 6.
- Market session/holiday schedules are not hardcoded. The system
  detects anomalies from observed data (tick activity, spread width).
  Explicit session/news policies are deferred to §19 decisions #3/#4.
- The staleness threshold is a per-pair configurable value. Its initial
  default requires owner approval.
- Tick-density/activity measures represent quote updates, not
  centralized traded volume, per strategy design §3.2.
- Tick activity level thresholds (what tick rate constitutes NORMAL,
  LOW, or NONE) require owner approval. Fail closed (block entries)
  if not configured.
- The anomaly_flag statistical threshold (e.g., N standard deviations
  above rolling mean) requires owner approval (§19 decision). Fail
  closed if not configured.
- The SpreadStatistics rolling window_size requires owner approval.
  Fail closed if not configured.
