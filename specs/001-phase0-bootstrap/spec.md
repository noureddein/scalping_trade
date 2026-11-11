# Feature Specification: Phase 0 — Project Bootstrap

**Feature Branch**: `001-phase0-bootstrap`

**Created**: 2026-11-10

**Status**: Draft

**Input**: User description: "Create a specification for the Phase 0: Bootstrap"

**Master Plan Reference**: Phase 0 (line 1037), §1.1 Project Independence (line 65)

## User Scenarios & Testing

### User Story 1 - Standalone Project Exists (Priority: P1)

The project owner verifies that a standalone project directory, Git
repository, and Python package exist independently of any other trading
system on the machine.

**Why this priority**: Without an independent project structure, no
subsequent phase can begin. This is the foundational prerequisite.

**Independent Test**: Verify that the project directory contains a valid
Git repository, `pyproject.toml` identifies the package, and no path or
configuration references the owner's existing trading system.

**Acceptance Scenarios**:

1. **Given** a fresh clone or checkout of the repository, **When** the
   owner inspects the directory, **Then** a `.git` directory exists and
   `git status` runs without error.
2. **Given** the project root, **When** `pyproject.toml` is read,
   **Then** it declares the scalping system package name, Python 3.12
   requirement, and project metadata.
3. **Given** the project tree, **When** searched for imports, paths, or
   config referencing the existing trading system, **Then** zero
   references are found.

---

### User Story 2 - Core Documentation Present (Priority: P1)

The project owner confirms that the master plan and strategy design
documents exist and are consistent with the approved project scope.

**Why this priority**: Documentation is the source of truth for all
subsequent phases. Missing or inconsistent docs block every downstream
specification.

**Independent Test**: Verify that `FOREX_SCALPING_MASTER_PLAN.md` and
`TRADING_STRATEGY_DESIGN.md` exist, are non-empty, and the strategy
design document explicitly defers to the master plan for status and
safety gates.

**Acceptance Scenarios**:

1. **Given** the project root, **When** the owner lists files, **Then**
   `FOREX_SCALPING_MASTER_PLAN.md` and `TRADING_STRATEGY_DESIGN.md` are
   present and non-empty.
2. **Given** both documents, **When** compared on shared topics (phase
   status, safety gates, architecture), **Then** no contradictions exist;
   the strategy doc defers to the master plan on status authority.

---

### User Story 3 - Environment and Topology Recorded (Priority: P2)

The project owner verifies that the approved development topology
(Python 3.12 in WSL + native MT5 on Windows, TCP loopback at
127.0.0.1) and the approved architecture (Architecture C) are recorded
in the master plan.

**Why this priority**: Phase 2+ implementations depend on these
topology decisions being documented and unambiguous.

**Independent Test**: Search the master plan for the topology
declaration and confirm it matches the constitution's Principle I.

**Acceptance Scenarios**:

1. **Given** the master plan, **When** searched for the development
   topology statement, **Then** it specifies Python 3.12 in WSL, native
   MT5 on Windows, TCP at `127.0.0.1`, and Architecture C as the
   approved implementation target.
2. **Given** the master plan, **When** the Phase 0 exit evidence is
   read, **Then** it states the project path is independent and no
   external production system or database is reused.

---

### User Story 4 - Repository Hygiene State Acknowledged (Priority: P3)

The project owner acknowledges that files are currently untracked with
no initial commit, and that this state is retained until the owner
directs otherwise.

**Why this priority**: Prevents accidental commits or staging that
could violate the owner's explicit instruction to retain the current
uncommitted state.

**Independent Test**: Run `git status` and confirm all project files
are untracked; confirm no commits exist in the log.

**Acceptance Scenarios**:

1. **Given** the repository, **When** `git log` is run, **Then** no
   commits are returned (or only the expected initial state).
2. **Given** the repository, **When** `git status` is run, **Then**
   project files appear as untracked, matching the documented state.

---

### Edge Cases

- What happens if `pyproject.toml` is missing or malformed? Phase 0
  cannot be considered complete; the package identity is a hard
  prerequisite.
- What happens if the master plan and strategy design contradict each
  other? Report the conflict to the owner per the constitution's Sources
  of Truth rule; do not silently resolve.
- What happens if the repository already has commits? Verify whether
  the owner authorized them; if not, flag as an unexpected state change.

## Requirements

### Functional Requirements

- **FR-001**: The project MUST exist as a standalone directory with its
  own Git repository, independent of any other trading system.
- **FR-002**: `pyproject.toml` MUST declare the project identity,
  Python 3.12 requirement, and package metadata.
- **FR-003**: `FOREX_SCALPING_MASTER_PLAN.md` MUST exist and serve as
  the canonical project plan and phase/status authority.
- **FR-004**: `TRADING_STRATEGY_DESIGN.md` MUST exist and remain
  consistent with the master plan.
- **FR-005**: The approved development topology (WSL Python 3.12 +
  native Windows MT5, TCP loopback 127.0.0.1, Architecture C) MUST be
  recorded in the master plan.
- **FR-006**: No project file, import, configuration, or database
  connection may reference or depend on the owner's existing trading
  system.
- **FR-007**: The repository's uncommitted/untracked state MUST be
  retained unless the owner explicitly directs otherwise.

### Key Entities

- **Project Root**: The standalone directory containing all project
  files, independent of external systems.
- **Master Plan**: `FOREX_SCALPING_MASTER_PLAN.md` — canonical plan,
  phase ledger, and status authority.
- **Strategy Design**: `TRADING_STRATEGY_DESIGN.md` — detailed strategy
  hypotheses, consistent with and subordinate to the master plan.
- **Package Manifest**: `pyproject.toml` — Python package identity and
  dependency declarations.

## Success Criteria

### Measurable Outcomes

- **SC-001**: The project directory contains a valid Git repository and
  a `pyproject.toml` that identifies the package and requires
  Python 3.12.
- **SC-002**: Both source-of-truth documents exist, are non-empty, and
  contain no mutual contradictions on shared topics.
- **SC-003**: A recursive search of the project tree finds zero
  references to the owner's existing trading system paths, databases,
  Docker configurations, or MT5 bridge.
- **SC-004**: The master plan records the approved WSL + Windows MT5
  topology and Architecture C decision.
- **SC-005**: All project files are untracked with no commits unless
  the owner has directed otherwise.

## Assumptions

- The owner's existing trading system is on the same machine but in a
  separate directory; independence is verified by absence of cross-
  references, not physical isolation.
- "Python 3.12" means the minimum supported version declared in
  `pyproject.toml`; the actual runtime may be 3.12.x.
- The repository hygiene state (untracked, no commits) is intentional
  and owner-directed; it is not a defect to be fixed.
- MT5 availability on Windows was observationally confirmed but is not
  a testable artifact of this phase; MT5 integration testing belongs to
  Phase 2.
