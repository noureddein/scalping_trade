# Research: Phase 1 — Architecture and Design

**Date**: 2026-11-10

No NEEDS CLARIFICATION items were identified in the technical context.
Phase 1 is a design validation phase with no technology unknowns to
resolve — the technology stack is already approved in §14.1.

## Findings

### Architecture Decision Consolidation

- **Decision**: §14.1 is the single authoritative record of approved
  decisions; it supersedes earlier research notes in §§3–4.
- **Rationale**: The master plan explicitly states "These decisions are
  consolidated here as the single current record; they supersede older
  architecture notes."
- **Alternatives considered**: Maintaining decisions across multiple
  sections was rejected — it creates contradiction risk.

### Unresolved Decisions Tracking

- **Decision**: §19 is the canonical list of 18 unresolved policy and
  parameter decisions.
- **Rationale**: Constitution Principle VII requires all unresolved
  parameters to be catalogued, not invented. §19 serves this purpose
  and is cross-referenced from multiple sections.
- **Alternatives considered**: None — the structure is already in place.

### Source-of-Truth Relationship

- **Decision**: `TRADING_STRATEGY_DESIGN.md` expands §7 and defers to
  the master plan on phase status, safety gates, and unresolved
  decisions.
- **Rationale**: The strategy design header explicitly states: "The
  master plan remains canonical for phase status, safety gates, and
  unresolved owner decisions."
- **Alternatives considered**: A single merged document was rejected —
  the strategy design is detailed enough to warrant a companion document.

### Domain Completeness Standard

- **Decision**: Each domain section (§§5–13) must state what the system
  does, which entities are involved, and what safety/correctness
  constraints apply — enough that an implementer does not need to invent
  requirements.
- **Rationale**: Derived from FR-002 of the spec. Gaps in domain
  sections force implementers to make unauthorized design decisions,
  violating Principle VII.
- **Alternatives considered**: None — this is the minimum completeness
  bar for a design phase.
