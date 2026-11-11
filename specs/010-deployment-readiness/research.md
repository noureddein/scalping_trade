# Research: Phase 9 — Deployment Readiness

**Date**: 2026-11-10

No NEEDS CLARIFICATION items in the technical context. Phase 9 is
primarily operational validation and documentation, not new feature
development. Research covers design patterns for the operational
infrastructure.

## Findings

### Python Project Metadata (pyproject.toml)

- **Decision**: Fix three metadata issues before Phase 9 implementation
  begins. (1) Correct all plan/task path references from
  `src/scalping/deploy/` to `src/scalping_core/deploy/` — the actual
  importable package is `scalping_core` under `src/`, not `scalping`.
  (2) Update `requires-python` from `">=3.10"` to `">=3.12"` to match
  the constitution's Python 3.12 target. (3) Update `description` from
  "Non-trading domain foundation" to reflect the project's current scope.
- **Rationale**: The package name `scalping_core` is established across
  26 source files and 245+ tests. The plan's `src/scalping/deploy/`
  references would create a second, disconnected package that can't
  import from `scalping_core` without path gymnastics. Constitution
  Principle I mandates Python 3.12; the `>=3.10` floor is permissive
  enough to pass on the current WSL 3.10.12 environment but doesn't
  enforce the constitutional target. The description hasn't been updated
  since Phase 0.
- **Alternatives considered**: (a) Renaming the existing package from
  `scalping_core` to `scalping` was rejected — it would require updating
  every import in 26 source files and 245+ tests for zero functional
  gain. (b) Keeping `requires-python = ">=3.10"` was considered since the
  current environment runs 3.10.12, but Constitution Principle I is
  explicit about 3.12. The environment needs upgrading to 3.12; the
  metadata should reflect the target, not the current drift.
- **Validation evidence**: `pip install -e .` must succeed; `python -c
  "import scalping_core"` must import; `pytest tests/` must pass;
  `pip show forex-scalping-core` must show the updated metadata fields.

### Recovery Testing Strategy

- **Decision**: Test three failure scenarios independently: process
  restart (SIGKILL + restart), database outage (stop PostgreSQL, wait,
  restart), and WSL host reboot (full restart sequence). Each scenario
  has a pass/fail checklist: reconciliation barrier activates, open
  positions detected, no orphaned state, no new orders until
  reconciliation completes.
- **Rationale**: The master plan §17 Phase 9 checklist explicitly
  requires testing "service restart, database outage, host/WSL reboot,
  backup restore, and alert delivery." Independent scenarios isolate
  failure modes and produce clear evidence.
- **Alternatives considered**: A single "chaos test" combining
  multiple failures was rejected — it obscures which failure mode
  caused which symptom, making the evidence less useful for
  acceptance.

### Secret Scanning Approach

- **Decision**: Implement a lightweight source code scanner that
  checks tracked files for common secret patterns (connection strings,
  API keys, password assignments, base64-encoded credentials). Run as
  a pre-commit check and as part of the release acceptance evidence.
  Use regex pattern matching — no external dependency.
- **Rationale**: FR-004 requires that no secrets are stored in
  source-controlled files. A scanner provides automated, repeatable
  evidence. Regex patterns cover the common cases (DATABASE_URL with
  embedded password, hardcoded strings assigned to variables named
  "password", "secret", "key", "token").
- **Alternatives considered**: External tools (trufflehog, gitleaks)
  were considered but rejected — they add dependencies and the
  project's secret surface is small (one database, one broker
  connection). A simple regex scanner is sufficient.

### Health Check Design

- **Decision**: Implement health check probes that verify: backend
  process alive, database connectivity (simple SELECT 1), MT5
  connection status (last heartbeat age), and dashboard HTTP
  responsiveness. Expose as a CLI command (`python -m scalping_core.deploy.health`)
  that returns structured JSON with component status and overall
  health.
- **Rationale**: FR-012 requires monitoring health checks for four
  components. A CLI command is the simplest approach for the
  single-operator topology — no additional HTTP server or monitoring
  agent needed. The operator can run it manually, from a cron job,
  or from the runbook's monitoring section.
- **Alternatives considered**: An HTTP health endpoint was considered
  but rejected — it would require an additional server binding beyond
  the dashboard, adding complexity for a single-operator system.

### Backup and Restore Procedure

- **Decision**: Use `pg_dump` (custom format) for backup and
  `pg_restore` for restore. The backup script verifies the dump file
  is non-empty and records a SHA-256 checksum. The restore procedure
  includes a schema version check (compare migration version in the
  restored database against the application's expected version).
- **Rationale**: `pg_dump`/`pg_restore` are the standard PostgreSQL
  tools, already available on the deployment topology. Custom format
  supports selective restore and compression. The checksum prevents
  silent corruption. The schema version check addresses the edge case
  of restoring a backup from a different application version.
- **Alternatives considered**: Logical SQL dumps (`pg_dump --format=plain`)
  were considered but rejected — custom format is more flexible and
  supports parallel restore for larger databases.

### Evidence Package Assembly

- **Decision**: The evidence package is a structured document (or
  directory) that maps each §17 acceptance criterion to its
  supporting evidence: test output files, log excerpts, screenshots,
  performance measurements, and owner sign-off records. The assembly
  tool collects file references and generates a summary with
  pass/fail/missing status for each criterion.
- **Rationale**: FR-009 requires a verifiable evidence package.
  A structured mapping ensures nothing is missed and the owner can
  cross-reference each claim. The tool does not generate evidence —
  it only assembles and validates completeness.
- **Alternatives considered**: A free-form report was rejected — it
  would be harder to verify completeness and easier to accidentally
  omit a criterion.

### Performance Qualification Approach

- **Decision**: Measure three latencies: tick-to-signal (time from
  tick arrival to strategy signal output), signal-to-submission (time
  from signal to broker adapter call), and end-to-end (tick arrival
  to broker response). Also measure sustained throughput (ticks per
  second processed without degradation) and memory stability (RSS
  growth over the soak test duration). All thresholds are
  owner-defined — the qualification tool refuses to produce a "pass"
  result without recorded thresholds.
- **Rationale**: FR-007 and Constitution Principle VII require
  owner-approved thresholds. The three latency measurements cover
  the critical path. Memory stability catches slow leaks that
  wouldn't show in a short test.
- **Alternatives considered**: Using external profiling tools was
  considered but rejected for the qualification measurement — simple
  timestamp instrumentation at pipeline boundaries is sufficient and
  avoids observer effects. External profiling remains available for
  debugging if needed.
