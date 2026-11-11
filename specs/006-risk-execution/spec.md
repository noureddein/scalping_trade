# Feature Specification: Phase 5 — Risk and Execution

**Feature Branch**: `006-risk-execution`

**Created**: 2026-11-10

**Status**: Draft

**Input**: User description: "Create a specification for the Phase 5: Risk and execution"

**Master Plan Reference**: Phase 5 (line 1090), §8 Trade Entry pipeline, §9 Position Management, §10 P/L Management, §11 Daily Risk Management, §14 Database Design, §14.1 Approved Decisions, §14.2 Schema Baseline

## User Scenarios & Testing

### User Story 1 - Validate Risk Before Entry (Priority: P1)

Before any trade entry, the system validates: fixed lot size against
broker constraints, estimated loss (including spread, commission,
slippage estimate) against the intended $0.50 per-trade loss ceiling,
stop-loss distance against broker minimum distance, margin
requirements, and maximum exposure limits. If any check fails, the
entry is rejected. If the required stop distance cannot satisfy both
the broker minimum and the $0.50 ceiling simultaneously, the entry is
rejected — the stop is never widened to fit.

**Why this priority**: Risk validation is the primary safety gate
before capital is committed. An incorrect or missing risk check can
result in losses exceeding the intended ceiling.

**Independent Test**: Submit entry requests with various lot sizes,
stop distances, and margin conditions. Verify correct acceptance and
rejection with structured reasons.

**Acceptance Scenarios**:

1. **Given** a valid signal with estimated loss under $0.50 and stop
   above broker minimum, **When** risk is validated, **Then** the
   entry is approved.
2. **Given** an estimated loss of $0.60, **When** risk is validated,
   **Then** the entry is rejected with "exceeds intended loss ceiling."
3. **Given** a stop distance below the broker minimum, **When** risk
   is validated, **Then** the entry is rejected with "below broker
   minimum stop distance."
4. **Given** a stop that meets broker minimum but exceeds the $0.50
   ceiling, **When** risk is validated, **Then** the entry is
   rejected — the stop is not widened.
5. **Given** insufficient margin, **When** risk is validated, **Then**
   the entry is rejected.

---

### User Story 2 - Enforce Daily Risk Limits (Priority: P1)

The system tracks daily net P/L (realized + floating + commissions +
swaps) and enforces configurable daily profit (+$15 default) and loss
(-$5 default) limits. When either limit is reached, new entries are
blocked, pending entry orders are cancelled, but open positions
continue to be managed. Daily reset occurs at the Asia/Amman timezone
boundary. PROFIT_LOCKED and LOSS_LOCKED persist until the next trading
day or authorized manual reset.

**Why this priority**: Daily risk limits prevent catastrophic drawdown
and lock in profits. Without them, a single bad session could deplete
the account.

**Independent Test**: Simulate a trading day with escalating P/L.
Verify limits trigger at correct thresholds and that the state machine
transitions correctly.

**Acceptance Scenarios**:

1. **Given** daily net P/L reaches +$15, **When** checked, **Then**
   state transitions to PROFIT_LOCKED and new entries are blocked.
2. **Given** daily net P/L reaches -$5, **When** checked, **Then**
   state transitions to LOSS_LOCKED and new entries are blocked.
3. **Given** PROFIT_LOCKED state, **When** a new trading day starts
   (Asia/Amman boundary), **Then** state resets to ACTIVE.
4. **Given** DRAINING state, **When** a new trading day starts,
   **Then** DRAINING persists — it survives rollover.
5. **Given** DISABLED state, **When** a new trading day starts,
   **Then** DISABLED persists — requires manual reactivation.
6. **Given** an open position exists when LOSS_LOCKED triggers,
   **When** managed, **Then** the position is NOT force-closed.

---

### User Story 3 - Manage Order Lifecycle Durably (Priority: P1)

Every order follows a durable state machine: intent is persisted
before submission, the pair is reserved (preventing duplicate entries),
broker outcome is recorded, and the position is created atomically.
Ambiguous outcomes (timeout, disconnect, unknown status) keep the pair
reserved and the reconciliation barrier held until authoritative
evidence or authorized operator intervention resolves them. The system
never automatically resubmits an ambiguous request.

**Why this priority**: Cross-system order safety between the backend
and MT5 is the highest-risk integration point. A lost or duplicated
order can result in unintended positions and financial loss.

**Independent Test**: Simulate order submission with various outcomes
(success, rejection, timeout, disconnect). Verify state machine
transitions, reservation behavior, and that ambiguous states are
never auto-resolved.

**Acceptance Scenarios**:

1. **Given** a validated entry, **When** order intent is created,
   **Then** it is persisted durably and the pair is reserved before
   any broker call.
2. **Given** a successful broker fill, **When** outcome is recorded,
   **Then** the position is created and the reservation is released
   atomically.
3. **Given** a broker rejection, **When** outcome is recorded, **Then**
   the reservation is released and no position is created.
4. **Given** a timeout or disconnect during submission, **When** the
   outcome is unknown, **Then** the pair reservation and barrier are
   held; the system does NOT resubmit.
5. **Given** an unresolved order, **When** the system restarts, **Then**
   the reservation and barrier remain held until operator resolution.

---

### User Story 4 - Enforce Pair Reservation and Duplicate Prevention (Priority: P1)

Maximum one active position per canonical pair. The system acquires a
durable pair reservation before entry submission and holds it through
the position lifecycle. A second entry attempt on a reserved pair is
rejected. The reservation is released only when the position is
closed and settled, or the order is definitively resolved (rejected,
cancelled, or operator-cleared).

**Why this priority**: Duplicate positions on the same pair violate
the trading model and compound risk exposure beyond intended limits.

**Independent Test**: Attempt concurrent entries on the same pair.
Verify only one succeeds and the second is rejected.

**Acceptance Scenarios**:

1. **Given** pair EURUSD has an active reservation, **When** a second
   entry is attempted, **Then** it is rejected with "pair reserved."
2. **Given** a position is closed, **When** settlement completes,
   **Then** the reservation is released and the pair is eligible.
3. **Given** an unresolved order, **When** a new entry is attempted,
   **Then** it is rejected — the reservation blocks until resolution.

---

### User Story 5 - Reconcile State on Startup (Priority: P1)

On startup, the system reconciles its durable state with broker
reality: checks for in-flight orders, unresolved intents, open
positions without matching records, and missing fill confirmations.
Entry admission is blocked (barrier held) until reconciliation
completes. An unresolved in-flight SUBMITTING request is NOT released
based on process death, timeout, or "not found" — it requires
authoritative broker evidence or operator intervention.

**Why this priority**: Without startup reconciliation, a crash or
restart could leave the system in an inconsistent state — phantom
reservations, orphaned orders, or untracked positions.

**Independent Test**: Simulate startup with various dirty states
(in-flight orders, orphaned reservations). Verify the barrier blocks
entries until reconciliation completes.

**Acceptance Scenarios**:

1. **Given** an in-flight SUBMITTING order at startup, **When**
   reconciliation runs, **Then** the barrier blocks all entries until
   the order is resolved.
2. **Given** a clean state at startup, **When** reconciliation
   completes, **Then** the barrier is released and entries are
   permitted.
3. **Given** a confirmed fill that was not persisted before crash,
   **When** detected during reconciliation, **Then** entry admission
   is halted account-wide until operator intervention.

---

### User Story 6 - Persist Order and Risk State Durably (Priority: P1)

All order intents, broker outcomes, position records, daily risk
states, and risk events are persisted to a durable store. The schema
enforces: explicit foreign keys, NOT NULL and CHECK constraints,
unique constraints for account/pair identity, and partial uniqueness
preventing more than one unresolved entry or open position per pair.
Migrations are versioned and applied only to an isolated disposable
database until separately approved for production.

**Why this priority**: In-memory-only state is lost on crash. Durable
persistence is required for cross-system order safety, reconciliation,
and audit.

**Independent Test**: Create orders, positions, and risk events.
Verify persistence, constraint enforcement, and recovery after
simulated crash.

**Acceptance Scenarios**:

1. **Given** an order intent, **When** persisted, **Then** it survives
   a process restart and is visible to reconciliation.
2. **Given** an attempt to create a second unresolved entry for the
   same pair, **When** persisted, **Then** the database constraint
   rejects it.
3. **Given** a migration set (001–006), **When** applied to a fresh
   database, **Then** all tables, constraints, and indexes are
   created correctly.
4. **Given** an upgrade from migrations 001–005 to 006, **When**
   applied, **Then** the upgrade succeeds without data loss.

---

### User Story 7 - Calculate Position Risk and P/L (Priority: P1)

The system calculates estimated gross and net P/L before entry,
accounting for: pair pip value, contract specifications, spread,
commission, expected slippage, and account currency conversion. The
$0.50 intended loss ceiling is an estimate, not a guarantee — the
system documents that gaps, slippage, and execution failures may
cause realized loss to exceed it.

**Why this priority**: Incorrect P/L calculation leads to incorrect
risk decisions. The system must know whether a trade fits within
risk limits before submitting it.

**Independent Test**: Calculate P/L for trades with known parameters.
Verify calculations match manual verification.

**Acceptance Scenarios**:

1. **Given** a EURUSD BUY at 1.08557 with 0.01 lot, SL at 1.08507
   (5 pip stop), **When** risk is calculated, **Then** estimated
   loss matches the expected value using the pair's pip value.
2. **Given** a non-USD account currency, **When** P/L is calculated,
   **Then** the conversion uses the specified source (deferred to
   §19#14 for final source/freshness rules).
3. **Given** commission and swap estimates, **When** net P/L is
   calculated, **Then** costs are included without double-counting.

---

### Edge Cases

- What happens if the database is unavailable during an entry attempt?
  The entry is rejected — no entry without durable state (fail-closed
  per §14.2).
- What happens if the broker rejects the stop-loss order after the
  position is opened? The system must handle split execution; the
  risk implications are logged and the position is flagged for
  operator review.
- What happens if a fill confirmation is lost (process crash between
  broker fill and database persist)? Entry admission is halted
  account-wide until operator intervention (§14.2).
- What happens if two processes attempt to reserve the same pair
  concurrently? The database row-level lock ensures only one succeeds;
  the other receives a rejection.
- What happens if the operator manually resets a risk lock while a
  position is open? The reset is auditable and recorded. The open
  position continues to be managed.
- What happens during a prolonged MT5 disconnection? Recovery behavior
  is deferred (§19#11). Existing positions continue management;
  new entries are blocked while disconnected.
- What happens with partial fills? Handling is deferred (§19#15).
  The current design assumes a single 0.01-lot fill.

## Requirements

### Functional Requirements

- **FR-001**: The system MUST validate fixed lot (0.01) against broker
  volume constraints before every entry.
- **FR-002**: The system MUST calculate estimated loss including
  spread, commission, slippage estimate, and account currency
  conversion, and reject entries exceeding the $0.50 intended loss
  ceiling.
- **FR-003**: The system MUST validate stop-loss distance against the
  broker's minimum distance. If the stop cannot satisfy both broker
  minimum and $0.50 ceiling, the entry MUST be rejected.
- **FR-004**: The system MUST NOT widen a stop-loss to satisfy broker
  constraints.
- **FR-005**: The system MUST track daily net P/L (realized + floating
  + commissions + swaps) and enforce daily profit (+$15) and loss
  (-$5) limits.
- **FR-006**: The daily risk state machine MUST support states: ACTIVE,
  PROFIT_LOCKED, LOSS_LOCKED, DRAINING, DISABLED. DRAINING and
  DISABLED survive daily rollover.
- **FR-007**: Daily reset MUST use the Asia/Amman timezone boundary
  with explicit timezone-aware logic.
- **FR-008**: When daily limits trigger, new entries MUST be blocked
  and pending entry orders cancelled. Open positions MUST NOT be
  force-closed.
- **FR-009**: The system MUST persist order intent and acquire a
  durable pair reservation before any broker submission.
- **FR-010**: Maximum one active position per canonical pair. A second
  entry on a reserved pair MUST be rejected.
- **FR-011**: Ambiguous broker outcomes (timeout, disconnect, unknown)
  MUST keep the pair reservation and reconciliation barrier held. The
  system MUST NOT automatically resubmit.
- **FR-012**: On startup, the system MUST reconcile durable state with
  broker state. Entry admission MUST be blocked until reconciliation
  completes.
- **FR-013**: An in-flight SUBMITTING request MUST NOT be released
  based on process death, timeout, or "not found." It requires
  authoritative broker evidence or operator intervention.
- **FR-014**: A confirmed fill that fails to persist MUST halt
  account-wide entry admission.
- **FR-015**: All order intents, outcomes, positions, daily risk
  states, and risk events MUST be durably persisted with explicit
  constraints (FK, NOT NULL, CHECK, unique, partial unique).
- **FR-016**: Database migrations MUST be versioned. Migrations MUST
  only be applied to isolated disposable databases until separately
  approved.
- **FR-017**: The order state machine MUST use safe transitions. The
  system MUST NOT assume an order was executed merely because it was
  submitted.
- **FR-018**: Operator resolution of unresolved orders MUST be
  auditable with structured records.
- **FR-019**: The system MUST calculate expected gross and net P/L
  before entry using pair pip value, contract specs, spread,
  commission, slippage, and currency conversion.
- **FR-020**: The system MUST NOT force-close positions due to spread
  spikes, daily limit triggers, or risk locks. Close-management
  permissions are deferred (§19#12).
- **FR-021**: Concurrent access to pair reservations, risk state, and
  order state MUST be serialized to prevent race conditions.

### Key Entities

- **Order Intent**: A durable record of the intent to submit an order,
  created before broker contact, with state machine tracking.
- **Pair Reservation**: A per-pair lock preventing duplicate entries,
  held from intent creation through position settlement.
- **Position**: A record of an open or closed position with entry
  price, stop, target, fill details, and P/L.
- **Daily Risk State**: Per-day state machine (ACTIVE through DISABLED)
  with P/L tracking, timezone-aware boundaries.
- **Risk Event**: An auditable record of risk-related decisions
  (limit triggers, locks, resets, operator interventions).
- **Reconciliation Barrier**: An account-wide gate that blocks entry
  admission during startup reconciliation or after critical failures.

## Success Criteria

### Measurable Outcomes

- **SC-001**: No entry is submitted without a prior durable order
  intent and pair reservation in 100% of test scenarios.
- **SC-002**: Entries are rejected when estimated loss exceeds $0.50
  in 100% of test scenarios.
- **SC-003**: Daily limits trigger correctly at the configured
  thresholds and block new entries within the same evaluation cycle.
- **SC-004**: The daily reset occurs exactly at the Asia/Amman
  timezone boundary in all test scenarios.
- **SC-005**: Ambiguous broker outcomes never result in automatic
  resubmission in any test scenario.
- **SC-006**: Pair reservations prevent duplicate entries in concurrent
  test scenarios with zero false admissions.
- **SC-007**: Startup reconciliation correctly identifies and blocks
  on all dirty-state scenarios (in-flight orders, orphaned
  reservations, missing fills).
- **SC-008**: All order state transitions follow the defined state
  machine with no invalid transitions in any test scenario.
- **SC-009**: Database constraints reject invalid data (duplicate
  unresolved entries, missing foreign keys, null required fields)
  in 100% of test scenarios.

## Assumptions

- The current MQL5 EA is read-only. Order submission protocol and
  handler do not exist yet. Phase 5 implements the backend order
  lifecycle as a design contract; actual broker execution requires a
  separately approved EA order handler.
- Fixed lot is 0.01 for the pilot. Variable lot sizing is not in
  scope.
- The $0.50 per-trade loss ceiling and $15/$5 daily limits are initial
  values per the master plan. They are configurable via the dashboard
  in Phase 6.
- Currency conversion source, freshness limits, and fallback behavior
  are deferred (§19#14). Phase 5 implements the conversion interface;
  actual source requires owner approval.
- Partial-fill handling is deferred (§19#15). Phase 5 assumes a single
  0.01-lot fill per order.
- Close-management permissions during DRAINING, risk locks, and
  backend outage are deferred (§19#12). Phase 5 does not implement
  close permissions.
- Exact broker-authoritative order correlation after timeout/restart
  is deferred (§19#13). Phase 5 implements the correlation mechanism;
  exact correlation rules require owner approval.
- Exit rules (SL/TP placement, trailing, early exit, adaptive TP) are
  deferred (§19#1, #6, #7). Phase 5 validates stop/target against
  broker constraints but does not select exit parameters.
- PostgreSQL is the durable store. Migrations 001–006 exist but are
  unapplied; integration testing requires a disposable database.
