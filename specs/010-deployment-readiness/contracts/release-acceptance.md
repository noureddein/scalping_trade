# Release Acceptance Contract

**Date**: 2026-11-10

**Scope**: Defines the criteria, evidence requirements, and decision
process for release acceptance. This is the final gate before
production evaluation. It does not authorize live trading.

## Acceptance Criteria Map

Every item from §17 of the master plan must have verifiable evidence.
The evidence package assembles this mapping.

### Phase-Level Evidence

| Phase | Area | Required Evidence |
|-------|------|-------------------|
| 0 | Bootstrap | Project structure, package config, environment docs |
| 1 | Architecture | Design decisions documented, owner approvals recorded |
| 2 | Broker Connectivity | EA compile, TCP protocol tests, account/symbol discovery |
| 3 | Market Data & Spread | Tick validation, spread calculation, staleness detection, live-feed test |
| 4 | Strategy Engine | Deterministic signal tests, regime classification, safe-start defaults |
| 5 | Risk & Execution | Order lifecycle, pair reservation, reconciliation, daily limits, DB persistence |
| 6 | Dashboard | API endpoints, SSE stream, audit log, emergency stop, independence |
| 7 | Backtesting | Deterministic replay, cost model, leakage detection, walk-forward, acceptance criteria |
| 8 | Demo Forward Test | Demo scope gate, evidence recording, honest reporting, safety under real conditions |
| 9 | Deployment Readiness | Recovery, security, backup, performance, runbook, this evidence package |

### Cross-Cutting Evidence

| Area | Required Evidence |
|------|-------------------|
| Security | Secret scan clean, localhost-only bindings, log redaction verified |
| Recovery | Process restart, DB outage, WSL reboot — each with reconciliation evidence |
| Backup | Backup/restore cycle with data integrity verification |
| Performance | Measured latencies within owner-approved thresholds, soak test results |
| Documentation | Runbook reviewed and validated on approved topology |

## Decision Process

### Pre-Decision Requirements

Before the owner can make a release acceptance decision:

1. **Evidence package assembled**: Tool reports COMPLETE status — no
   MISSING criteria.
2. **Security audit clean**: Secret scan reports zero findings.
   Binding audit confirms localhost only. Log redaction verified.
3. **Recovery tests passed**: All three scenarios (process restart,
   DB outage, WSL reboot) passed with evidence.
4. **Performance qualified**: All metrics within owner-approved
   thresholds, or deviations documented with root cause.
5. **Runbook validated**: Deployment procedure tested on approved
   topology.

### Decision Recording

The owner records their decision as:

| Field | Description |
|-------|-------------|
| Decision | APPROVED or REJECTED |
| Date | When the decision was made |
| Rationale | Why (reference specific evidence or gaps) |
| Conditions | Any conditions on the approval (e.g., "approved for Demo monitoring only") |
| Live trading note | Must explicitly state: "Live trading requires separate authorization" |

### Post-Decision

- **If APPROVED**: System is cleared for production evaluation
  (monitoring, observation). Live trading remains unauthorized
  until a separate, explicit owner decision.
- **If REJECTED**: Owner documents which criteria failed and what
  remediation is needed. Re-run Phase 9 acceptance after fixes.

## Consumer/Producer Obligations

**Evidence assembly tool (producer) guarantees**:
- Every §17 criterion is mapped to an evidence slot
- Missing evidence is reported as MISSING, never fabricated
- Evidence paths point to actual files that can be independently verified
- The tool does not generate evidence — it only validates completeness

**Owner (consumer) guarantees**:
- Reviews each piece of evidence, not just the summary
- Records their decision with rationale
- Does not treat release acceptance as live trading authorization
- Verifies that evidence is current (not stale from a prior run)
