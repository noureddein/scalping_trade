# Tasks: Phase 0 — Project Bootstrap

**Input**: Design documents from `specs/001-phase0-bootstrap/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, quickstart.md

**Note**: Phase 0 is a verification phase. No application code is written. Tasks are
scripted checks and owner-verified inspections that produce pass/fail evidence.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4)
- Include exact file paths or commands in descriptions

---

## Phase 1: Setup

**Purpose**: Prepare the verification environment

- [X] T001 Create verification script at scripts/verify_phase0.sh that runs all automated checks from quickstart.md and outputs a structured PASS/FAIL summary

---

## Phase 2: Foundational

**Purpose**: No foundational tasks — Phase 0 has no shared infrastructure prerequisites

**Checkpoint**: Setup complete, verification can begin

---

## Phase 3: User Story 1 — Standalone Project Exists (Priority: P1) 🎯 MVP

**Goal**: Confirm the project directory, Git repository, and Python package exist independently

**Independent Test**: Run `git status` in project root; read `pyproject.toml`; grep for cross-references

- [X] T002 [P] [US1] Verify .git directory exists and `git status` runs without error in /home/noureddein/my_projects/scalping_trade/
- [X] T003 [P] [US1] Verify pyproject.toml declares the scalping package name, requires Python >= 3.12, and contains project metadata
- [X] T004 [US1] Run recursive grep across the project tree for references to the owner's existing trading system paths, Docker configs, shared databases, or MT5 bridge — expected result: zero matches (FR-006, SC-003)

**Checkpoint**: Project exists as a standalone entity with its own identity

---

## Phase 4: User Story 2 — Core Documentation Present (Priority: P1)

**Goal**: Confirm both source-of-truth documents exist and are consistent

**Independent Test**: Check file existence, non-empty content, and cross-document consistency

- [X] T005 [P] [US2] Verify FOREX_SCALPING_MASTER_PLAN.md exists and is non-empty
- [X] T006 [P] [US2] Verify TRADING_STRATEGY_DESIGN.md exists and is non-empty
- [X] T007 [US2] Spot-check consistency between the two documents on shared topics (phase status, safety gates, architecture) — report any contradictions to the owner per constitution Sources of Truth rule

**Checkpoint**: Source-of-truth documents are present and internally consistent

---

## Phase 5: User Story 3 — Environment and Topology Recorded (Priority: P2)

**Goal**: Confirm the approved development topology is recorded in the master plan

**Independent Test**: Search master plan for topology keywords

- [X] T008 [P] [US3] Verify FOREX_SCALPING_MASTER_PLAN.md contains the approved topology: Python 3.12 in WSL, native MT5 on Windows, TCP loopback at 127.0.0.1, Architecture C
- [X] T009 [US3] Verify Phase 0 exit evidence in the master plan states the project path is independent and no external production system or database is reused

**Checkpoint**: Topology and architecture decisions are documented and match constitution Principle I

---

## Phase 6: User Story 4 — Repository Hygiene State Acknowledged (Priority: P3)

**Goal**: Confirm the uncommitted/untracked state is intentional and retained

**Independent Test**: Run `git status` and `git log`

- [X] T010 [US4] Run `git log` and confirm no unauthorized commits exist; run `git status` and confirm project files are untracked (FR-007, SC-005)

**Checkpoint**: Repository hygiene matches the owner-directed state

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Assemble evidence and report results

- [X] T011 Run the verification script (T001) end-to-end and capture output as Phase 0 acceptance evidence
- [X] T012 Fill the Status column in quickstart.md success summary table with actual PASS/FAIL results
- [X] T013 Report any failures or unexpected states to the owner with specific remediation steps

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — T001 can start immediately
- **User Stories (Phases 3–6)**: Can all run in parallel after T001
  - US1 and US2 are both P1 and independent
  - US3 depends only on the master plan file (no US1/US2 dependency)
  - US4 is independent
- **Polish (Phase 7)**: Depends on all user stories completing

### User Story Dependencies

- **US1 (P1)**: No dependencies on other stories
- **US2 (P1)**: No dependencies on other stories
- **US3 (P2)**: No dependencies on other stories
- **US4 (P3)**: No dependencies on other stories

### Parallel Opportunities

All four user stories can run in parallel since they verify different aspects of the project:
- US1: project structure and package
- US2: documentation files
- US3: topology in master plan
- US4: git state

Within US1, T002/T003/T004 can partially parallelize (T002 and T003 are [P]).
Within US2, T005 and T006 are [P].

---

## Parallel Example: All User Stories

```bash
# All user stories can start simultaneously:
# US1: T002, T003 (parallel), then T004
# US2: T005, T006 (parallel), then T007
# US3: T008 (parallel), then T009
# US4: T010
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete T001 (setup verification script)
2. Run T002–T004 (US1: standalone project verification)
3. **STOP and VALIDATE**: Project identity confirmed
4. Proceed to US2–US4

### Incremental Delivery

1. T001 → verification tooling ready
2. US1 (T002–T004) → project identity confirmed
3. US2 (T005–T007) → documentation confirmed
4. US3 (T008–T009) → topology confirmed
5. US4 (T010) → repo hygiene confirmed
6. T011–T013 → evidence assembled, Phase 0 accepted

---

## Notes

- Phase 0 produces no application code — all tasks are verification
- T001 creates the only new file (verification script)
- All other tasks observe and report existing state
- Do not stage or commit without owner direction (FR-007)
- If any check fails, report to owner — do not auto-fix
