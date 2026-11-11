# Tasks: Phase 9 — Deployment Readiness

**Input**: Design documents from `specs/010-deployment-readiness/`

**Prerequisites**: plan.md, spec.md, data-model.md, contracts/release-acceptance.md, research.md, quickstart.md

**Note**: Phase 9 is the final phase before production evaluation. It validates operational readiness:
recovery, security, backup, performance, documentation, and evidence assembly. Minimal new application
code — primarily procedures, tests, and evidence collection. No new database tables. Live trading
authorization is explicitly out of scope.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US6)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: Deploy subpackage structure and ops directory

- [ ] T001 Create the deploy subpackage directory at src/scalping_core/deploy/ with __init__.py
- [ ] T002 Create the ops/ directory at project root for operator-facing documentation (runbook.md, backup-restore.sh, recovery-checklist.md, monitoring-setup.md)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Health check infrastructure that all stories depend on for verification

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T003 Implement health check probes in src/scalping_core/deploy/health.py: check four components per data-model.md — backend (process alive), database (connection responsive), mt5_connection (last heartbeat), dashboard (HTTP reachable). Return HealthCheckResult: timestamp, overall_status (HEALTHY if all UP, DEGRADED if at least one DOWN but backend UP, UNHEALTHY if backend or database DOWN), components list (name, status UP/DOWN/UNKNOWN, detail string, latency_ms nullable). Health check endpoint at localhost only (FR-003, FR-012)
- [ ] T004 Write unit tests in tests/test_health_checks.py: test HEALTHY when all components UP, test DEGRADED when dashboard DOWN but backend UP, test UNHEALTHY when database DOWN, test latency_ms recorded for each component, test health endpoint binds to localhost only

**Checkpoint**: Health check infrastructure ready — stories can verify system state

---

## Phase 3: User Story 1 — Service Recovery (Priority: P1) 🎯 MVP

**Goal**: System recovers to safe reconciled state after process restart, DB outage, or WSL reboot

**Independent Test**: Kill backend with open position → restart → verify reconciliation barrier activates, position detected, new trading blocked

- [ ] T005 [US1] Document recovery test scenarios in ops/recovery-checklist.md: define three manual test scenarios — (1) process kill with open position: kill -9, restart, verify reconciliation barrier activates, open position detected from broker, new entries blocked until reconciliation completes (FR-001, SC-001). (2) Database outage: drop DB connection, verify fail-closed state (no new orders, no state loss), restore DB, verify normal operation resumes (FR-002). (3) WSL host reboot: reboot WSL, verify backend starts, runs startup reconciliation, reaches known-safe state before accepting signals. Each scenario includes: trigger command, expected behavior, evidence to capture
- [ ] T006 [US1] Implement schema version check on startup in src/scalping_core/deploy/health.py: on backend startup, compare database schema version against expected migration version. If mismatch detected, refuse to operate and report "schema version mismatch — apply migrations before starting" (FR-011). Log the expected vs actual version
- [ ] T007 [US1] Write unit tests in tests/test_health_checks.py: test schema version mismatch detection and refusal to start (FR-011), test recovery checklist scenarios are automated where possible (process restart reconciliation, DB reconnect)

**Checkpoint**: Recovery procedures documented and startup safety checks implemented

---

## Phase 4: User Story 2 — Security Hardening (Priority: P1)

**Goal**: No secrets in source, localhost-only bindings, least-privilege DB access, log redaction

**Independent Test**: Scan source for secrets → zero findings; inspect bindings → localhost only; review logs → no credentials

- [ ] T008 [P] [US2] Implement source code secret scanner in src/scalping_core/deploy/secrets_audit.py: scan all tracked files for patterns matching secrets — passwords, API keys, connection strings, tokens (regex patterns for common secret formats). Return SecretScanResult: scan_time, files_scanned, findings list (file_path, line_number, pattern_matched, severity), clean boolean (True if zero findings). Scanner runs on tracked files only (git ls-files). Do not flag .env.example templates with placeholder values (SC-002)
- [ ] T009 [P] [US2] Implement binding audit in src/scalping_core/deploy/secrets_audit.py: verify all network listeners bind exclusively to 127.0.0.1 — TCP connector (Phase 2), dashboard HTTP (Phase 6), health check endpoint. Report any binding to 0.0.0.0 or external interfaces as a finding (FR-003, SC-003)
- [ ] T010 [US2] Implement log redaction verification in src/scalping_core/deploy/secrets_audit.py: scan recent log output for sensitive data patterns — account credentials, full account numbers (more than last 4 digits), connection strings. Partial identifiers (last 4 digits) are permitted for correlation (FR-005). Report any unredacted sensitive data as a finding
- [ ] T011 [US2] Write unit tests in tests/test_secrets_audit.py: test secret scanner detects hardcoded password in tracked file, test scanner ignores .env.example placeholders, test binding audit flags 0.0.0.0 binding, test binding audit passes localhost-only, test log redaction catches full account number, test log redaction permits last-4-digit partial

**Checkpoint**: Security posture verified — no secrets in source, localhost-only, logs redacted

---

## Phase 5: User Story 3 — Backup and Restore (Priority: P2)

**Goal**: Database backup/restore preserves all data; restored system passes reconciliation

**Independent Test**: Backup DB → drop → restore → verify all historical data present and system resumes

- [ ] T012 [US3] Create database backup/restore script at ops/backup-restore.sh: implement pg_dump/pg_restore for PostgreSQL. Backup includes all Phase 2–8 tables (risk events, order intents, positions, audit log, backtest runs, forward test events). Verify backup integrity after creation. Restore to fresh instance. Detect corrupted backup and fail with clear error (FR-006). Script includes usage instructions and error handling
- [ ] T013 [US3] Document backup/restore procedure in ops/runbook.md (backup section): step-by-step backup command, restore command, post-restore verification steps (record count comparison, startup reconciliation pass). Include handling for schema version mismatch after restore (run migrations if needed per FR-011). Document recovery from corrupted backup (SC-004)
- [ ] T014 [US3] Write unit tests in tests/test_evidence_package.py: test backup/restore cycle preserves all records (risk events, order intents, positions, audit log — SC-004), test restored system passes startup reconciliation (FR-006), test schema version mismatch detected after restore to wrong version

**Checkpoint**: Backup/restore verified with 100% data integrity

---

## Phase 6: User Story 4 — Performance Qualification (Priority: P2)

**Goal**: Measure tick-to-signal and signal-to-submission latency under sustained load; compare against owner-approved thresholds

**Independent Test**: Run sustained load test → measure latencies → compare against thresholds → pass/fail

- [ ] T015 [US4] Implement performance measurement harness in src/scalping_core/deploy/health.py: measure tick_to_signal_ms (per-tick latency from receipt to signal output), signal_to_submission_ms (signal to order submission), end_to_end_ms (full pipeline), ticks_per_second (sustained throughput). Record PerformanceBaseline: measured_at, latency sample lists, memory_start_mb and memory_end_mb (RSS for soak test leak detection), soak_duration_seconds, thresholds dict (owner-approved). Refuse to pass qualification if thresholds not defined (FR-007, Constitution Principle VII). Output as JSON file for historical comparison
- [ ] T016 [US4] Document performance qualification procedure in ops/runbook.md (performance section): how to run the measurement harness, how to define owner-approved thresholds, how to interpret results. Include soak test instructions for detecting memory leaks and connection exhaustion. Document what to do when latencies exceed thresholds (root cause analysis, not threshold adjustment)
- [ ] T017 [US4] Write unit tests in tests/test_health_checks.py: test performance harness refuses to pass without owner-defined thresholds (FR-007), test latency measurement records all required fields, test soak test detects memory growth, test pass=true when all metrics within thresholds, test pass=false with documented deviation

**Checkpoint**: Performance measured and qualified against owner-approved thresholds

---

## Phase 7: User Story 5 — Deployment Documentation (Priority: P2)

**Goal**: Complete runbook enabling deployment without developer assistance

**Independent Test**: Follow runbook on approved topology → system reaches healthy state without developer help

- [ ] T018 [US5] Write deployment runbook at ops/runbook.md: complete operational documentation covering — (1) installation: Python 3.12, PostgreSQL, MT5 terminal, WSL2 prerequisites. (2) Configuration: environment variables for secrets (DB connection, broker config — not in source per FR-004), .env.example template with placeholder values. (3) Startup/shutdown: start backend, verify health check, start dashboard, connect MT5 EA. (4) Monitoring: health check endpoints, what DEGRADED/UNHEALTHY means, alerting options (FR-012). (5) Incident response: common failure modes with actionable diagnosis and recovery steps. (6) Rollback: database migration rollback procedure, application rollback to previous version (FR-013). (7) Clock sync: WSL clock drift impact on tick timestamps, verification command (SC-006)
- [ ] T019 [US5] Write monitoring setup guide at ops/monitoring-setup.md: lightweight self-hosted monitoring for single operator — health check polling, log aggregation, alerting on UNHEALTHY status. No external SaaS dependency. Cover four components: backend process, database connectivity, MT5 connection, dashboard availability (FR-012)

**Checkpoint**: Runbook and monitoring guide complete — deployment possible without developer

---

## Phase 8: User Story 6 — Release Acceptance (Priority: P3)

**Goal**: Assemble verifiable evidence package mapping all §17 criteria; owner makes go/no-go decision

**Independent Test**: Assemble evidence package → verify every §17 criterion has evidence → owner reviews and records decision

- [ ] T020 [US6] Implement evidence package assembly in src/scalping_core/deploy/evidence.py: map every §17 acceptance criterion to an evidence slot per contracts/release-acceptance.md — Phase 0–9 evidence (test output, logs, screenshots, measurements, owner sign-offs) and cross-cutting evidence (security, recovery, backup, performance, documentation). Return EvidencePackage: assembled_at, criteria list (section, criterion, evidence_type, evidence_path nullable, status PRESENT/MISSING/OWNER_VERIFIED), overall_status (COMPLETE if no MISSING, else INCOMPLETE), missing_count. Tool validates completeness — it does NOT generate or fabricate evidence (FR-009). Evidence paths point to actual files
- [ ] T021 [US6] Implement release decision recording in src/scalping_core/deploy/evidence.py: record owner's go/no-go decision per contracts/release-acceptance.md — Decision (APPROVED/REJECTED), Date, Rationale (reference specific evidence or gaps), Conditions (e.g., "approved for Demo monitoring only"), Live trading note (MUST state "Live trading requires separate authorization" per FR-010). If REJECTED, document which criteria failed and remediation needed
- [ ] T022 [US6] Write unit tests in tests/test_evidence_package.py: test evidence package reports INCOMPLETE when criteria have no evidence, test COMPLETE when all criteria have evidence (SC-007), test evidence paths point to existing files, test tool does not fabricate evidence for MISSING criteria, test release decision includes mandatory live trading disclaimer (FR-010), test REJECTED decision documents failed criteria

**Checkpoint**: Evidence package assembled; owner can make informed release decision

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: End-to-end validation and final verification

- [ ] T023 Run secret scan across entire repository and record PASS/FAIL evidence in evidence package (SC-002)
- [ ] T024 Run binding audit and record localhost-only verification evidence (SC-003)
- [ ] T025 Run quickstart.md validation scenarios end-to-end and record PASS/FAIL evidence. Note: recovery scenarios (T005), security audit (T008–T010), backup/restore (T012), and performance qualification (T015) require owner execution on the approved topology

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — T001/T002 can start immediately
- **Foundational (Phase 2)**: Depends on Setup — T003/T004 need package structure
- **US1 (Phase 3)**: Depends on Foundational (health checks needed for recovery verification)
- **US2 (Phase 4)**: Depends on Setup only (secret scanner is independent)
- **US3 (Phase 5)**: Depends on Foundational (backup/restore needs health check for verification)
- **US4 (Phase 6)**: Depends on Foundational (performance harness extends health.py)
- **US5 (Phase 7)**: Can start after Setup (documentation is independent of code)
- **US6 (Phase 8)**: Depends on US1–US5 (evidence package aggregates all prior results)
- **Polish (Phase 9)**: Depends on all user stories

### User Story Dependencies

- **US1 (P1)**: Depends on Foundational only
- **US2 (P1)**: Depends on Setup only (independent secret/binding audit)
- **US3 (P2)**: Depends on Foundational (needs health check for post-restore verification)
- **US4 (P2)**: Depends on Foundational (extends health.py)
- **US5 (P2)**: No code dependencies — documentation can start early
- **US6 (P3)**: Depends on all others (evidence package aggregates everything)

### Parallel Opportunities

- US1, US2, US5 can all run in parallel after Foundational (different files/directories)
- US3 and US4 can run in parallel (backup script vs performance harness — different files)
- T008 and T009 can run in parallel (both in secrets_audit.py but different functions)
- Documentation tasks (T005, T012, T013, T016, T018, T019) can start early

---

## Parallel Example: Recovery + Security + Documentation

```bash
# After Foundational, start in parallel:
# US1: T005-T007 (recovery — ops/recovery-checklist.md + health.py)
# US2: T008-T011 (security — secrets_audit.py, different file)
# US5: T018-T019 (documentation — ops/runbook.md, independent)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete T001–T002 (Setup: package + ops directory)
2. Complete T003–T004 (Foundational: health checks)
3. Complete T005–T007 (US1: recovery procedures and startup checks)
4. **STOP and VALIDATE**: System recovers safely from process restart, DB outage, WSL reboot
5. Proceed to US2–US6

### Incremental Delivery

1. Setup + Foundational → health check infrastructure ready
2. US1 + US2 + US5 (parallel: T005–T011, T018–T019) → recovery, security, documentation
3. US3 + US4 (parallel: T012–T017) → backup/restore, performance qualification
4. US6 (T020–T022) → evidence package assembly and release decision
5. Polish (T023–T025) → final scans and end-to-end validation

---

## Notes

- No new database tables — all Phase 9 entities are transient (in-memory or file-based)
- Performance thresholds are owner-defined — system refuses to pass without them (FR-007, Principle VII)
- Evidence package validates completeness; it does NOT generate or fabricate evidence
- Release acceptance does NOT authorize live trading — separate explicit authorization required (FR-010)
- All prior phases (0–8) must have passed acceptance criteria before Phase 9 begins (Principle V)
- Deployment topology is WSL + native Windows MT5 unless owner approves alternative
- Monitoring is lightweight self-hosted — no external SaaS dependency
- Secrets provided via environment variables, not source-controlled files (FR-004)
