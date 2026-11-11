# Implementation Plan: Phase 2 — Broker Connectivity

**Branch**: `003-broker-connectivity` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-broker-connectivity/spec.md`

## Summary

Implement a read-only broker connectivity layer: TCP connection to MT5
via a MQL5 EA, account discovery, symbol discovery, canonical symbol
mapping, contract specification retrieval, connection state management,
and fail-closed behavior on disconnection. Architecture C (one EA per
pair, TCP loopback). Pilot scope: one Demo account, one pair.

## Technical Context

**Language/Version**: Python 3.12 (backend), MQL5 (EA)

**Primary Dependencies**: Standard library (`socket`, `struct`,
`json`); pytest for testing

**Storage**: In-memory for connection state and symbol registry in
Phase 2. PostgreSQL deferred to Phase 5.

**Testing**: pytest with synthetic socket harness; end-to-end
validation requires native Windows MT5 + WSL backend (owner-performed)

**Target Platform**: WSL2 (backend) ↔ Windows (MT5), TCP at 127.0.0.1

**Project Type**: Algorithmic trading system — broker integration layer

**Performance Goals**: Account info within 5s of startup; disconnect
detection within 10s (per SC-001, SC-002)

**Constraints**: Read-only connector (no order submission); one Demo
account; one active pair; fail-closed on connection loss

**Scale/Scope**: One TCP connection, one account, up to ~100 discovered
symbols, one active pair

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1
design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Platform Target | Pass | TCP loopback 127.0.0.1, WSL ↔ Windows |
| II. Fail-Closed Configuration | Pass | FR-008 marks incomplete contracts ineligible; FR-009 blocks ops on disconnect |
| III. Read-Only Broker Connector | Pass | FR-011 explicitly read-only; no order handler in EA |
| IV. Role Separation | Pass | Claude implements; owner validates end-to-end on MT5 |
| V. Sequential Phase Discipline | Pass | Spec cites §5, §5.1, §5.2, §14.1 |
| VI. Execution Safety Invariants | Pass | Fail-closed on connection loss (FR-009); no order path exists |
| VII. No Invented Parameters | Pass | No trading parameters involved in connectivity |
| VIII. Honest Test Reporting | Pass | Synthetic tests labeled as such; end-to-end requires owner |
| IX. Plan-Aligned Evidence | Pass | Phase 2 status notes "local end-to-end validation pending" |

No violations. No complexity tracking needed.

## Project Structure

### Documentation (this feature)

```text
specs/003-broker-connectivity/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── contracts/
│   └── tcp-protocol.md  # EA ↔ backend message contract
├── quickstart.md        # Phase 1 output (validation guide)
└── checklists/
    └── requirements.md  # Spec quality checklist
```

### Source Code (repository root)

```text
src/scalping_core/
├── broker_adapter.py         # Broker adapter abstraction
├── broker_types.py           # Broker-related type definitions
├── tcp_broker_adapter.py     # TCP implementation of broker adapter
├── mt5_execution_adapter.py  # MT5-specific execution adapter
└── fake_broker.py            # Test double

mql5/
├── ReadOnlyConnector.mq5     # Read-only EA source
├── ReadOnlyConnector.ex5     # Compiled EA
└── ExecutionConnector.mq5    # Future execution EA (not Phase 2)

tests/
├── test_broker_adapter.py    # Broker adapter unit tests
├── test_tcp_broker_adapter.py # TCP adapter tests (socket harness)
└── test_mt5_execution_adapter.py # MT5 adapter tests
```

**Structure Decision**: Existing flat module layout under
`src/scalping_core/`. Phase 2 touches `broker_adapter.py`,
`tcp_broker_adapter.py`, `broker_types.py`, and
`mql5/ReadOnlyConnector.mq5`. Tests use synthetic socket harness.

## Complexity Tracking

No violations to justify.
