# Quickstart Validation Guide: Phase 5 — Risk and Execution

**Date**: 2026-11-10

## Prerequisites

- Python 3.12 environment (WSL2)
- PostgreSQL instance (dedicated disposable database for testing)
- Phases 2–4 passing (broker connection, market data, strategy engine)
- pytest installed
- Migrations 001–006 available

## Validation Scenarios

### 1. Pre-Trade Risk Validation (FR-001–004, SC-002)

**What to verify**: Entries accepted when risk passes, rejected when
any check fails, stop never widened.

| Scenario | Expected |
|----------|----------|
| Estimated loss $0.40, stop above broker min | Entry approved |
| Estimated loss $0.60 | Rejected: exceeds loss ceiling |
| Stop below broker minimum distance | Rejected: below broker min |
| Stop meets broker min but exceeds $0.50 | Rejected: not widened |
| Insufficient margin | Rejected: margin |
| Lot size != 0.01 | Rejected: lot constraint |

**Command**: `pytest tests/test_risk_gate.py -v`

---

### 2. Daily Risk State Machine (FR-005–008, SC-003, SC-004)

**What to verify**: Limits trigger at thresholds, state transitions
correct, rollover behavior per state.

| Scenario | Expected |
|----------|----------|
| Net P/L reaches +$15 | PROFIT_LOCKED, entries blocked |
| Net P/L reaches -$5 | LOSS_LOCKED, entries blocked |
| PROFIT_LOCKED + daily rollover | Resets to ACTIVE |
| DRAINING + daily rollover | Stays DRAINING |
| DISABLED + daily rollover | Stays DISABLED |
| Open position when locked | NOT force-closed |
| Reset timezone | Asia/Amman boundary exactly |

**Command**: `pytest tests/test_daily_risk.py -v`

---

### 3. Order Lifecycle (FR-009, FR-017, SC-001, SC-008)

**What to verify**: Intent persisted before submission, state
transitions follow the machine, no invalid transitions.

| Scenario | Expected |
|----------|----------|
| Normal flow: intent → submit → fill | DRAFT→...→FILLED, position created |
| Broker rejection | REJECTED, reservation released |
| Timeout/disconnect | UNKNOWN, reservation HELD |
| Invalid transition (e.g., DRAFT→FILLED) | Rejected by state machine |

**Command**: `pytest tests/test_execution_engine.py -v`

---

### 4. Pair Reservation (FR-010, FR-021, SC-006)

**What to verify**: One entry per pair, concurrent attempts serialized,
reservation lifecycle correct.

| Scenario | Expected |
|----------|----------|
| First entry on EURUSD | Reservation acquired |
| Second entry on same pair | Rejected: pair reserved |
| Position closed + settled | Reservation released |
| Concurrent entry attempts | Only one succeeds |

**Command**: `pytest tests/test_admission_protocol.py -k "test_reservation" -v`

---

### 5. Ambiguous Outcome Handling (FR-011, FR-013, SC-005)

**What to verify**: Ambiguous outcomes keep reservation held, no
auto-resubmission, operator resolution auditable.

| Scenario | Expected |
|----------|----------|
| Timeout during submission | UNKNOWN; reservation HELD |
| Operator resolves as filled | Position created; reservation released |
| Operator resolves as not filled | Reservation released; no position |
| Attempt auto-clear on timeout | NOT permitted |

**Command**: `pytest tests/test_execution_engine.py -k "test_ambiguous" -v`

---

### 6. Startup Reconciliation (FR-012, FR-014, SC-007)

**What to verify**: Barrier blocks entries during reconciliation;
in-flight orders not auto-cleared; lost fills halt admission.

| Scenario | Expected |
|----------|----------|
| Clean startup | Barrier released, entries permitted |
| In-flight SUBMITTING at startup | Barrier held, entries blocked |
| Lost fill (crash between fill and persist) | Admission halted account-wide |
| All resolved | Barrier released |

**Command**: `pytest tests/test_admission_protocol.py -k "test_reconciliation" -v`

---

### 7. Durable Persistence (FR-015, FR-016, SC-009)

**What to verify**: Schema constraints enforced, migrations apply
correctly, data survives restart.

| Scenario | Expected |
|----------|----------|
| Fresh migration 001–006 | All tables, constraints, indexes created |
| Upgrade 001–005 → 006 | Upgrade succeeds, no data loss |
| Duplicate unresolved entry (same pair) | Database constraint rejects |
| Missing FK reference | Database rejects |
| Null required field | Database rejects |
| Data after simulated crash | Order intents and reservations survive |

**Command**: `pytest tests/test_durable_store.py -v`

---

### 8. P/L Calculation (FR-019, SC-002)

**What to verify**: Estimated P/L includes all cost components,
matches manual verification.

| Scenario | Expected |
|----------|----------|
| EURUSD BUY, 0.01 lot, 5-pip stop | Estimated loss matches pip-value calc |
| Include commission + slippage estimate | Net P/L reflects costs |
| Non-USD account (deferred source) | Conversion interface called |

**Command**: `pytest tests/test_risk_gate.py -k "test_pnl" -v`

---

## Test Matrix

| Scenario | Unit (mocked DB) | Integration (PostgreSQL) | Manual |
|----------|------------------|-------------------------|--------|
| Risk validation | Yes | — | — |
| Daily risk state | Yes | Yes (timezone) | — |
| Order lifecycle | Yes | Yes (persistence) | — |
| Pair reservation | Yes | Yes (concurrency) | — |
| Ambiguous outcomes | Yes | Yes (persistence) | — |
| Reconciliation | Yes | Yes (barrier + DB) | — |
| Durable persistence | — | Yes | — |
| P/L calculation | Yes | — | Owner verifies formulas |

**Note**: Integration tests require a dedicated disposable PostgreSQL
database. They MUST NOT run against any production or shared database.
The EA is read-only — no actual broker order submission is tested.
Broker execution is a design contract until an order handler is
separately approved (Constitution Principle III).

## Implementation Evidence (2026-11-11)

**PASS** — All quickstart validation scenarios verified:

- **Unit tests**: 532 passed (test_order_types, test_risk_gate, test_daily_risk,
  test_execution_engine, test_admission_protocol, test_position_manager,
  test_operator_resolution, test_stop_loss, test_startup_supervisor,
  test_postgres_store, test_durable_store)
- **PostgreSQL integration**: 41/41 passed (store CRUD, reservations, barrier,
  state guard, migrations 001–008, account enforcement, halt/recovery)
- **Migration runner**: disposable-target, ordering, upgrade-planning checks passed
- **No broker mutation attempted** (EA is read-only per Constitution Principle III)

Coverage by quickstart scenario:
1. Pre-trade risk: 111 risk_gate tests (volume, margin, exposure, stop distance, loss ceiling)
2. Daily risk state: 60 daily_risk tests (thresholds, rollover, floating P/L, transitions, cancel intents)
3. Order lifecycle: 22 execution_engine tests (full pipeline, state machine, intent persistence, regime recheck)
4. Pair reservation: 15 admission_protocol tests (acquire, gate, resolve, crash points)
5. Ambiguous outcomes: 18 operator_resolution tests (FILLED, REJECTED, OVERRIDE, audit)
6. Startup reconciliation: 15 startup_supervisor tests (barrier, dirty state, halt, recovery)
7. Durable persistence: 41 postgres_store + durable_store integration tests
8. P/L calculation: covered in risk_gate tests (cost components, conversion interface)

**Convergence (T027–T030)**: FR-008 cancel intents on limit trigger, regime recheck
in entry pipeline, ENTRY_REJECTED/BARRIER_HELD/BARRIER_RELEASED RiskEvent persistence,
migration 008 for full OrderState enum.
