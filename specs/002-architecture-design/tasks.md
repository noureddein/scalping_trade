# Tasks: Phase 1 — Architecture and Design

**Input**: Design documents from `specs/002-architecture-design/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, quickstart.md

**Note**: Phase 1 is a design validation phase. No application code is written or modified.
Tasks are document reviews, cross-reference audits, and consistency checks that produce
pass/fail evidence against the master plan and strategy design document.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different documents, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Include exact file paths or section references in descriptions

---

## Phase 1: Setup

**Purpose**: Prepare validation tools and load documents

- [X] T001 Create validation script at scripts/verify_phase1.sh that runs all automated cross-reference and consistency checks from quickstart.md and outputs a structured PASS/FAIL summary

---

## Phase 2: Foundational

**Purpose**: Load and index both source-of-truth documents for cross-referencing

- [X] T002 Build a section index of FOREX_SCALPING_MASTER_PLAN.md (§§1–21 with line ranges) to enable targeted validation of each domain and cross-reference auditing; see section-index.md

**Checkpoint**: Section index ready, validation can begin

---

## Phase 3: User Story 1 — Approved Architecture Recorded (Priority: P1) 🎯 MVP

**Goal**: Confirm §14.1 contains one approved decision per architecture area with no open research questions

**Independent Test**: Read §14.1 and verify every row has a concrete approved value, no "TBD"

- [X] T003 [US1] Review FOREX_SCALPING_MASTER_PLAN.md §14.1 (approved decisions table) and verify every architecture area has a single, unambiguous approved value — no "TBD", no open research questions
- [X] T004 [US1] Cross-reference §14.1 approved decisions against §§3–13 — verify no section contradicts the approved decision; where earlier sections present research options, confirm the approved option is clearly identified
- [X] T005 [US1] Cross-reference §14.1 approved decisions against constitution Principles I–IX — verify all 9 principles are consistent with the approved decisions

**Checkpoint**: Architecture decisions validated as complete and internally consistent

---

## Phase 4: User Story 2 — System Design Domains Specified (Priority: P1)

**Goal**: Confirm each domain section (§§5–14) states requirements, entities, and constraints

**Independent Test**: Review each domain for completeness — no gaps requiring implementer invention

- [X] T006 [P] [US2] Review FOREX_SCALPING_MASTER_PLAN.md §§5–6 (broker abstraction, symbol registry/contract specs) — verify functional requirements, key entities, and constraints are stated without gaps
- [X] T007 [P] [US2] Review FOREX_SCALPING_MASTER_PLAN.md §§7–8 (pair management, strategy architecture) — verify functional requirements, key entities, and constraints are stated without gaps
- [X] T008 [P] [US2] Review FOREX_SCALPING_MASTER_PLAN.md §§9–11 (trade entry/execution, position management, P/L management) — verify functional requirements, key entities, and constraints are stated without gaps
- [X] T009 [P] [US2] Review FOREX_SCALPING_MASTER_PLAN.md §§12–13 (daily risk management, spread intelligence, dashboard) — verify functional requirements, key entities, and constraints are stated without gaps
- [X] T010 [US2] Review FOREX_SCALPING_MASTER_PLAN.md §14.2 (database design) — verify conceptual entities, integrity constraints, migration policy, cross-system order safety rules, and admission/recovery contracts are specified; entity-list contradiction reported in quickstart.md

**Checkpoint**: All domain sections pass completeness review

---

## Phase 5: User Story 3 — Unresolved Decisions Catalogued (Priority: P1)

**Goal**: Confirm §19 lists all unresolved decisions with context for owner resolution

**Independent Test**: Read §19; verify each entry has number, description, and blocking context

- [X] T011 [US3] Review FOREX_SCALPING_MASTER_PLAN.md §19 — verify all unresolved decisions are numbered with descriptions and sufficient context for the owner to make an informed choice; report the total count (18; context gaps reported in quickstart.md)
- [X] T012 [US3] Audit all cross-references to §19 throughout the master plan — verify every "§19" or "unresolved decision" reference points to a valid §19 entry number, and no dangling references exist
- [X] T013 [US3] Verify no strategy threshold, exit rule, spread limit, slippage tolerance, dwell time, data source, or acceptance criterion has been invented anywhere in the plan — each must appear as an unresolved §19 entry (FR-005, constitution Principle VII); unlisted 60-second spread-stability requirement reported in quickstart.md

**Checkpoint**: All unresolved decisions are tracked and no parameters are invented

---

## Phase 6: User Story 4 — Source-of-Truth Consistency (Priority: P2)

**Goal**: Confirm master plan and strategy design document are consistent

**Independent Test**: Compare shared topics between documents

- [X] T014 [P] [US4] Verify TRADING_STRATEGY_DESIGN.md header/scope explicitly states that FOREX_SCALPING_MASTER_PLAN.md is canonical for phase status and safety gates
- [X] T015 [US4] Compare strategy names, regime states, data conventions, and safety constraints between TRADING_STRATEGY_DESIGN.md and FOREX_SCALPING_MASTER_PLAN.md §7 — report any contradictions to the owner

**Checkpoint**: Both documents are consistent on all shared topics

---

## Phase 7: User Story 5 — Definition of Success Documented (Priority: P2)

**Goal**: Confirm §21 contains concrete, testable production-readiness criteria

**Independent Test**: Read §21 and verify each criterion is verifiable

- [X] T016 [US5] Review FOREX_SCALPING_MASTER_PLAN.md §21 — verify it contains at least 10 concrete, testable production-readiness criteria (SC-005)
- [X] T017 [US5] Verify §21 includes the final rule: live trading requires explicit owner authorization — and that this is stated as a non-negotiable gate, not a suggestion

**Checkpoint**: Definition of success is concrete, measurable, and includes the live-trading authorization gate

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Assemble evidence and report results

- [X] T018 Run the validation script (T001) end-to-end and capture output as Phase 1 acceptance evidence
- [X] T019 Fill the quickstart.md validation summary with actual PASS/FAIL results from each check
- [X] T020 Report failures, contradictions, or incomplete sections in quickstart.md with section references and remediation suggestions

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — T001 can start immediately
- **Foundational (Phase 2)**: T002 depends on T001
- **User Stories (Phases 3–7)**: All depend on T002 (section index)
  - US1, US2, US3 are all P1 and can run in parallel
  - US4 and US5 are P2 and can run in parallel with each other
- **Polish (Phase 8)**: Depends on all user stories completing

### User Story Dependencies

- **US1 (P1)**: No dependencies on other stories
- **US2 (P1)**: No dependencies on other stories
- **US3 (P1)**: No dependencies on other stories
- **US4 (P2)**: No dependencies on other stories
- **US5 (P2)**: No dependencies on other stories

### Parallel Opportunities

US1, US2, and US3 can all run in parallel — they audit different sections of the master plan:
- US1: §14.1 approved decisions
- US2: §§5–14 domain sections
- US3: §19 unresolved decisions

Within US2, T006–T009 are [P] (different domain sections).
US4 and US5 can also run in parallel with each other.

---

## Parallel Example: All P1 Stories

```bash
# US1, US2, US3 can all start simultaneously:
# US1: T003 → T004 → T005 (sequential within story)
# US2: T006, T007, T008, T009 (parallel domain reviews) → T010
# US3: T011 → T012 → T013
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete T001 (setup validation script)
2. Complete T002 (section index)
3. Complete T003–T005 (US1: architecture decisions audit)
4. **STOP and VALIDATE**: Core architecture is verified
5. Proceed to US2–US5

### Incremental Delivery

1. T001–T002 → tooling and index ready
2. US1 (T003–T005) → architecture decisions confirmed
3. US2 (T006–T010) → domain completeness confirmed
4. US3 (T011–T013) → unresolved decisions tracked
5. US4 (T014–T015) → cross-document consistency confirmed
6. US5 (T016–T017) → success criteria confirmed
7. T018–T020 → evidence assembled, Phase 1 accepted

---

## Notes

- Phase 1 produces no application code — all tasks are document validation
- T001 creates the only new file (validation script)
- All other tasks review and audit existing documents
- Do not modify source code (constitution Principle IV: design phase)
- Contradictions found must be reported to the owner, not silently resolved
- Do not stage or commit without owner direction
