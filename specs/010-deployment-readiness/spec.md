# Feature Specification: Deployment Readiness

**Feature Branch**: `010-deployment-readiness`

**Created**: 2026-11-10

**Status**: Draft

**Input**: Phase 9 of the Forex Scalping Master Plan (§§15–17).
Final phase before production evaluation. Covers security review,
recovery testing, performance qualification, deployment documentation,
and release acceptance. Live trading requires separate explicit owner
approval beyond this phase.

## User Scenarios & Testing

### User Story 1 — Service Recovery (Priority: P1)

The owner restarts the backend process, simulates a database outage,
and reboots the WSL host. After each disruption, the system recovers
to a safe state: the reconciliation barrier activates, open positions
are detected, and no orders are submitted until reconciliation completes.

**Why this priority**: A trading system that cannot survive restarts
or infrastructure failures is unsafe to operate, regardless of how
well other features work.

**Independent Test**: Simulate each failure scenario (process kill,
DB connection drop, WSL reboot) and verify the system reaches a safe,
reconciled state within the owner-defined recovery window.

**Acceptance Scenarios**:

1. **Given** the backend is running with an open position, **When**
   the backend process is killed and restarted, **Then** the
   reconciliation barrier activates, the open position is detected
   from the broker, and new trading is blocked until reconciliation
   completes.
2. **Given** the backend is running, **When** the database becomes
   unreachable, **Then** the system enters a fail-closed state
   (no new orders, no state loss) and recovers when the database
   returns.
3. **Given** the system was running, **When** the WSL host reboots,
   **Then** the backend starts, runs startup reconciliation, and
   reaches a known-safe state before accepting any trading signals.

---

### User Story 2 — Security Hardening (Priority: P1)

The owner reviews the system's security posture: secrets are not
stored in source code, the backend binds only to localhost, database
credentials use least-privilege access, and logs redact sensitive
data (account numbers, credentials, connection strings).

**Why this priority**: A system handling broker accounts and financial
data must protect credentials and restrict network exposure before
any production use.

**Independent Test**: Audit source code for hardcoded secrets, verify
bind addresses, check database user privileges, and review log output
for sensitive data leakage.

**Acceptance Scenarios**:

1. **Given** the deployed system, **When** the source code is scanned,
   **Then** no secrets (passwords, API keys, connection strings) are
   found in tracked files.
2. **Given** the backend is running, **When** network listeners are
   inspected, **Then** only localhost (127.0.0.1) bindings are active
   for the TCP connector and dashboard.
3. **Given** the system is operating, **When** logs are reviewed after
   a trading session, **Then** no account credentials, full account
   numbers, or connection strings appear in log output.

---

### User Story 3 — Backup and Restore (Priority: P2)

The owner performs a database backup, destroys the database, restores
from the backup, and verifies that the system resumes operation with
all prior state (risk events, order history, audit log) intact.

**Why this priority**: Data durability is essential for a financial
system. The owner must be able to recover from data loss without
losing trading history or risk state.

**Independent Test**: Backup the database, drop and recreate it from
the backup, start the system, and verify all historical data is
accessible and the system resumes normal operation.

**Acceptance Scenarios**:

1. **Given** a database with trading history, **When** the database is
   backed up and restored to a fresh instance, **Then** all risk
   events, order intents, positions, and audit log entries are present
   and queryable.
2. **Given** a restored database, **When** the backend starts, **Then**
   it passes startup reconciliation and resumes normal operation
   without manual intervention beyond configuration.

---

### User Story 4 — Performance Qualification (Priority: P2)

The owner runs measured load and latency tests under realistic
conditions and verifies that the system meets owner-approved
performance thresholds for tick processing, signal generation,
and order submission latency.

**Why this priority**: A scalping system must process market data and
execute decisions within tight time constraints. Unmeasured performance
is an unacceptable risk.

**Independent Test**: Run a sustained load test at expected tick rates,
measure end-to-end latencies, and compare against owner-approved
thresholds.

**Acceptance Scenarios**:

1. **Given** the system is running, **When** ticks arrive at the
   expected rate for the approved pair, **Then** tick-to-signal
   latency and signal-to-submission latency are measured and recorded.
2. **Given** measured results, **When** compared against owner-approved
   thresholds, **Then** all latencies are within the approved bounds
   or deviations are documented with root cause.
3. **Given** a sustained soak test of owner-defined duration, **When**
   the system runs continuously, **Then** no memory leaks, connection
   exhaustion, or degradation is observed.

---

### User Story 5 — Deployment Documentation (Priority: P2)

The owner has a complete runbook covering: installation steps,
configuration reference, startup/shutdown procedures, monitoring
setup, incident response procedures, and rollback instructions.

**Why this priority**: Operational documentation ensures the owner can
deploy, operate, and troubleshoot the system without relying on
developer memory.

**Independent Test**: A person unfamiliar with the codebase can follow
the runbook to deploy the system to the approved topology and verify
it reaches a running state.

**Acceptance Scenarios**:

1. **Given** the runbook, **When** followed step by step on the
   approved topology, **Then** the system is deployed and reaches a
   healthy state.
2. **Given** the runbook, **When** a failure scenario occurs, **Then**
   the incident response section provides actionable steps to diagnose
   and recover.

---

### User Story 6 — Release Acceptance (Priority: P3)

The owner reviews the complete evidence package — all phase test
results, security audit findings, recovery test evidence, performance
measurements, and Demo forward test results — and makes a go/no-go
decision for production evaluation. This decision is recorded and
does not authorize live trading.

**Why this priority**: Release acceptance is the final gate before
production evaluation. It aggregates all prior evidence into a single
decision point.

**Independent Test**: Present the evidence package; the owner can
independently verify each claim by cross-referencing test output,
logs, and measurements.

**Acceptance Scenarios**:

1. **Given** all prior phases are accepted, **When** the evidence
   package is assembled, **Then** every acceptance criterion from
   §17 of the master plan has verifiable evidence attached.
2. **Given** the evidence package, **When** the owner reviews it,
   **Then** they can approve or reject production evaluation with a
   recorded decision and rationale.
3. **Given** production evaluation is approved, **When** the decision
   is recorded, **Then** it explicitly states that live trading
   requires a separate, additional authorization.

---

### Edge Cases

- What happens when a backup is restored to a database with a
  different schema version? System must detect the mismatch and
  refuse to start until migrations are applied.
- What happens when the dashboard is accessible but the backend is
  unreachable? Dashboard must show a clear disconnected state and
  disable all controls.
- What happens when performance thresholds are not defined by the
  owner? System must refuse to pass performance qualification —
  no default thresholds are invented.
- What happens when the WSL clock drifts relative to the Windows
  host? Document the impact on tick timestamps and reconciliation
  timing; include clock sync verification in the runbook.
- What happens when the database backup is corrupted? Restore must
  fail with a clear error; the system must not start with partial
  data.

## Requirements

### Functional Requirements

- **FR-001**: System MUST survive process restart without data loss
  or orphaned broker state. Reconciliation barrier MUST activate
  on every startup.
- **FR-002**: System MUST survive database outage by entering a
  fail-closed state (no new orders) and resume normal operation
  when the database recovers.
- **FR-003**: System MUST bind all network listeners exclusively to
  localhost (127.0.0.1).
- **FR-004**: System MUST NOT store secrets (passwords, API keys,
  connection strings) in source-controlled files. All secrets MUST
  be provided via environment variables or owner-managed
  configuration files excluded from version control.
- **FR-005**: System logs MUST redact account credentials, full
  account numbers, and connection strings. Partial identifiers
  (last 4 digits) are permitted for correlation.
- **FR-006**: Database backup and restore procedure MUST preserve
  all risk events, order intents, positions, audit log entries, and
  configuration. Restored system MUST pass startup reconciliation.
- **FR-007**: Performance qualification MUST use owner-approved
  thresholds. The system MUST refuse to pass qualification if
  thresholds are not defined (Constitution Principle VII).
- **FR-008**: A deployment runbook MUST document installation,
  configuration, startup/shutdown, monitoring, incident response,
  and rollback procedures for the approved topology.
- **FR-009**: Release acceptance MUST produce a verifiable evidence
  package covering all phase acceptance criteria from §17 of the
  master plan.
- **FR-010**: Release acceptance MUST NOT authorize live trading.
  A separate explicit owner authorization is required (Constitution
  Principle III).
- **FR-011**: The system MUST detect schema version mismatches on
  startup and refuse to operate until migrations are applied.
- **FR-012**: Monitoring MUST include health checks for: backend
  process, database connectivity, MT5 connection, and dashboard
  availability.
- **FR-013**: The runbook MUST include rollback procedures for
  database migrations and application deployments.

### Key Entities

- **EvidencePackage**: Aggregation of all phase test results,
  security findings, recovery evidence, and performance measurements
  required for release acceptance.
- **PerformanceBaseline**: Recorded latency and throughput
  measurements with owner-approved thresholds.
- **DeploymentConfiguration**: The set of environment variables,
  secrets, and configuration files required for the approved
  topology.

## Success Criteria

### Measurable Outcomes

- **SC-001**: System recovers to a safe, reconciled state within the
  owner-approved recovery window after process restart, database
  outage, or host reboot.
- **SC-002**: Zero secrets found in source-controlled files after
  a full repository scan.
- **SC-003**: All network listeners bind exclusively to localhost —
  zero external-facing ports.
- **SC-004**: Database backup and restore completes with 100% data
  integrity — all records match pre-backup state.
- **SC-005**: All measured latencies are within owner-approved
  thresholds during sustained operation.
- **SC-006**: The runbook enables deployment to the approved topology
  without developer assistance.
- **SC-007**: The release evidence package covers 100% of the §17
  acceptance criteria with verifiable evidence attached to each item.

## Assumptions

- The approved deployment topology is the current WSL backend +
  native Windows MT5 setup unless the owner explicitly approves an
  alternative before deployment work begins (per master plan §17
  Phase 9 checklist).
- Performance thresholds are owner-defined — this spec does not
  invent latency targets (Constitution Principle VII).
- The database is PostgreSQL as approved in earlier phases.
- Backup procedures use standard database tooling appropriate for
  the chosen database system.
- Monitoring uses lightweight, self-hosted approaches consistent
  with the single-operator design — no external SaaS monitoring
  dependency is assumed.
- All prior phases (0–8) have passed their acceptance criteria
  before Phase 9 begins (Constitution Principle V).
- Live trading authorization is a separate decision beyond Phase 9
  scope (Constitution Principle III, master plan final rule).
