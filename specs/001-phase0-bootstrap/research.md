# Research: Phase 0 — Project Bootstrap

**Date**: 2026-11-10

No NEEDS CLARIFICATION items were identified in the technical context.
Phase 0 is a verification phase with no technology choices to research.

## Findings

### Project Independence

- **Decision**: Verify independence by absence of cross-references to
  the existing trading system — not by physical isolation.
- **Rationale**: The master plan §1.1 defines independence as: separate
  directory, separate Git repo, independent PostgreSQL, independent
  environment variables, independent services, independent MT5
  connectivity. No shared database, Docker config, or MT5 bridge.
- **Alternatives considered**: None — §1.1 is prescriptive.

### Repository Hygiene State

- **Decision**: Retain untracked/uncommitted state until owner directs
  otherwise.
- **Rationale**: Master plan Phase 0 status explicitly states files are
  untracked with no initial commit, and this state is intentional.
- **Alternatives considered**: Auto-committing bootstrap artifacts was
  rejected — the owner's instruction is explicit.

### Package Identity

- **Decision**: `pyproject.toml` is the single source of package
  identity and Python version requirement.
- **Rationale**: Standard Python packaging; the master plan §3.1
  specifies Python 3.12.
- **Alternatives considered**: None — standard practice.
