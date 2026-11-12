# Quickstart Validation Guide: Phase 8 — Demo Forward Test

**Date**: 2026-11-10

## Prerequisites

- Python 3.12 environment (WSL2)
- PostgreSQL instance (disposable test database)
- Phases 2–7 passing
- pytest installed
- Migration 009 (demo forward test tables) applied
- EA order handler compiled and loaded (requires owner approval)
- MT5 Demo account connected

**Critical**: The EA order handler must be separately approved by the
owner before implementation. Do not compile or load order-capable EA
code without recorded approval.

## Validation Scenarios

### 1. Demo Scope Gate (FR-001, FR-002, FR-004, SC-001)

**What to verify**: No orders without approval; scope enforcement.

| Scenario | Expected |
|----------|----------|
| No DemoScopeApproval exists | Order refused: "no Demo approval" |
| Approval exists but account mismatch | Order refused |
| Approval exists but wrong pair | Order refused |
| Approval exists but expired | Order refused |
| Approval exists, all checks pass | Order permitted |
| Live account (not Demo) | Order refused: "not a Demo account" |

**Command**: `pytest tests/test_demo_scope.py -v`

**Status**: ✅ PASS (6/6 tests verified 2026-11-12)

---

### 2. Order Lifecycle on Demo (FR-003, SC-003)

**What to verify**: Full Phase 5 pipeline works with real broker.

| Scenario | Expected |
|----------|----------|
| Valid signal → order → fill | Full lifecycle: intent → reservation → fill → position |
| Broker rejects order | Rejection recorded, reservation released |
| Timeout during submission | UNKNOWN protocol: reservation held |
| Duplicate entry attempt (same pair) | Rejected by pair reservation |

**Command**: Manual — owner submits test order on Demo and verifies
against MT5 terminal. `pytest tests/test_demo_scope.py -k "test_lifecycle" -v` for mock-broker unit tests.

**Automated checks**: ✅ PASS (4/4 tests verified 2026-11-12)
**Manual check**: ⏸️ PENDING — requires owner execution on real Demo terminal

---

### 3. Safety Mechanisms Under Real Conditions (FR-005–FR-008, SC-003–SC-005)

**What to verify**: Phase 5 safety works with real broker.

| Scenario | Expected |
|----------|----------|
| Process restart with open position | Reconciliation barrier activates |
| SL/TP on broker terminal | Match system's specified values |
| Daily P/L reaches loss limit | LOSS_LOCKED, entries blocked |
| Emergency stop from dashboard | DRAINING immediately |
| MT5 disconnect during order | UNKNOWN protocol followed |

**Command**: Manual — owner performs each scenario and records
evidence. Backend tests: `pytest tests/test_demo_scope.py -k "test_safety" -v`

**Automated checks**: ✅ PASS (5/5 tests verified 2026-11-12)
**Manual check**: ⏸️ PENDING — requires owner execution on real Demo terminal

---

### 4. Evidence Recording (FR-009, FR-010, SC-002)

**What to verify**: Every event recorded, no silent drops.

| Scenario | Expected |
|----------|----------|
| Signal generated | SIGNAL_GENERATED event recorded |
| Entry rejected (spread gate) | ENTRY_REJECTED with reason |
| Order filled | ORDER_FILLED + COST_RECORDED + LATENCY_RECORDED |
| Fill price differs from expected | FILL_DISCREPANCY recorded |
| DB error during recording | Recording failure logged, retried on recovery |

**Command**: `pytest tests/test_demo_evidence.py -v`

**Status**: ✅ PASS (7/7 tests verified 2026-11-12)

---

### 5. Duration Expiry (FR-013, SC-007)

**What to verify**: New entries blocked on expiry, positions managed.

| Scenario | Expected |
|----------|----------|
| Duration expires | Approval → EXPIRED, entries blocked within 1s |
| Open position at expiry | Position managed (SL/TP active), not closed |
| Owner revokes approval | Approval → REVOKED, entries blocked immediately |

**Command**: `pytest tests/test_demo_scope.py -k "test_expiry" -v`

**Status**: ✅ PASS (2/2 tests verified 2026-11-12)

---

### 6. Honest Reporting (FR-011, FR-012, SC-006)

**What to verify**: Reports include limitations and disclaimers.

| Scenario | Expected |
|----------|----------|
| 5-trade sample | "Insufficient sample size" warning |
| Profitable result | No "positive expectancy" claim |
| Any report | "Results do not authorize live trading" disclaimer |
| Cost breakdown | Spread, commission, swap, slippage itemized |

**Command**: `pytest tests/test_demo_report.py -v`

**Status**: ✅ PASS (5/5 tests verified 2026-11-12)

---

### 7. Discrepancy Detection (SC-004)

**What to verify**: Slippage and latency measured accurately.

| Scenario | Expected |
|----------|----------|
| Fill at expected price | 0 slippage recorded |
| Fill 0.5 pip worse | Discrepancy recorded with both prices |
| Submission-to-fill time | Latency in ms recorded |

**Command**: `pytest tests/test_demo_evidence.py -k "test_discrepancy" -v`

**Status**: ✅ PASS (7/7 tests verified 2026-11-12)

---

## Test Matrix

| Scenario | Unit (mocked) | Integration (DB) | Manual (Demo Broker) |
|----------|--------------|------------------|---------------------|
| Scope gate | Yes | Yes (approval table) | Owner verifies |
| Order lifecycle | Yes | Yes (persistence) | Owner on Demo |
| Safety mechanisms | Yes | Yes | Owner triggers each |
| Evidence recording | Yes | Yes (event tables) | Owner audits log |
| Duration expiry | Yes | Yes (state transition) | — |
| Honest reporting | Yes | Yes | Owner reviews report |
| Discrepancy detection | Yes | Yes | Owner compares terminal |

**Note**: Phase 8 is predominantly a manual verification phase. Unit
and integration tests validate the infrastructure, but the core value
is proving that safety mechanisms work with a real broker. The owner
must perform the manual scenarios and record evidence per Constitution
Principle VIII (honest test reporting).

---

## Safety Verification Test Plan (FR-005–FR-008, FR-014, FR-015)

Each scenario must be performed by the owner against the real MT5 Demo
terminal. Record evidence (screenshots, logs, event table queries) for
each. A pass requires the expected behavior; any deviation is a fail.

### Scenario 1: Startup Reconciliation After Process Kill (FR-005, SC-005)

- **Trigger**: Open a Demo position, then kill the Python backend process
- **Expected**:
  - On restart, reconciliation barrier activates
  - System detects the open position from broker state
  - New entries are blocked until reconciliation completes
  - Position remains tracked after reconciliation
- **Evidence**: ForwardTestEvent with reconciliation events, barrier status log

### Scenario 2: SL/TP Verification Against Broker Terminal (FR-006, SC-004)

- **Trigger**: Submit an order that fills, then check the broker terminal
- **Expected**:
  - SL value on MT5 terminal matches the system's specified stop_loss_price
  - TP value on MT5 terminal matches the system's specified take_profit_price (if set)
  - Values match in 100% of placed orders
- **Evidence**: Screenshot of MT5 terminal showing SL/TP alongside system log

### Scenario 3: Duplicate Protection via Pair Reservation (FR-007)

- **Trigger**: Generate two signals for the same pair while the first is in-flight
- **Expected**:
  - First signal proceeds to order submission
  - Second signal is rejected by pair reservation
  - ENTRY_REJECTED event recorded with reason "pair_reservation_unavailable"
- **Evidence**: ForwardTestEvent log showing both signals and the rejection

### Scenario 4: Daily Loss Limit Triggers LOSS_LOCKED (FR-008)

- **Trigger**: Trade until daily P/L reaches the configured loss limit
- **Expected**:
  - System transitions to LOSS_LOCKED state
  - All further entry attempts are blocked
  - LIMIT_TRIGGERED risk event recorded
- **Evidence**: DailyRiskState showing LOSS_LOCKED, ForwardTestEvent showing blocked entries

### Scenario 5: Emergency Stop from Dashboard (FR-014)

- **Trigger**: Activate emergency stop via the Phase 6 dashboard
- **Expected**:
  - System transitions to DRAINING immediately
  - New entries blocked
  - Open positions continue managed (SL/TP active, not force-closed)
- **Evidence**: Dashboard state change, ForwardTestEvent showing DRAINING transition

### Scenario 6: MT5 Disconnect/Reconnect Recovery (FR-015)

- **Trigger**: Disconnect the MT5 terminal (kill EA or network) during trading
- **Expected**:
  - System detects disconnect, follows Phase 2 reconnect protocol
  - In-flight orders follow UNKNOWN protocol (reservation held)
  - On reconnection, state is recovered correctly
  - No orders submitted during disconnection
- **Evidence**: Connection status logs, ForwardTestEvent showing disconnect/reconnect events
