# Feature Specification: Phase 1 — Architecture and Design

**Feature Branch**: `002-architecture-design`

**Created**: 2026-11-10

**Status**: Draft

**Input**: User description: "Create a specification for the Phase 1: Architecture and design"

**Master Plan Reference**: Phase 1 (line 1043), §§3–14, §19, §21

## User Scenarios & Testing

### User Story 1 - Approved Architecture Recorded (Priority: P1)

The project owner verifies that all approved architecture decisions are
consolidated in the master plan and are internally consistent. This
includes the runtime architecture (Architecture C), development
topology, EA topology, durable state choice, safety policies, and
trading authority boundaries.

**Why this priority**: Every subsequent implementation phase depends on
unambiguous, owner-approved architecture decisions. A missing or
contradictory decision blocks safe implementation.

**Independent Test**: Read §14.1 of the master plan and confirm each
decision area has a single, unambiguous approved value that does not
contradict any other section of the plan.

**Acceptance Scenarios**:

1. **Given** the master plan §14.1, **When** the owner reviews the
   approved decisions table, **Then** every row has a concrete approved
   value (not "TBD" or a research question).
2. **Given** the master plan, **When** §§3–13 are compared with §14.1,
   **Then** no section contradicts the approved decisions; where earlier
   sections present research options, the approved decision is clearly
   identified.
3. **Given** the approved decisions, **When** the constitution is
   checked, **Then** Principles I–IX are consistent with §14.1.

---

### User Story 2 - System Design Domains Specified (Priority: P1)

The project owner verifies that the master plan specifies design
requirements for each major system domain: broker abstraction, symbol
registry, contract specifications, pair management, strategy
architecture, trade entry/execution, position management, profit/loss
management, daily risk management, spread intelligence, dashboard, and
database.

**Why this priority**: Each domain becomes an implementation phase. The
design must be complete enough that implementers know what to build
without inventing requirements.

**Independent Test**: For each domain listed in §§5–14, confirm the
master plan states what the system must do, what entities are involved,
and what safety/correctness constraints apply.

**Acceptance Scenarios**:

1. **Given** the master plan §§5–14, **When** each domain section is
   reviewed, **Then** it states functional requirements, key entities,
   and constraints without gaps that would force an implementer to guess.
2. **Given** the strategy design document, **When** compared with §7 of
   the master plan, **Then** the strategy document expands §7 without
   contradicting the master plan's requirements or safety gates.
3. **Given** the database design section (§14.2), **When** reviewed,
   **Then** it lists conceptual entities, integrity constraints,
   migration policy, and cross-system order safety requirements.

---

### User Story 3 - Unresolved Decisions Catalogued (Priority: P1)

The project owner verifies that all unresolved policy and parameter
decisions are explicitly listed in §19, with enough context that the
owner can make an informed choice when the time comes.

**Why this priority**: Unresolved decisions are the Phase 1 "remaining"
gate. Each must be tracked so it is resolved before its corresponding
behavior is enabled — per constitution Principles II and VII.

**Independent Test**: Read §19 and confirm each item names the decision,
explains why it matters, and identifies which phase or behavior it
blocks.

**Acceptance Scenarios**:

1. **Given** §19, **When** each decision is reviewed, **Then** it has
   a number, a description, and enough context to understand the
   tradeoff.
2. **Given** the master plan, **When** searching for "unresolved",
   "decision", or "§19", **Then** every cross-reference to a deferred
   decision points to a valid §19 entry.
3. **Given** the constitution Principle VII, **When** §19 is reviewed,
   **Then** no strategy threshold, exit rule, spread limit, or
   acceptance criterion has been invented — each is listed as
   unresolved.

---

### User Story 4 - Source-of-Truth Consistency (Priority: P2)

The project owner verifies that the master plan and the trading strategy
design document are consistent on all shared topics, and that the
strategy document explicitly defers to the master plan on phase status,
safety gates, and unresolved decisions.

**Why this priority**: Two divergent sources of truth create ambiguity
that can lead to incorrect implementation. The constitution requires
conflicts to be reported, not silently resolved.

**Independent Test**: Compare the strategy design document header and
scope declaration with the master plan; check that strategy hypotheses
in the design doc match §7 of the master plan.

**Acceptance Scenarios**:

1. **Given** `TRADING_STRATEGY_DESIGN.md` header, **When** read,
   **Then** it states that the master plan is canonical for status and
   safety gates.
2. **Given** both documents, **When** strategy names, regime states, and
   data conventions are compared, **Then** no contradictions exist.

---

### User Story 5 - Definition of Success Documented (Priority: P2)

The project owner verifies that the master plan includes a clear,
measurable definition of production readiness (§21) that all phases
work toward.

**Why this priority**: Without a shared definition of done, phase
acceptance criteria may drift or be interpreted inconsistently.

**Independent Test**: Read §21 and confirm each success criterion is
concrete and testable.

**Acceptance Scenarios**:

1. **Given** §21, **When** each criterion is reviewed, **Then** it
   describes a verifiable system behavior, not a vague aspiration.
2. **Given** §21, **When** the final rule is read, **Then** it states
   that live trading requires explicit owner authorization.

---

### Edge Cases

- What happens if an approved decision in §14.1 contradicts a
  requirement in §§5–13? Report the conflict to the owner; do not
  silently override either source.
- What happens if a new domain requirement is discovered during
  implementation that §§5–14 do not cover? Add it to the master plan
  as a proposed requirement and request owner approval before
  implementing.
- What happens if two §19 decisions interact (e.g., partial fills
  affect order correlation)? Document the dependency between decisions
  so the owner resolves them together.

## Requirements

### Functional Requirements

- **FR-001**: The master plan MUST consolidate all approved architecture
  decisions in a single authoritative section (§14.1) that supersedes
  earlier research notes.
- **FR-002**: Each system domain (§§5–14) MUST specify what the system
  does, which entities are involved, and what safety/correctness
  constraints apply.
- **FR-003**: The trading strategy design document MUST expand §7
  without contradicting the master plan and MUST defer to the master
  plan on phase status and safety gates.
- **FR-004**: All unresolved policy and parameter decisions MUST be
  catalogued in §19 with enough context for an informed owner decision.
- **FR-005**: No strategy threshold, exit rule, spread limit, slippage
  tolerance, dwell time, data source, or acceptance criterion may be
  invented — each MUST appear as an unresolved decision until owner-
  approved.
- **FR-006**: The database design (§14.2) MUST specify conceptual
  entities, integrity constraints, cross-system order safety rules,
  migration policy, and admission/recovery contracts.
- **FR-007**: The definition of success (§21) MUST list concrete,
  testable criteria for production readiness including the requirement
  for explicit owner authorization before live trading.
- **FR-008**: The master plan and strategy design document MUST NOT
  contradict each other on any shared topic. Conflicts MUST be reported
  to the owner per the constitution's Sources of Truth rule.

### Key Entities

- **Approved Decisions (§14.1)**: The single authoritative record of
  architecture and operational-policy decisions.
- **System Domains (§§5–13)**: Broker abstraction, symbol registry,
  pair management, strategy architecture, trade entry, position
  management, P/L management, daily risk, spread intelligence,
  dashboard.
- **Database Design (§14.2)**: Conceptual data model, integrity rules,
  and cross-system safety contracts.
- **Unresolved Decisions (§19)**: Catalogued policy/parameter decisions
  awaiting owner approval, each blocking specific behaviors.
- **Definition of Success (§21)**: Production-readiness criteria.

## Success Criteria

### Measurable Outcomes

- **SC-001**: §14.1 contains one approved decision per architecture area
  with no "TBD" or open-ended research questions.
- **SC-002**: Every domain section (§§5–14) passes a completeness
  review: it states requirements, entities, and constraints without
  gaps requiring implementer invention.
- **SC-003**: §19 lists all 18 unresolved decisions with numbered
  entries, descriptions, and sufficient context for owner resolution.
- **SC-004**: A cross-reference audit finds zero dangling §19 references
  and zero contradictions between the master plan and the strategy
  design document.
- **SC-005**: §21 contains at least 10 concrete, testable production-
  readiness criteria including the live-trading authorization rule.
- **SC-006**: The constitution's 9 principles are consistent with all
  approved decisions and design requirements in the master plan.

## Assumptions

- Phase 1 is a design phase — its deliverable is the documented design
  in the master plan and strategy design document, not executable code.
- The master plan already exists and has been iteratively refined; this
  specification validates its completeness, not its initial creation.
- "Design gate complete" (the current Phase 1 status) means the
  architecture is approved for implementation, but unresolved decisions
  in §19 remain open and block their corresponding behaviors.
- The strategy design document is a companion to §7, not a replacement;
  the master plan remains canonical.
