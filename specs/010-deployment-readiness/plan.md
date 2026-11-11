# Implementation Plan: Phase 9 — Deployment Readiness

**Branch**: `010-deployment-readiness` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/010-deployment-readiness/spec.md`

## Summary

Final phase before production evaluation. Validates that the system
is operationally ready: survives failures, protects secrets, measures
performance, documents operations, and assembles verifiable evidence
for all prior phases. Does not authorize live trading.

## Technical Context

**Language/Version**: Python 3.12 (backend), MQL5 (EA), shell scripts
(operational tooling)

**Primary Dependencies**: Existing Phase 0–8 modules; standard OS
and database tooling for backup/monitoring

**Storage**: PostgreSQL (existing instance; backup/restore procedures)

**Testing**: pytest for automated checks; manual owner verification
for recovery scenarios, security audit, and performance qualification

**Target Platform**: WSL2 + native Windows MT5 (owner-approved
topology; no Ubuntu/Wine assumed)

**Project Type**: Operational readiness validation and documentation
(minimal new application code; primarily procedures, tests, and
evidence collection)

**Performance Goals**: Owner-defined thresholds (not invented —
Constitution Principle VII)

**Constraints**: All prior phases (0–8) must be accepted. Live
trading authorization is out of scope. Deployment topology must be
owner-approved before work begins.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| I | Platform Target | PASS | WSL + native Windows MT5; no Ubuntu/Wine assumed. pyproject.toml requires-python updated to >=3.12 per constitution (current WSL env is 3.10.12 — env upgrade needed separately) |
| II | Fail-Closed Configuration | PASS | System enters fail-closed on DB outage or missing config |
| III | Read-Only Broker Connector | PASS | Phase 9 does not modify the broker connector; live trading auth is explicitly out of scope |
| IV | Role Separation | PASS | Claude implements; Codex audits; owner performs recovery scenarios and security review |
| V | Sequential Phase Discipline | PASS | Requires all Phases 0–8 accepted first |
| VI | Execution Safety Invariants | PASS | Recovery tests validate that all safety mechanisms survive failures |
| VII | No Invented Parameters | PASS | Performance thresholds are owner-defined; spec refuses to pass qualification without them |
| VIII | Honest Test Reporting | PASS | Evidence package requires verifiable test output for every acceptance criterion |
| IX | Plan-Aligned Evidence | PASS | Release acceptance maps directly to §17 master plan criteria |

## Project Structure

### Documentation (this feature)

```text
specs/010-deployment-readiness/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── release-acceptance.md
└── tasks.md              # Created by /speckit-tasks
```

### Source Code (repository root)

```text
src/
├── scalping_core/
│   ├── deploy/
│   │   ├── health.py         # Health check endpoints/probes
│   │   ├── secrets_audit.py  # Source code secret scanner
│   │   └── evidence.py       # Evidence package assembly
│   └── ...                   # Existing Phase 0–8 modules

tests/
├── test_health_checks.py
├── test_secrets_audit.py
└── test_evidence_package.py

ops/
├── runbook.md                # Deployment runbook
├── backup-restore.sh         # Database backup/restore script
├── recovery-checklist.md     # Recovery test checklist
└── monitoring-setup.md       # Monitoring configuration guide
```

**Structure Decision**: Minimal new application code — most Phase 9
deliverables are operational documentation and procedures. The
`deploy/` subpackage holds the small amount of automation (health
checks, secret scanning, evidence assembly). The `ops/` directory
holds operator-facing documentation that lives outside the Python
package.
