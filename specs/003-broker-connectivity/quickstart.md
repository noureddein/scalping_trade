# Quickstart Validation: Phase 2 — Broker Connectivity

**Date**: 2026-11-11

## Prerequisites

- Windows: MT5 terminal with a Demo account logged in
- Windows: `ReadOnlyConnector.mq5` compiled and loaded on a chart
- WSL: Python 3.12 environment with the project package installed
- Both systems on the same machine (loopback 127.0.0.1)

## Validation Scenarios

### 1. Account Discovery (SC-001)

**Goal**: Backend connects and retrieves account info within 5 seconds.

```bash
# Run the backend socket scenarios without MT5:
python3.12 -m pytest tests/test_tcp_broker_adapter.py -q
# The EA should already be running on MT5 for the separate owner check.
```

**Expected**: Backend logs show account_number, broker_name, balance,
equity, margin, and currency within 5 seconds of startup.

**Verify**:
- [x] Synthetic account payload populates all required account values
- [ ] Values match what the owner's MT5 terminal shows
- [x] State becomes CONNECTED after valid account data is received

### 2. Disconnect Detection (SC-002)

**Goal**: Backend detects EA disconnect within 10 seconds.

1. With an active connection, stop the EA in MT5 (remove from chart)
2. Observe backend logs

**Expected**: Within 10 seconds, backend transitions to DISCONNECTED
state and logs the event.

**Verify**:
- [x] Socket harness reports DISCONNECTED after heartbeat timeout
- [x] Broker-dependent operations raise `BrokerUnavailableError`
- [ ] State transition is observed and logged during an owner-run MT5 session

### 3. Automatic Reconnection (SC-002)

**Goal**: Backend reconnects when EA restarts.

1. Reload the EA onto the chart in MT5
2. Observe backend logs

**Expected**: Backend transitions back to CONNECTED and retrieves
fresh account info.

**Verify**:
- [x] Socket harness accepts a replacement EA connection
- [x] Operations remain blocked until fresh account data arrives
- [ ] Owner confirms restart and fresh account values on MT5

### 4. Symbol Discovery (SC-003)

**Goal**: Backend receives the full symbol list from the broker.

```bash
# The EA pushes its symbol list on connect and at each discovery interval.
# To exercise the request path in the socket harness:
python3.12 -m pytest tests/test_tcp_broker_adapter.py -k symbol -q
```

**Expected**: A list of broker symbols with trading permission flags.

**Verify**:
- [x] Synthetic symbol list is parsed with explicit permission flags
- [ ] Owner confirms all broker symbols and permissions on MT5
- [x] Non-Forex symbols are preserved as broker symbols and excluded from Forex canonical mapping

### 5. Canonical Symbol Mapping (SC-006)

**Goal**: Map a broker symbol to a canonical name and retain the
owner-confirmed mapping in the current process.

1. After symbol discovery, create/confirm a mapping: EURUSD →
   (broker-specific name, e.g., EURUSD or EURUSD_)
2. Inspect the owner's mapping in the running process

**Verify**:
- [x] Owner mapping can be updated and reports `confirmed_by_owner`
- [ ] Mapping survives a backend restart (not implemented in this phase; data-model.md specifies in-memory storage)
- [x] Canonical mapping retains `EURUSD` as the strategy-facing name

### 6. Contract Specification Retrieval (SC-004)

**Goal**: All 15 required fields populated from the broker for a
mapped symbol.

```bash
# The EA pushes contract specs for Market Watch symbols on connect and at
# each discovery interval. Exercise parsing with:
python3.12 -m pytest tests/test_tcp_broker_adapter.py -k contract -q
```

**Expected**: Full contract spec with all fields from
[data-model.md](data-model.md). Incomplete commission or margin metadata is
rejected and leaves the symbol ineligible; the adapter never fabricates a
value.

**Verify**:
- [x] Synthetic complete contract payload passes all 15-field validation
- [ ] Values match the owner's MT5 symbol properties
- [x] Missing, null, non-finite, or invalid fields reject the contract without defaults
- [ ] The EA reports commission as available only for no-rule symbols; tiered commission schedules remain ineligible because one flat value cannot represent them

### 7. Fail-Closed Behavior (SC-005)

**Goal**: System blocks operations when disconnected.

1. Stop the EA to trigger disconnect
2. Attempt to request symbols or contract specs

**Expected**: Operations fail with clear error status, not stale data.

**Verify**:
- [x] Operations are rejected while DISCONNECTED or RECONNECTING
- [x] Stale account, symbol, and contract data are not served
- [x] Operations resume only after fresh account information is received

### 8. Malformed Message Handling (FR-010)

**Goal**: Backend survives bad data from EA without crashing.

This is best tested via the synthetic socket harness in pytest, not
via the real EA.

**Verify**:
- [x] Invalid JSON is logged and discarded
- [x] Missing and invalid fields are rejected without crashing
- [x] Connection stays open after malformed JSON messages

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

## Implementation Evidence — 2026-11-11

- Focused broker suites: **108 passed** across the value, mapping, framing,
  and TCP socket tests.
- Full repository suite: **401 passed, 36 skipped, 16 failed**. The failures
  are in `test_operator_resolution.py::test_resolve_order_not_found` and
  `tests/test_startup_supervisor.py`; these files were not changed by this
  feature. The startup failures report the existing test reconciler missing
  `halt_entry_barrier()`.
- The current `ReadOnlyConnector.mq5` source was not compiled in MetaEditor.
  The generated `.ex5` file was not replaced; compiling and checking the EA
  remains an owner-side Windows validation.
- **Owner follow-up required:** no live MT5 Demo session was started here.
  The manual checks above remain open. Symbol mappings are in-memory only,
  per the Phase 2 data model, so SC-006's restart-persistence expectation is
  not met in this phase. Tiered commission schedules are left unknown and
  rejected rather than flattened.
