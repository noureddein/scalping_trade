# Implementation Plan: Phase 8 — Demo Forward Test

**Branch**: `009-demo-forward-test` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/009-demo-forward-test/spec.md`

## Summary

Enable order submission to a Demo account through the existing Phase 5
execution pipeline. This is the first broker-mutating phase — it
requires explicit owner approval for: Demo scope definition, EA order
handler implementation, and activation. All Phase 5 safety mechanisms
remain active. Every event is recorded. Results do not authorize live
trading.

## Technical Context

**Language/Version**: Python 3.12 (backend), MQL5 (EA order handler)

**Primary Dependencies**: Existing Phase 2–6 modules; new EA order
handler functions in MQL5

**Storage**: PostgreSQL (existing Phase 5 tables + evidence log
extension)

**Testing**: pytest for backend; manual owner verification against
MT5 terminal for broker interactions

**Target Platform**: WSL2 + native Windows MT5 (Demo account)

**Project Type**: Extension of existing system (new EA order handler +
evidence recording + Demo scope gate)

**Performance Goals**: Order submission latency measured but no
target — real broker conditions determine latency

**Constraints**: Demo account only. Single pair. Owner-approved
scope. Constitution Principle III gate.

**Scale/Scope**: One Demo account, one pair, 0.01 lot, owner-defined
duration

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| I | Platform Target | PASS | Python 3.12 WSL + native Windows MT5 Demo |
| II | Fail-Closed Configuration | PASS | Refuses orders without Demo scope approval |
| III | Read-Only Broker Connector | **GATE** | EA order handler requires separate explicit owner approval before implementation. Current EA is read-only. |
| IV | Role Separation | PASS | Claude implements; Codex audits; owner approves Demo scope and verifies broker terminal |
| V | Sequential Phase Discipline | PASS | Phase 8 follows Phases 0–7; requires Phase 7 acceptance criteria met |
| VI | Execution Safety Invariants | PASS | All Phase 5 mechanisms active: durable intent, pair reservation, reconciliation, daily limits |
| VII | No Invented Parameters | PASS | Demo scope (pair, lot, duration, stops) defined by owner |
| VIII | Honest Test Reporting | PASS | Complete evidence recording; no positive expectancy from small samples |
| IX | Plan-Aligned Evidence | PASS | Every signal, decision, and broker interaction recorded |

**Principle III Note**: This is the first phase that transitions the
EA from read-only to order-capable. The owner must explicitly approve
the EA order handler implementation before any code is written. The
approval is scoped to Demo only — it does not authorize live trading.

## Project Structure

### Documentation (this feature)

```text
specs/009-demo-forward-test/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── demo-scope.md
└── tasks.md              # Created by /speckit-tasks
```

### Source Code (repository root)

```text
mql5/
├── ReadOnlyConnector.mq5     # Existing read-only EA
└── DemoOrderHandler.mq5      # NEW: Demo-only order handler (requires owner approval)

src/
├── scalping_core/
│   ├── demo/
│   │   ├── scope.py          # Demo scope approval gate
│   │   ├── evidence.py       # Complete event recording
│   │   └── report.py         # Forward test report generation
│   └── ...                   # Existing Phase 2–6 modules

tests/
├── test_demo_scope.py
├── test_demo_evidence.py
└── test_demo_report.py

migrations/
└── 011_demo_forward_test.sql
```

**Structure Decision**: Minimal additions — `demo/` subpackage for
scope gate, evidence recording, and reporting. The EA order handler
is a new MQL5 file (not a modification of the read-only connector).
The existing Phase 5 execution pipeline is used unchanged.
