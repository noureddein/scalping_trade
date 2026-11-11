# Implementation Plan: Phase 0 — Project Bootstrap

**Branch**: `001-phase0-bootstrap` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-phase0-bootstrap/spec.md`

## Summary

Validate that the standalone project structure, core documentation,
package manifest, approved topology record, and repository hygiene state
all meet the Phase 0 exit criteria defined in the master plan. This is a
verification phase — no application code is written.

## Technical Context

**Language/Version**: Python 3.12 (declared in `pyproject.toml`, not
exercised in this phase)

**Primary Dependencies**: None for this phase (verification only)

**Storage**: N/A

**Testing**: Manual inspection and scripted checks (file existence,
content search, git status)

**Target Platform**: WSL2 (verification host)

**Project Type**: Algorithmic trading system (bootstrap verification)

**Performance Goals**: N/A

**Constraints**: No commits or staging without owner direction; no
modification of the existing trading system

**Scale/Scope**: Single project directory, 2 source-of-truth documents,
1 package manifest

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1
design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Platform Target | Pass | Topology recorded in master plan §14.1 |
| II. Fail-Closed Configuration | N/A | No strategies in bootstrap |
| III. Read-Only Broker Connector | N/A | No broker interaction in bootstrap |
| IV. Role Separation | Pass | Claude creates spec/plan; owner validates |
| V. Sequential Phase Discipline | Pass | Phase 0 is the first phase; spec cites master plan Phase 0 and §1.1 |
| VI. Execution Safety Invariants | N/A | No execution in bootstrap |
| VII. No Invented Parameters | Pass | No parameters to invent |
| VIII. Honest Test Reporting | Pass | Verification results will be reported as-observed |
| IX. Plan-Aligned Evidence | Pass | All claims traceable to master plan |

No violations. No complexity tracking needed.

## Project Structure

### Documentation (this feature)

```text
specs/001-phase0-bootstrap/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output (below)
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── quickstart.md        # Phase 1 output (verification guide)
```

### Source Code (repository root)

```text
src/                     # Python package (exists, not modified)
mql5/                    # MQL5 EA source (exists, not modified)
tests/                   # Test suite (exists, not modified)
migrations/              # DB migrations (exists, not modified)
prototypes/              # Prototypes (exists, not modified)
pyproject.toml           # Package manifest (verified, not modified)
FOREX_SCALPING_MASTER_PLAN.md    # Source of truth #1
TRADING_STRATEGY_DESIGN.md       # Source of truth #2
```

**Structure Decision**: Existing project structure is verified as-is.
Phase 0 does not create or modify source code.

## Complexity Tracking

No violations to justify.
