# Data Model: Phase 9 — Deployment Readiness

**Date**: 2026-11-10

Phase 9 introduces no new database tables. The existing Phase 2–8
schema is unchanged. The entities below are logical structures used
by the deployment readiness tooling — they exist as in-memory or
file-based artifacts, not as persisted database entities.

## Logical Entities

### HealthCheckResult

Output of the health check probe. Not persisted — produced on demand.

| Field | Type | Description |
|-------|------|-------------|
| timestamp | datetime | When the check ran |
| overall_status | enum | HEALTHY, DEGRADED, UNHEALTHY |
| components | list | Per-component results (see below) |

**Component entry**:

| Field | Type | Description |
|-------|------|-------------|
| name | string | "backend", "database", "mt5_connection", "dashboard" |
| status | enum | UP, DOWN, UNKNOWN |
| detail | string | Diagnostic message (e.g., "last heartbeat 3s ago") |
| latency_ms | integer | Response time for the check; nullable |

**Status rules**:
- HEALTHY: all components UP
- DEGRADED: at least one component DOWN, backend still UP
- UNHEALTHY: backend DOWN or database DOWN

### SecretScanResult

Output of the source code secret scanner.

| Field | Type | Description |
|-------|------|-------------|
| scan_time | datetime | When the scan ran |
| files_scanned | integer | Total tracked files checked |
| findings | list | Each finding: file path, line number, pattern matched, severity |
| clean | boolean | True if no findings |

### PerformanceBaseline

Recorded latency and throughput measurements from qualification.

| Field | Type | Description |
|-------|------|-------------|
| measured_at | datetime | When the test ran |
| tick_to_signal_ms | list[decimal] | Per-tick latency samples |
| signal_to_submission_ms | list[decimal] | Per-signal latency samples |
| end_to_end_ms | list[decimal] | Full pipeline samples |
| ticks_per_second | decimal | Sustained throughput |
| memory_start_mb | decimal | RSS at soak test start |
| memory_end_mb | decimal | RSS at soak test end |
| soak_duration_seconds | integer | How long the soak test ran |
| thresholds | dict | Owner-approved thresholds for each metric |
| pass | boolean | All metrics within thresholds |

### EvidencePackage

Structured mapping of §17 acceptance criteria to evidence.

| Field | Type | Description |
|-------|------|-------------|
| assembled_at | datetime | When the package was assembled |
| criteria | list | Each criterion entry (see below) |
| overall_status | enum | COMPLETE, INCOMPLETE |
| missing_count | integer | Criteria without evidence |

**Criterion entry**:

| Field | Type | Description |
|-------|------|-------------|
| section | string | Master plan section reference (e.g., "§17 Market Data") |
| criterion | string | What must be demonstrated |
| evidence_type | string | "test_output", "log", "screenshot", "measurement", "owner_sign_off" |
| evidence_path | string | File path to the evidence artifact; nullable if missing |
| status | enum | PRESENT, MISSING, OWNER_VERIFIED |

## Notes

- No new database migration is needed for Phase 9. All entities are
  transient artifacts produced by deployment readiness tooling.
- The PerformanceBaseline may optionally be saved to a JSON file for
  historical comparison, but it is not a database entity.
- The EvidencePackage is assembled from files across the repository —
  it references existing test output, logs, and measurements rather
  than duplicating them.
