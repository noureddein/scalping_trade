# Data Model: Phase 1 — Architecture and Design

**Date**: 2026-11-10

Phase 1 validates the design — it does not implement data entities. The
entities below are the design-phase artifacts being validated, not
runtime database tables.

## Design Artifacts Under Validation

### Approved Decisions Record (§14.1)

- **Identity**: Single table in the master plan
- **Fields**: Area, Approved decision/boundary
- **Constraint**: Each area has exactly one approved value; no TBD
- **Relationship**: Referenced by all implementation phases

### System Domain Sections (§§5–13)

- **Identity**: One section per domain
- **Fields**: Functional requirements, entities, constraints
- **Constraint**: Must be complete enough for implementation without
  guessing
- **Relationship**: Each maps to one or more implementation phases

### Unresolved Decisions Catalogue (§19)

- **Identity**: Numbered list (currently 18 items)
- **Fields**: Decision number, description, context/tradeoff
- **Constraint**: Must cover every unresolved parameter; cross-
  references must be valid
- **Relationship**: Each decision blocks specific behavior until
  owner-approved

### Definition of Success (§21)

- **Identity**: Criteria list
- **Fields**: Concrete, testable criterion text
- **Constraint**: Must include live-trading authorization rule
- **Relationship**: All phases work toward these criteria

## Runtime Data Model

The runtime data model is specified conceptually in §14.2 and will be
implemented in Phase 5. See [master plan §14.2](../../FOREX_SCALPING_MASTER_PLAN.md)
for the full entity list and integrity requirements.
