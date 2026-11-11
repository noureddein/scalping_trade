# Quickstart Validation Guide: Phase 6 — Dashboard

**Date**: 2026-11-10

## Prerequisites

- Python 3.12 environment (WSL2)
- PostgreSQL instance (disposable test database)
- Phases 2–5 passing
- pytest installed
- Migration 007 (audit_log table) applied

## Validation Scenarios

### 1. Overview Panel (FR-001, SC-001, SC-002)

**What to verify**: All 11 overview fields display correctly and
update in near real-time.

| Scenario | Expected |
|----------|----------|
| Backend running, broker connected | All fields display current values |
| Trade completes | P/L, trade count, win/loss update within 1s |
| PROFIT_LOCKED state | Trading status shows lock prominently |
| Backend unreachable | "Disconnected" indicator, data marked stale |
| Panel load time | < 2 seconds |

**Command**: `pytest tests/test_dashboard_api.py -k "test_overview" -v`

---

### 2. Pair Management (FR-002, FR-012)

**What to verify**: Pairs display all 9 fields, CRUD operations work,
removal blocked when position exists.

| Scenario | Expected |
|----------|----------|
| View pairs list | All 9 §13.2 fields displayed |
| Add new pair | Pair appears, available for trading |
| Disable pair | Marked disabled, signals stop |
| Remove pair with no position | Removed successfully |
| Remove pair with active position | 409 Conflict, removal blocked |

**Command**: `pytest tests/test_dashboard_api.py -k "test_pairs" -v`

---

### 3. Live Spread Monitor (FR-003, SC-002)

**What to verify**: All 9 spread fields update with ticks, stability
timer displays correctly.

| Scenario | Expected |
|----------|----------|
| Active pair with ticks | All spread fields display and update |
| Spread spike | Permission blocked, stability timer appears |
| 60s stable after spike | Permission returns to allowed |
| SSE reconnection | Data resumes without duplication |

**Command**: `pytest tests/test_dashboard_live_feed.py -k "test_spread" -v`

---

### 4. Risk Controls (FR-004, FR-008, SC-003, SC-004)

**What to verify**: Parameters editable, validated, and audit-logged.

| Scenario | Expected |
|----------|----------|
| Change daily profit limit | Validated, applied, audit entry created |
| Invalid value (negative lot) | 400 error, clear message |
| Read-only field (lot_size) | 403 Forbidden |
| Audit log query | All changes recorded with old/new values |
| Config change response time | < 1 second |

**Command**: `pytest tests/test_dashboard_audit.py -v`

---

### 5. Positions Panel (FR-005, SC-002)

**What to verify**: Open positions display all 11 fields, floating
P/L updates live.

| Scenario | Expected |
|----------|----------|
| Open position exists | All 11 §13.5 fields displayed |
| Price changes | Floating P/L updates within 1s |
| No positions | Empty state (not error) |
| Position closes | Moves to history |

**Command**: `pytest tests/test_dashboard_api.py -k "test_positions" -v`

---

### 6. Emergency Stop (FR-007, SC-005)

**What to verify**: Transitions to DRAINING, blocks entries, requires
confirmation.

| Scenario | Expected |
|----------|----------|
| Emergency stop with confirm=true | DRAINING within 1s |
| Emergency stop without confirm | 400 Bad Request |
| Already DRAINING | 409 Conflict |
| New entry after stop | Blocked by risk state |

**Command**: `pytest tests/test_dashboard_emergency.py -v`

---

### 7. Disconnection/Reconnection (FR-009, FR-011, SC-006)

**What to verify**: Stale indicators appear, reconnection recovers
accurate state.

| Scenario | Expected |
|----------|----------|
| SSE connection drops | Stale indicator on all data |
| Controls during disconnect | Disabled |
| SSE reconnects | State recovers, no missed updates |
| Last-Event-ID replay | Events resume from correct point |

**Command**: `pytest tests/test_dashboard_live_feed.py -k "test_reconnect" -v`

---

### 8. Dashboard Independence (FR-010, SC-007)

**What to verify**: Backend continues operating when dashboard fails.

| Scenario | Expected |
|----------|----------|
| Dashboard process killed | Backend continues trading |
| Dashboard reconnects | State display accurate |
| No dashboard running | Backend unaffected |

**Command**: `pytest tests/test_dashboard_api.py -k "test_independence" -v`

---

## Test Matrix

| Scenario | Unit | Integration (DB) | Manual (Browser) |
|----------|------|------------------|-----------------|
| Overview panel | Yes | Yes | Owner verifies layout |
| Pair management | Yes | Yes (constraints) | Owner verifies CRUD |
| Spread monitor | Yes | — | Owner verifies live updates |
| Risk controls | Yes | Yes (audit log) | Owner verifies validation UX |
| Positions panel | Yes | Yes | Owner verifies P/L updates |
| Emergency stop | Yes | Yes (state transition) | Owner verifies confirmation |
| Disconnect/reconnect | Yes | — | Owner verifies stale indicators |
| Dashboard independence | — | Yes | Owner kills dashboard process |

**Note**: Manual browser tests are required per master plan Phase 6
checklist. The dashboard is a UI feature — type checking and test
suites verify API correctness, not feature correctness. Owner
verification in a browser is essential for acceptance.
