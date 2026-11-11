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

---

### 5. Duration Expiry (FR-013, SC-007)

**What to verify**: New entries blocked on expiry, positions managed.

| Scenario | Expected |
|----------|----------|
| Duration expires | Approval → EXPIRED, entries blocked within 1s |
| Open position at expiry | Position managed (SL/TP active), not closed |
| Owner revokes approval | Approval → REVOKED, entries blocked immediately |

**Command**: `pytest tests/test_demo_scope.py -k "test_expiry" -v`

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

---

### 7. Discrepancy Detection (SC-004)

**What to verify**: Slippage and latency measured accurately.

| Scenario | Expected |
|----------|----------|
| Fill at expected price | 0 slippage recorded |
| Fill 0.5 pip worse | Discrepancy recorded with both prices |
| Submission-to-fill time | Latency in ms recorded |

**Command**: `pytest tests/test_demo_evidence.py -k "test_discrepancy" -v`

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
