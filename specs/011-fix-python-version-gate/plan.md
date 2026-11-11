# Implementation Plan: Fix Phase 0 Python Version Gate

**Branch**: `011-fix-python-version-gate` | **Date**: 2026-11-11 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/011-fix-python-version-gate/spec.md`

## Summary

Correct the `requires-python` field in `pyproject.toml` from `>=3.10`
to `>=3.12`, tighten the quickstart validation to check the exact
value, rerun the existing verification script, record evidence, and
update the master plan Phase 0 status only if all exit checks pass.
No application code, database, or git operations.

## Technical Context

**Language/Version**: Python 3.12 (declared target; current WSL
environment is 3.10.12 — environment upgrade is out of scope)

**Primary Dependencies**: None — this is a metadata-only correction

**Storage**: N/A

**Testing**: `scripts/verify_phase0.sh` (existing, already checks
for `>=3.12`); manual quickstart validation

**Target Platform**: WSL2 (verification host)

**Project Type**: Corrective metadata fix for an algorithmic trading
system bootstrap phase

**Performance Goals**: N/A

**Constraints**: No application code changes, no broker actions, no
database changes, no staging, no commits (spec FR-007, FR-008)

**Scale/Scope**: One field in one file (`pyproject.toml`), plus
documentation consistency updates in two files

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| I | Platform Target | PASS | This fix enforces Principle I: pyproject.toml will declare Python 3.12 |
| II | Fail-Closed Configuration | N/A | No strategies involved |
| III | Read-Only Broker Connector | N/A | No broker interaction |
| IV | Role Separation | PASS | Claude updates metadata; owner verifies evidence |
| V | Sequential Phase Discipline | PASS | Corrects an unresolved Phase 0 exit-gate failure before downstream phases |
| VI | Execution Safety Invariants | N/A | No execution code touched |
| VII | No Invented Parameters | PASS | `>=3.12` comes from the constitution and Phase 0 spec, not invented |
| VIII | Honest Test Reporting | PASS | Evidence recorded only after actual verifier run; PASS/FAIL distinguished from "check executed" |
| IX | Plan-Aligned Evidence | PASS | Verifier output is the evidence; master plan updated only if all checks pass |

No violations. No complexity tracking needed.

## Project Structure

### Documentation (this feature)

```text
specs/011-fix-python-version-gate/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output (no unknowns — findings only)
├── quickstart.md        # Validation guide
└── checklists/
    └── requirements.md  # Spec quality checklist
```

### Source Code (repository root)

```text
pyproject.toml                              # requires-python fix (sole code change)
scripts/verify_phase0.sh                    # Rerun only — no changes needed
specs/001-phase0-bootstrap/quickstart.md    # Tighten step 2 check
FOREX_SCALPING_MASTER_PLAN.md               # Phase 0 status update (conditional)
```

**Structure Decision**: No new files created. Three files may be
modified: `pyproject.toml` (metadata fix), `specs/001-phase0-bootstrap/quickstart.md`
(tighten step 2 check and update summary), and conditionally
`FOREX_SCALPING_MASTER_PLAN.md` (Phase 0 status update, only if all
verification checks pass). `scripts/verify_phase0.sh` is run
read-only for evidence — it is not modified.

## Complexity Tracking

No violations to justify.
