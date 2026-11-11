# Implementation Plan: Phase 6 — Dashboard

**Branch**: `007-dashboard` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/007-dashboard/spec.md`

## Summary

Build an independent monitoring and configuration dashboard for the
forex scalping system. The dashboard reads backend state (positions,
P/L, spreads, risk state) and sends configuration commands. It is not
in the execution path — backend continues operating if the dashboard
is unavailable.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: stdlib, aiohttp (already used by backend
for async HTTP)

**Storage**: PostgreSQL (reads from existing Phase 5 tables; audit
log entries written to new table)

**Testing**: pytest, disposable PostgreSQL for integration tests

**Target Platform**: WSL2 (local web dashboard served on localhost)

**Project Type**: Web application (backend API + lightweight frontend)

**Performance Goals**: Panel loads < 2s, live updates < 1s latency
(SC-001, SC-002)

**Constraints**: Single operator, localhost only, no external auth
for pilot

**Scale/Scope**: One operator, one account, single-pair pilot

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| I | Platform Target | PASS | Python 3.12 in WSL, localhost dashboard |
| II | Fail-Closed Configuration | PASS | Dashboard reads config; backend enforces fail-closed |
| III | Read-Only Broker Connector | PASS | Dashboard sends config commands to backend only; no broker contact |
| IV | Role Separation | PASS | Dashboard is operator tool; Claude implements, Codex audits |
| V | Sequential Phase Discipline | PASS | Phase 6 follows completed Phases 0–5 |
| VI | Execution Safety Invariants | PASS | Dashboard cannot bypass risk gates; emergency stop uses existing DRAINING state |
| VII | No Invented Parameters | PASS | Dashboard exposes existing parameters; no new thresholds invented |
| VIII | Honest Test Reporting | PASS | UI/integration tests required per master plan Phase 6 checklist |
| IX | Plan-Aligned Evidence | PASS | Spec cites §13.1–13.6 and Phase 6 test backlog |

## Project Structure

### Documentation (this feature)

```text
specs/007-dashboard/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── dashboard-api.md
└── tasks.md              # Created by /speckit-tasks
```

### Source Code (repository root)

```text
src/
├── scalping/
│   ├── dashboard/
│   │   ├── api.py            # HTTP API endpoints
│   │   ├── live_feed.py      # Server-sent events for live updates
│   │   ├── audit_log.py      # Configuration change audit logging
│   │   └── emergency.py      # Emergency stop handler
│   └── ...                   # Existing Phase 2–5 modules
├── static/
│   └── dashboard/            # Frontend assets (HTML/CSS/JS)
└── ...

tests/
├── test_dashboard_api.py
├── test_dashboard_live_feed.py
├── test_dashboard_audit.py
└── test_dashboard_emergency.py
```

**Structure Decision**: Single project with a `dashboard/` subpackage
under `src/scalping/`. Frontend is a lightweight static HTML/JS app
served by the same Python process. No separate frontend build step.
