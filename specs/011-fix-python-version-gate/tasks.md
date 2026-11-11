# Tasks: Fix Phase 0 Python Version Gate

**Input**: Design documents from `specs/011-fix-python-version-gate/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, quickstart.md

**Note**: This is a corrective metadata fix. No application code, database, broker, staging,
or commit operations. Four existing files are touched; no new files are created.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: No setup needed — all files already exist

(No tasks — the verification script, quickstart, pyproject.toml, and master plan are all in place.)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: No foundational infrastructure needed — this is a metadata correction

**Checkpoint**: Proceed directly to user stories

---

## Phase 3: User Story 1 — Package Manifest Declares Python 3.12 (Priority: P1) 🎯 MVP

**Goal**: `pyproject.toml` declares `requires-python = ">=3.12"`

**Independent Test**: `grep -E '^requires-python' pyproject.toml` returns `requires-python = ">=3.12"`

- [x] T001 [US1] Change `requires-python = ">=3.10"` to `requires-python = ">=3.12"` in pyproject.toml (FR-001, SC-001). This is the sole code change in the entire feature.

**Checkpoint**: Manifest satisfies Phase 0 spec FR-002 and Constitution Principle I

---

## Phase 4: User Story 2 — Quickstart Validation Checks Exact Version (Priority: P1)

**Goal**: Phase 0 quickstart step 2 checks for `requires-python = ">=3.12"` specifically, not just `grep -q "python"`

**Independent Test**: Read specs/001-phase0-bootstrap/quickstart.md step 2 — it must use a pattern that rejects `>=3.10`

- [x] T002 [US2] Update step 2 in specs/001-phase0-bootstrap/quickstart.md: replace the current `grep -q "python" pyproject.toml` check with `grep -Eq '^requires-python[[:space:]]*=[[:space:]]*">=3\.12"' pyproject.toml` (or equivalent) that verifies the exact `>=3.12` value, matching the pattern used by scripts/verify_phase0.sh `has_package_metadata` (FR-002, SC-002)

**Checkpoint**: Quickstart and verification script now check the same thing

---

## Phase 5: User Story 3 — Verification Script Consistent (Priority: P1)

**Goal**: `scripts/verify_phase0.sh` reports PASS for the pyproject.toml check after the manifest fix

**Independent Test**: Run `bash scripts/verify_phase0.sh` — the "pyproject.toml declares scalping package metadata and Python >=3.12" line reports PASS

- [x] T003 [US3] Run `bash scripts/verify_phase0.sh` and capture the full output. Confirm the pyproject.toml check reports PASS. Record the output as evidence (FR-003, FR-004, SC-003). No changes to the script — it already checks for `>=3.12`

**Checkpoint**: Verification script and quickstart agree on PASS

---

## Phase 6: User Story 4 — Evidence Recorded and Status Distinguished (Priority: P2)

**Goal**: Quickstart summary shows actual latest results; master plan status reflects whether all checks passed

**Independent Test**: Read the quickstart summary table — every row shows the actual result from the latest verifier run. Read the master plan Phase 0 status — it reflects the verifier outcome.

- [x] T004 [US4] Update the success summary table in specs/001-phase0-bootstrap/quickstart.md: set every row's Status column to the actual PASS/FAIL result from the T003 verifier run. Replace the current "FAIL — requires `>=3.10`" on the Package manifest row with the actual result. Remove any stale results from prior runs (FR-005, SC-004)
- [x] T005 [US4] Update the "Observed run" line at the bottom of specs/001-phase0-bootstrap/quickstart.md to reflect the latest verifier output (count of passed/failed checks)
- [x] T006 [US4] If and only if ALL checks in the T003 verifier run reported PASS: update the Phase 0 status line in FOREX_SCALPING_MASTER_PLAN.md to reflect that all exit checks have passed. If any check reported FAIL: do NOT update the status to claim completion — instead note which checks failed (FR-006, SC-005). Constitution Principle VIII: only report what actually passed

**Checkpoint**: Evidence chain complete — manifest, quickstart, verifier, and master plan are all consistent

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final validation

- [x] T007 Run specs/011-fix-python-version-gate/quickstart.md validation steps 1–5 end-to-end and confirm all rows in the success summary would report PASS
- [x] T008 Verify no application code was changed: `git diff src/ mql5/ tests/ migrations/` shows zero changes (FR-007). Verify no staging or commits occurred (FR-008)

---

## Dependencies & Execution Order

### Phase Dependencies

- **US1 (Phase 3)**: No dependencies — start immediately
- **US2 (Phase 4)**: No dependency on US1 (different file), but logically follows
- **US3 (Phase 5)**: Depends on US1 (manifest must be fixed before rerunning verifier)
- **US4 (Phase 6)**: Depends on US3 (needs verifier output to record evidence)
- **Polish (Phase 7)**: Depends on all user stories

### Critical Path

```
T001 (fix manifest) → T003 (rerun verifier) → T004/T005/T006 (record evidence)
T002 (tighten quickstart) can run in parallel with T001
```

### Parallel Opportunities

- T001 and T002 can run in parallel (different files: pyproject.toml vs quickstart.md)
- T004 and T005 can run in parallel (same file but different sections)
- T007 and T008 can run in parallel (different verification targets)

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. T001: Fix the one field in pyproject.toml
2. **STOP and VALIDATE**: `grep -E '^requires-python' pyproject.toml` returns `">=3.12"`
3. Proceed to T002–T006

### Incremental Delivery

1. T001 + T002 (parallel) → manifest fixed, quickstart tightened
2. T003 → verifier rerun, evidence captured
3. T004 + T005 + T006 → evidence recorded, status updated
4. T007 + T008 → final validation

---

## Notes

- Total: 8 tasks across 4 user stories + polish
- No new files created — all tasks modify or verify existing files
- The verification script (scripts/verify_phase0.sh) is NOT modified — only rerun
- Do not stage or commit (FR-008) — the owner directs git operations
- If the verifier reveals other failures beyond pyproject.toml, report them but do not fix (out of scope)
