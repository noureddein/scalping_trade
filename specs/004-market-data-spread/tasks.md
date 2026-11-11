# Tasks: Phase 3 — Market Data and Spread

**Input**: Design documents from `specs/004-market-data-spread/`

**Prerequisites**: plan.md, spec.md, data-model.md, contracts/tick-protocol.md, research.md, quickstart.md

**Note**: Phase 3 implements live tick ingestion, spread calculation, spread protection gates,
stability recovery, and market anomaly detection. All processing is in-memory. Extends Phase 2
TCP protocol with TICK_DATA and MARKET_STATUS messages.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US6)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: Tick and spread type definitions shared across all stories

- [ ] T001 Add tick and spread types to src/scalping_core/broker_types.py: Tick dataclass (pair: str, bid: Decimal positive/finite, ask: Decimal positive/finite/>=bid, broker_timestamp: datetime advancing, local_receipt_time: datetime monotonic, batch_sequence: int non-negative, run_counter: int, validation_status: enum VALID/CROSSED/STALE/DUPLICATE/MALFORMED/REORDERED), TickBatch dataclass (pair: str, sequence_number: int monotonically increasing per run, run_counter: int, tick_count: int positive, has_gap: bool, is_run_boundary: bool), SpreadSnapshot dataclass (pair: str, spread_pips: Decimal non-negative, bid: Decimal, ask: Decimal, timestamp: datetime), SpreadTrend enum (WIDENING/NARROWING/STABLE), TickActivityLevel enum (NORMAL/LOW/NONE)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: TICK_DATA message parsing in the TCP adapter — all tick stories depend on this

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T002 Extend src/scalping_core/tcp_broker_adapter.py to parse TICK_DATA messages per contracts/tick-protocol.md: extract pair (str, must map to canonical symbol via Phase 2), run_counter (int), batch_sequence (int), ticks array (each with bid: decimal positive/finite, ask: decimal positive/finite/>=bid, broker_timestamp: ISO 8601 advancing). Record local_receipt_time on the backend side. Reject entire message if JSON is malformed; reject individual ticks if fields are missing/invalid; pass valid ticks to market_data consumer
- [ ] T003 Extend src/scalping_core/tcp_broker_adapter.py to parse optional MARKET_STATUS messages: pair (str), is_market_open (bool), server_time (ISO 8601). Forward to market_data consumer. Ignore unknown message types for forward compatibility

**Checkpoint**: TCP adapter delivers parsed ticks and market status to the market data layer

---

## Phase 3: User Story 1 — Receive and Validate Live Ticks (Priority: P1) 🎯 MVP

**Goal**: Accept valid ticks, reject invalid ticks with structured reasons, track staleness

**Independent Test**: Send valid and invalid ticks → verify acceptance/rejection with correct reasons

- [ ] T004 [US1] Implement tick validation in src/scalping_core/market_data.py: for each tick check structural validity (all fields present), finite/positive bid and ask, ask >= bid (else CROSSED), correct pair mapping (known canonical symbol from Phase 2), advancing broker_timestamp per pair (else DUPLICATE/REORDERED), local_receipt_time freshness against configurable staleness threshold (else STALE). Set validation_status enum accordingly. Return only VALID ticks to downstream consumers
- [ ] T005 [US1] Implement staleness detection in src/scalping_core/market_data.py: track last_tick_time per pair, compare against configurable staleness_threshold (positive duration, per pair). When no tick arrives within threshold, mark pair as stale (is_stale = True) and block signal generation for that pair. Staleness threshold default requires owner approval — fail closed if not configured (FR-009, FR-006)
- [ ] T006 [US1] Write unit tests in tests/test_market_data.py: test tick validation for each rejection reason (CROSSED bid/ask, STALE timestamp, DUPLICATE broker_timestamp, MALFORMED missing fields, REORDERED earlier timestamp), test valid tick acceptance, test staleness detection (fresh → stale → fresh transitions), test that downstream receives only VALID ticks

**Checkpoint**: Tick validation works — valid ticks accepted, invalid ticks rejected with reasons

---

## Phase 4: User Story 2 — Handle Tick Batching and Deduplication (Priority: P1)

**Goal**: Process tick batches, deduplicate, detect gaps and EA run boundaries

**Independent Test**: Send batches with duplicates, gaps, new run counters → verify correct handling

- [ ] T007 [US2] Implement batch processing in src/scalping_core/market_data.py: accept TickBatch, process each tick individually through validation (T004), track batch_sequence per run_counter per pair. Detect sequence gaps (batch_sequence jumps) and set has_gap=True, log degraded interval. Detect EA run boundaries (new run_counter) and set is_run_boundary=True, reset sequence tracking, quarantine rolling indicators
- [ ] T008 [US2] Implement deduplication in src/scalping_core/market_data.py: within a batch, discard ticks whose broker_timestamp matches or precedes an already-accepted tick for the same pair. Track ring-buffer overwrites from EA (run_counter change with lower sequence). Log deduplication counts per batch
- [ ] T009 [US2] Write unit tests in tests/test_market_data.py: test batch with duplicates (same broker_timestamp), test sequence gap detection, test EA restart (new run_counter), test batch ordering, test degraded interval marking

**Checkpoint**: Batch processing handles duplicates, gaps, and EA restarts correctly

---

## Phase 5: User Story 3 — Calculate Live Spread Per Pair (Priority: P1)

**Goal**: Spread in broker-correct pips using contract spec; rolling 9-metric statistics

**Independent Test**: Feed known tick sequence → verify spread matches manual calculation using contract spec

- [ ] T010 [US3] Implement spread calculation in src/scalping_core/spread_engine.py: compute spread_pips = (ask - bid) / point using the pair's ContractSpecification.point from Phase 2 (no hardcoded pip assumptions per FR-003). Create SpreadSnapshot for each valid tick. Reject calculation if contract spec is unavailable or stale
- [ ] T011 [US3] Implement rolling spread statistics in src/scalping_core/spread_engine.py: maintain SpreadStatistics per pair with all 9 metrics from §12.1 — current (latest spread_pips: non-negative Decimal), average (rolling mean: non-negative Decimal), median (rolling median: non-negative Decimal), maximum (rolling max: non-negative Decimal), minimum (rolling min: non-negative Decimal), volatility (standard deviation: non-negative Decimal), percentile (current spread's rank 0–100), trend (WIDENING/NARROWING/STABLE based on recent direction), anomaly_flag (bool, set when spread exceeds statistical threshold). Track window_size (positive int). Update on each new valid tick
- [ ] T012 [US3] Write unit tests in tests/test_spread_engine.py: test spread calculation against known bid/ask with specific contract spec (digits=5, point=0.00001), test all 9 statistics update correctly on tick sequence, test stale contract spec rejection, test that spread uses broker point not hardcoded value

**Checkpoint**: Spread calculated correctly in broker pips with rolling statistics

---

## Phase 6: User Story 4 — Enforce Spread Protection Gates (Priority: P1)

**Goal**: Hybrid spread gate (manual max + adaptive baseline); fail-closed when unconfigured

**Independent Test**: Set manual threshold → feed ticks above/below → verify entry blocking

- [ ] T013 [US4] Implement SpreadGate in src/scalping_core/spread_engine.py: per-pair gate with manual_max_spread (positive Decimal or NULL if unconfigured) and adaptive_threshold (positive Decimal or NULL if unconfigured). On each spread update: manual_gate_passing = current spread <= manual_max_spread, adaptive_gate_passing = current spread <= adaptive_threshold. entry_eligible = both gates passing AND neither is NULL. If either is NULL → entry_eligible = False (fail-closed per FR-006)
- [ ] T014 [US4] Implement spread gate query interface in src/scalping_core/spread_engine.py: is_entry_eligible(pair) → bool that downstream consumers (strategy, execution) call before entry. Returns False if either gate is unconfigured, either gate is failing, or market health indicates stale/recovering state. Log gate state changes (pass→fail, fail→pass)
- [ ] T015 [US4] Write unit tests in tests/test_spread_engine.py: test entry blocked when spread > manual max, test entry blocked when spread > adaptive threshold, test fail-closed when manual NULL, test fail-closed when adaptive NULL, test entry permitted when both pass, test that spread gate does NOT affect existing positions (FR-008)

**Checkpoint**: Spread gates enforce entry blocking; fail-closed when unconfigured

---

## Phase 7: User Story 5 — Spread Stability Recovery (Priority: P2)

**Goal**: 60-second stable spread required before re-enabling entries after abnormality

**Independent Test**: Trigger spike → feed 60s stable → entries re-enabled; spike during recovery → timer resets

- [ ] T016 [US5] Implement stability recovery state machine in src/scalping_core/spread_engine.py: per-pair states NORMAL → ABNORMAL (spread gate violation) → RECOVERING (spread returns within limits, start 60s timer) → NORMAL (timer expires). RECOVERING → ABNORMAL if spread spikes again (timer resets to zero). Track stability_timer_start and stability_duration (default 60s). Entry blocked during ABNORMAL and RECOVERING states
- [ ] T017 [US5] Write unit tests in tests/test_spread_engine.py: test NORMAL→ABNORMAL transition on gate violation, test ABNORMAL→RECOVERING when spread normalizes, test RECOVERING→NORMAL after 60s stable, test RECOVERING→ABNORMAL on second spike (timer reset), test per-pair isolation (one pair abnormal doesn't affect others)

**Checkpoint**: Stability recovery prevents premature re-entry after spread spikes

---

## Phase 8: User Story 6 — Detect Market Anomalies and Stale Data (Priority: P2)

**Goal**: Detect low activity, stale data, abnormal volatility, unstable reopening from observed data

**Independent Test**: Simulate no-tick period → stale detected; ticks resume with wide spreads → unstable reopening flagged

- [ ] T018 [US6] Implement MarketHealthState in src/scalping_core/market_data.py: per-pair state tracking is_stale (bool), last_tick_time (timestamp or NULL), staleness_threshold (positive duration, per pair), tick_activity_level (NORMAL/LOW/NONE based on recent tick rate), is_spread_abnormal (from SpreadGate), is_recovering (from stability state machine), is_entry_blocked (True if any condition blocks). Detect reduced tick activity by comparing tick rate to a rolling baseline. Detect market closure as extended NONE activity. Detect unstable reopening as ticks resuming after NONE period — require stability confirmation before entries
- [ ] T019 [US6] Write unit tests in tests/test_market_data.py: test stale detection (no ticks beyond threshold), test tick activity level transitions (NORMAL→LOW→NONE), test unstable reopening detection (NONE→ticks arrive with wide spread), test that anomaly detection uses observed data not hardcoded schedules, test is_entry_blocked aggregation (any blocking condition → blocked)

**Checkpoint**: Market anomalies detected from observed data; entries blocked during anomalous conditions

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: EA tick delivery, integration, and end-to-end validation

- [ ] T020 [P] Extend mql5/ReadOnlyConnector.mq5 to send TICK_DATA messages: batch ticks per contracts/tick-protocol.md format (pair as broker symbol, run_counter incrementing on EA restart, batch_sequence monotonically increasing, ticks array with bid/ask/broker_timestamp). Optionally send MARKET_STATUS messages with is_market_open and server_time
- [ ] T021 Run quickstart.md validation scenarios end-to-end and record PASS/FAIL evidence for each scenario (owner performs live MT5 tick validation; automated tests use synthetic tick sequences)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — T001 can start immediately
- **Foundational (Phase 2)**: Depends on Setup — T002/T003 need tick types
- **User Stories (Phases 3–8)**: All depend on Foundational (TICK_DATA parsing)
  - US1 must complete before US2 (batch processing builds on tick validation)
  - US3 can start after US1 (needs validated ticks for spread calculation)
  - US4 depends on US3 (spread gates need spread calculations)
  - US5 depends on US4 (stability recovery needs spread gates)
  - US6 depends on US1 and US4 (health state combines staleness + spread gate)
- **Polish (Phase 9)**: T020 can start after Setup; T021 needs all stories

### User Story Dependencies

- **US1 (P1)**: No dependencies — tick validation is foundational
- **US2 (P1)**: Depends on US1 (batch processing uses tick validation)
- **US3 (P1)**: Depends on US1 (spread calc needs validated ticks)
- **US4 (P1)**: Depends on US3 (gates need spread values)
- **US5 (P2)**: Depends on US4 (stability needs gates)
- **US6 (P2)**: Depends on US1 + US4 (health combines staleness + spread)

### Parallel Opportunities

- US2 and US3 can run in parallel (both depend only on US1, touch different files: market_data.py vs spread_engine.py)
- T020 (EA extension) can start early alongside user stories
- Within US3, T010 and T011 are sequential (stats need spread calc)

---

## Parallel Example: US2 + US3 after US1

```bash
# After US1 completes, start both in parallel:
# US2: T007-T009 in market_data.py (batch/dedup)
# US3: T010-T012 in spread_engine.py (spread calculation)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete T001 (Setup: tick types)
2. Complete T002–T003 (Foundational: TICK_DATA parsing)
3. Complete T004–T006 (US1: tick validation)
4. **STOP and VALIDATE**: Valid ticks accepted, invalid rejected with reasons
5. Proceed to US2–US6

### Incremental Delivery

1. Setup + Foundational → tick types and parsing ready
2. US1 (T004–T006) → tick validation works
3. US2 + US3 (parallel: T007–T012) → batch handling + spread calculation
4. US4 (T013–T015) → spread gates enforce entry eligibility
5. US5 (T016–T017) → stability recovery prevents premature re-entry
6. US6 (T018–T019) → market anomaly detection
7. Polish (T020–T021) → EA tick delivery, end-to-end validation

---

## Notes

- All tick processing is in-memory — no tick-by-tick PostgreSQL storage (FR-011)
- Adaptive spread threshold values are deferred to §19#2 — implement the mechanism, not the values
- Staleness threshold default requires owner approval — fail closed if not configured
- Spread protection applies only to new entries, never force-closes existing positions (FR-008)
- Market anomaly detection uses observed data, not hardcoded session/holiday schedules
- broker_timestamp and local_receipt_time are kept strictly distinct (FR-012)
