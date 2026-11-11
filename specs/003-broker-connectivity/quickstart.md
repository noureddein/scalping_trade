# Quickstart Validation: Phase 2 — Broker Connectivity

**Date**: 2026-11-10

## Prerequisites

- Windows: MT5 terminal with a Demo account logged in
- Windows: `ReadOnlyConnector.mq5` compiled and loaded on a chart
- WSL: Python 3.12 environment with the project package installed
- Both systems on the same machine (loopback 127.0.0.1)

## Validation Scenarios

### 1. Account Discovery (SC-001)

**Goal**: Backend connects and retrieves account info within 5 seconds.

```bash
# Start the backend broker adapter (command TBD in tasks.md)
# The EA should already be running on MT5
```

**Expected**: Backend logs show account_number, broker_name, balance,
equity, margin, and currency within 5 seconds of startup.

**Verify**:
- [ ] All 6 account fields populated
- [ ] Values match what MT5 terminal shows
- [ ] Connection state is CONNECTED

### 2. Disconnect Detection (SC-002)

**Goal**: Backend detects EA disconnect within 10 seconds.

1. With an active connection, stop the EA in MT5 (remove from chart)
2. Observe backend logs

**Expected**: Within 10 seconds, backend transitions to DISCONNECTED
state and logs the event.

**Verify**:
- [ ] State change logged within 10s
- [ ] Broker-dependent operations fail with "broker unavailable"

### 3. Automatic Reconnection (SC-002)

**Goal**: Backend reconnects when EA restarts.

1. Reload the EA onto the chart in MT5
2. Observe backend logs

**Expected**: Backend transitions back to CONNECTED and retrieves
fresh account info.

**Verify**:
- [ ] Connection re-established without manual intervention
- [ ] Fresh account info received and logged

### 4. Symbol Discovery (SC-003)

**Goal**: Backend receives the full symbol list from the broker.

```bash
# Trigger symbol discovery (command TBD in tasks.md)
```

**Expected**: A list of broker symbols with trading permission flags.

**Verify**:
- [ ] Symbol list is non-empty
- [ ] Known Forex pairs (e.g., EURUSD) appear with trading_permitted
- [ ] Non-Forex instruments also appear (they won't be mapped)

### 5. Canonical Symbol Mapping (SC-006)

**Goal**: Map a broker symbol to a canonical name and persist the
mapping.

1. After symbol discovery, create/confirm a mapping: EURUSD →
   (broker-specific name, e.g., EURUSD or EURUSD_)
2. Restart the backend
3. Verify the mapping persists

**Verify**:
- [ ] Mapping created successfully
- [ ] After restart, mapping is still present
- [ ] Strategies would reference "EURUSD", not the broker name

### 6. Contract Specification Retrieval (SC-004)

**Goal**: All 13 required fields populated from the broker for a
mapped symbol.

```bash
# Request contract spec for a mapped symbol (command TBD in tasks.md)
```

**Expected**: Full contract spec with all fields from [data-model.md](data-model.md)
ContractSpecification entity.

**Verify**:
- [ ] All fields present and non-default
- [ ] Values match MT5 terminal's symbol properties
- [ ] No fields use assumed/hardcoded values

### 7. Fail-Closed Behavior (SC-005)

**Goal**: System blocks operations when disconnected.

1. Stop the EA to trigger disconnect
2. Attempt to request symbols or contract specs

**Expected**: Operations fail with clear error status, not stale data.

**Verify**:
- [ ] Operations rejected while DISCONNECTED
- [ ] No stale data served
- [ ] Operations succeed again after reconnection

### 8. Malformed Message Handling (FR-010)

**Goal**: Backend survives bad data from EA without crashing.

This is best tested via the synthetic socket harness in pytest, not
via the real EA.

**Verify**:
- [ ] Invalid JSON is logged and discarded
- [ ] Missing fields cause message rejection, not crash
- [ ] Connection stays open after a single bad message

## End-to-End Test Matrix

| Test | Automated (pytest) | Manual (MT5) |
|------|-------------------|--------------|
| Account discovery | Socket harness | Owner validates values |
| Disconnect detection | Socket close | Owner stops EA |
| Reconnection | Socket reconnect | Owner restarts EA |
| Symbol discovery | Synthetic list | Owner checks against MT5 |
| Symbol mapping | Unit test | Owner confirms mapping |
| Contract specs | Synthetic spec | Owner checks against MT5 |
| Fail-closed | State assertions | Owner verifies behavior |
| Malformed messages | Fuzz/inject | N/A |

Automated tests use the synthetic socket harness and are NOT proof of
end-to-end broker integration. The owner must perform manual MT5
validation for Phase 2 acceptance.
