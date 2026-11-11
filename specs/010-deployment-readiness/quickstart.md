# Quickstart Validation Guide: Phase 9 — Deployment Readiness

**Date**: 2026-11-10

## Prerequisites

- Python 3.12 environment (WSL2)
- PostgreSQL instance (disposable test database)
- All Phases 0–8 passing their acceptance criteria
- pytest installed
- MT5 terminal running with Demo account connected
- Owner-approved performance thresholds recorded

## Validation Scenarios

### 0. Python Project Metadata (pyproject.toml)

**What to verify**: Package metadata matches the constitution and the
actual source tree.

| Check | Command | Expected |
|-------|---------|----------|
| requires-python | `grep requires-python pyproject.toml` | `>=3.12` |
| description | `grep description pyproject.toml` | Not "Non-trading domain foundation" |
| Package discoverable | `pip install -e . && python -c "import scalping_core"` | No error |
| Metadata fields | `pip show forex-scalping-core` | Updated description, requires-python |
| Tests still pass | `pytest tests/ -x -q` | All passing |
| No stale path refs | `grep -r "src/scalping/" specs/010-deployment-readiness/` | Zero hits for `src/scalping/` (only `src/scalping_core/`) |

---

### 1. Process Restart Recovery (FR-001, SC-001)

**What to verify**: System recovers safely after being killed.

| Scenario | Expected |
|----------|----------|
| Kill backend with SIGKILL, restart | Reconciliation barrier activates |
| Open position exists at restart | Position detected from broker |
| No position at restart | Clean startup, ready for trading signals |
| Restart during active order (SUBMITTING) | Intent preserved, reconciliation detects ambiguity |

**Command**: Manual — owner kills and restarts process, observes
logs. `pytest tests/test_health_checks.py -k "test_recovery" -v`
for automated pre/post checks.

---

### 2. Database Outage Recovery (FR-002, SC-001)

**What to verify**: System enters fail-closed on DB loss, recovers.

| Scenario | Expected |
|----------|----------|
| Stop PostgreSQL while backend running | Fail-closed: no new orders, error logged |
| Restart PostgreSQL | System resumes normal operation |
| DB outage during order submission | Order blocked, no partial state |

**Command**: Manual — owner stops/starts PostgreSQL, observes
system behavior. `pytest tests/test_health_checks.py -k "test_db_outage" -v`

---

### 3. Security Audit (FR-003–FR-005, SC-002, SC-003)

**What to verify**: No secrets in code, localhost-only, logs redacted.

| Scenario | Expected |
|----------|----------|
| Run secret scanner on repo | Zero findings |
| Inspect network listeners | Only 127.0.0.1 bindings |
| Review logs after trading session | No credentials or full account numbers |

**Command**: `python -m scalping_core.deploy.secrets_audit` for secret
scan. `ss -tlnp` or `netstat -tlnp` for binding audit. Manual log
review by owner.

---

### 4. Backup and Restore (FR-006, SC-004)

**What to verify**: Full data integrity after backup/restore cycle.

| Scenario | Expected |
|----------|----------|
| Backup database with trading history | Dump file created, checksum recorded |
| Restore to fresh database | All records present, checksums match |
| Start system on restored database | Startup reconciliation passes |
| Restore backup with wrong schema version | System refuses to start, migration required |
| Restore corrupted backup | Restore fails with clear error |

**Command**: `bash ops/backup-restore.sh backup` and
`bash ops/backup-restore.sh restore`. Manual verification by owner.

---

### 5. Performance Qualification (FR-007, SC-005)

**What to verify**: Latencies within owner-approved thresholds.

| Scenario | Expected |
|----------|----------|
| Sustained tick processing at expected rate | Tick-to-signal latency measured |
| Signal generation under load | Signal-to-submission latency measured |
| Soak test for owner-defined duration | No memory leaks, no degradation |
| No thresholds defined | Qualification tool refuses to produce "pass" |

**Command**: Manual — owner runs performance test and records
results. `pytest tests/test_health_checks.py -k "test_performance" -v`
for measurement infrastructure tests.

---

### 6. Health Checks (FR-012)

**What to verify**: All four components monitored.

| Scenario | Expected |
|----------|----------|
| All components running | HEALTHY status |
| Database stopped | DEGRADED, database DOWN |
| MT5 disconnected | DEGRADED, mt5_connection DOWN |
| Backend stopped | UNHEALTHY (check itself fails) |

**Command**: `python -m scalping_core.deploy.health`

---

### 7. Evidence Package Assembly (FR-009, FR-010, SC-007)

**What to verify**: Complete evidence for all §17 criteria.

| Scenario | Expected |
|----------|----------|
| All phases accepted, evidence files present | COMPLETE status |
| Missing evidence for one criterion | INCOMPLETE, missing item listed |
| Evidence package reviewed | "Live trading requires separate authorization" present |

**Command**: `python -m scalping_core.deploy.evidence`

---

### 8. Deployment Runbook (FR-008, FR-013, SC-006)

**What to verify**: Runbook is complete and followable.

| Scenario | Expected |
|----------|----------|
| Follow runbook on approved topology | System reaches healthy state |
| Simulate failure, follow incident response | Actionable recovery steps |
| Rollback migration | Database returns to prior schema version |

**Command**: Manual — owner follows runbook step by step.

---

## Test Matrix

| Scenario | Unit (mocked) | Integration (DB) | Manual (Owner) |
|----------|--------------|------------------|----------------|
| Process restart | Yes | Yes (state check) | Owner kills/restarts |
| DB outage | Yes | Yes (stop/start DB) | Owner observes |
| Security audit | Yes (scanner) | — | Owner reviews |
| Backup/restore | — | Yes (full cycle) | Owner verifies |
| Performance | Yes (instrumentation) | Yes (under load) | Owner runs soak |
| Health checks | Yes | Yes | Owner verifies |
| Evidence package | Yes | — | Owner reviews |
| Runbook | — | — | Owner follows |

**Note**: Phase 9 is predominantly owner-driven. Automated tests
validate the tooling infrastructure (health checks, secret scanner,
evidence assembler). The core value is proving operational readiness
through real failure scenarios and owner verification. Constitution
Principle VIII requires that only actually-run tests are reported as
evidence.
