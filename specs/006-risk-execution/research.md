# Research: Phase 5 — Risk and Execution

**Date**: 2026-11-10

No NEEDS CLARIFICATION items in the technical context. Research covers
design patterns for the risk/execution layer.

## Findings

### Durable-Before-Broker Pattern

- **Decision**: Persist order intent and acquire pair reservation in
  PostgreSQL before any broker contact. Record broker outcome and
  create position atomically afterward. This is the "write-ahead"
  pattern for cross-system safety.
- **Rationale**: §14.2 explicitly requires this sequence. PostgreSQL
  and MT5 cannot share an atomic transaction; the backend must own
  the durable record of intent so that any crash or disconnect leaves
  a recoverable state.
- **Alternatives considered**: Optimistic approach (submit first,
  persist after) was rejected — a crash between broker fill and
  database write would create an untracked position with no recovery
  path.

### Order State Machine

- **Decision**: Use a linear state machine with explicit transitions:
  DRAFT → PENDING_SUBMIT → SUBMITTING → SUBMITTED → FILLED / REJECTED
  / CANCELLED / UNKNOWN. UNKNOWN is the catch-all for ambiguous
  outcomes. Only FILLED creates a position. UNKNOWN, SUBMITTING, and
  PENDING_SUBMIT all block the pair.
- **Rationale**: §14.2 requires safe order-state transitions and
  specifies that PENDING_SUBMIT, SUBMITTED, and UNKNOWN block the
  pair. Never assume execution from submission alone (§8 step 15).
- **Alternatives considered**: A simpler two-state model (pending →
  done) was rejected — it cannot represent the critical UNKNOWN state
  that requires operator resolution.

### Daily Risk State Machine

- **Decision**: Five states: ACTIVE, PROFIT_LOCKED, LOSS_LOCKED,
  DRAINING, DISABLED. PROFIT_LOCKED and LOSS_LOCKED reset at
  Asia/Amman daily boundary. DRAINING and DISABLED survive rollover
  and require manual clearing/reactivation. State transitions are
  event-driven (P/L threshold, operator action, daily reset).
- **Rationale**: §11.3 specifies these exact states and their
  rollover behavior. §14.1 confirms DRAINING and DISABLED survival.
- **Alternatives considered**: None — the requirement is prescriptive.

### Pair Reservation Concurrency

- **Decision**: Use PostgreSQL row-level locking (SELECT FOR UPDATE)
  for pair reservations. The partial unique constraint ensures at most
  one unresolved entry or open position per pair at the database level.
  Application-level checks are a first filter; the database constraint
  is the authoritative guard.
- **Rationale**: §14.2 requires database-level duplicate prevention
  and row-level barrier/reservation serialization. In-memory-only
  locking is insufficient — it is lost on crash and cannot serialize
  across processes.
- **Alternatives considered**: Application-level mutex was rejected
  as insufficient for crash recovery and multi-process safety.

### Startup Reconciliation

- **Decision**: On startup, scan for in-flight orders (SUBMITTING,
  PENDING_SUBMIT), unresolved intents, and orphaned reservations.
  Hold the entry barrier (block all new entries account-wide) until
  reconciliation completes. An in-flight SUBMITTING request is never
  auto-cleared — it requires authoritative broker evidence or operator
  intervention.
- **Rationale**: §14.2 specifies this exact behavior. A process that
  died mid-submission cannot know whether the broker received and
  executed the order. Auto-clearing would risk losing track of a
  filled order.
- **Alternatives considered**: Timeout-based auto-clearing was
  rejected per §14.2: "An unresolved in-flight SUBMITTING request
  cannot be released based only on process death, timeout, or not
  found."

### Intended Loss Ceiling Semantics

- **Decision**: The $0.50 per-trade loss ceiling is a mandatory
  pre-trade risk TARGET, not a guarantee. The system rejects entries
  where estimated loss exceeds the ceiling. The system documents that
  gaps, slippage, rejected stops, and execution failures can cause
  larger realized losses. The stop is never widened to fit broker
  constraints.
- **Rationale**: §10.2 explicitly states this is "not a guarantee
  that realized loss cannot exceed $0.50" and prohibits stop widening.
- **Alternatives considered**: Treating it as a hard guarantee was
  rejected — it is physically impossible to guarantee maximum loss
  in a gapping market.
