# Implementation Plan: Phase 5 — Risk and Execution

**Branch**: `006-risk-execution` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/006-risk-execution/spec.md`

## Summary

Implement pre-trade risk validation ($0.50 loss ceiling, broker stop
minimum, margin, lot constraints), daily risk state machine (ACTIVE
through DISABLED with Asia/Amman reset), durable order lifecycle
(intent → submission → outcome → position), pair reservations with
concurrency safety, startup reconciliation with entry barrier,
operator resolution audit trail, and PostgreSQL persistence with
versioned migrations (001–006). The EA is read-only; broker execution
is a design contract until an order handler is separately approved.

## Technical Context

**Language/Version**: Python 3.12 (backend)

**Primary Dependencies**: Standard library (datetime, zoneinfo,
decimal, dataclasses); psycopg / asyncpg for PostgreSQL; pytest

**Storage**: PostgreSQL (independent instance, least-privilege
application role). Versioned migrations 001–006 exist but are
unapplied. Integration tests require a dedicated disposable database.

**Testing**: pytest for unit tests (mocked DB); PostgreSQL integration
tests on disposable database; concurrent-process tests for
reservations/barriers

**Target Platform**: WSL2 (backend) ↔ Windows (MT5 read-only)

**Project Type**: Algorithmic trading system — risk/execution layer

**Performance Goals**: No specific latency target (EA is read-only;
broker execution path is a design contract). Risk validation must
complete before any broker submission.

**Constraints**: Never widen stops (FR-004); never auto-resubmit
(FR-011); never force-close on limits (FR-020); durable-before-broker
(FR-009); fail-closed on DB unavailable; 7 deferred decisions (§19
#1,6,7,11-15)

**Scale/Scope**: One pair pilot; 0.01 fixed lot; single operator

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1
design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Platform Target | Pass | Python 3.12 backend + PostgreSQL; EA read-only |
| II. Fail-Closed Configuration | Pass | FR-002/003: reject entry on risk failure; DB down = no entry |
| III. Read-Only Broker Connector | Pass | EA has no order handler; execution is design contract only |
| IV. Role Separation | Pass | Claude implements; operator resolves ambiguous orders |
| V. Sequential Phase Discipline | Pass | Spec cites §8–§11, §14, §14.1–14.2 |
| VI. Execution Safety Invariants | Pass | FR-004/009/011/013/014/020: never widen/resubmit/force-close |
| VII. No Invented Parameters | Pass | $0.50/$15/$5 from master plan; exit rules deferred §19 |
| VIII. Honest Test Reporting | Pass | Integration tests require disposable DB; broker path is design contract |
| IX. Plan-Aligned Evidence | Pass | Phase 5 status: "partial implementation; not execution-ready" |

No violations.

## Project Structure

### Documentation (this feature)

```text
specs/006-risk-execution/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── contracts/
│   └── order-lifecycle.md # Order state machine contract
├── quickstart.md        # Phase 1 output (validation guide)
└── checklists/
    └── requirements.md  # Spec quality checklist
```

### Source Code (repository root)

```text
src/scalping_core/
├── execution_engine.py   # Order lifecycle, submission, outcome recording
├── risk_gate.py          # Pre-trade risk validation, lot/stop/margin checks
├── daily_risk.py         # Daily P/L tracking, state machine, Asia/Amman reset
├── pair_reservation.py   # Durable pair locks, concurrency serialization
├── reconciliation.py     # Startup reconciliation, entry barrier
├── order_types.py        # Order state machine, intent, outcome types
├── position_manager.py   # Position creation, tracking, settlement
├── durable_store.py      # PostgreSQL store abstraction
└── broker_types.py       # Shared types (extends Phase 2)

migrations/
├── 001_*.sql through 006_*.sql  # Existing unapplied migrations

tests/
├── test_execution_engine.py     # Order lifecycle tests
├── test_admission_protocol.py   # Barrier, reservation, reconciliation
├── test_risk_gate.py            # Risk validation tests
├── test_daily_risk.py           # Daily limits, state machine, timezone
└── test_durable_store.py        # PostgreSQL integration tests
```

**Structure Decision**: Extends existing module layout. Most files
already exist from the code scaffold. Phase 5 fills them with
durable state, constraint enforcement, and reconciliation logic.

## Complexity Tracking

No violations to justify.
