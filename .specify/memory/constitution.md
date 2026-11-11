<!--
## Sync Impact Report

- **Version change:** 0.0.0 (initial placeholder) → 1.0.0
- **Modified principles:** None (first ratification)
- **Added sections:**
  - Core Principles (9 principles)
  - Sources of Truth
  - Role and Workflow Constraints
  - Governance
- **Removed sections:** All template placeholder content replaced
- **Deferred TODOs:** None

Remove this comment block before committing.
-->

# Forex Scalping System Constitution

## Core Principles

### I. Platform Target

The project target is a Python 3.12 backend running in WSL with native
MetaTrader 5 on Windows. The two processes communicate exclusively over
TCP loopback at `127.0.0.1`. All implementation, integration tests, and
deployment assumptions MUST conform to this topology. Ubuntu/Wine is not
an assumed requirement.

### II. Fail-Closed Configuration

Strategies MUST remain inactive unless every required parameter and
owner decision has been explicitly approved. Missing, invalid, or
default-placeholder configuration MUST fail closed — no implicit
defaults may activate a strategy, enable an entry signal, or relax a
safety gate.

### III. Read-Only Broker Connector

The current MT5 connector is read-only. No agent, tool, or automated
process may submit, modify, or close broker orders; enable live trading
flags; or invoke the MT5 Strategy Tester unless the owner explicitly
authorizes that specific action in writing. This constraint applies to
Claude, Codex, hooks, and any CI/CD automation.

### IV. Role Separation

Claude implements code during owner-approved implementation phases.
Codex is the independent auditor: it reviews implementation, may run
explicitly requested non-trading tests when a safe environment is
available, but MUST NOT modify application source code during audits.
The owner performs GUI/terminal checks and any broker-connected
validation.

### V. Sequential Phase Discipline

Work proceeds one owner-approved phase or task at a time. Each Spec Kit
feature specification MUST cite the exact master-plan section numbers
and acceptance-test identifiers it implements. Do not begin a subsequent
phase while the current phase has open safety gates or unresolved
required tests.

### VI. Execution Safety Invariants

The following execution-safety mechanisms are non-negotiable and MUST be
preserved in every implementation change:

- Account-wide risk authority (daily loss/profit limits, exposure caps).
- Durable order intent (intent survives restarts; no silent discard).
- Pair reservations (one position per pair, reservation before entry).
- Reconciliation barriers (startup reconciliation before new trading).
- Exact order-correlation requirements (every fill traces to one intent).
- Fail-closed behavior on ambiguity or error.

No process may automatically resubmit an ambiguous broker request.

### VII. No Invented Parameters

Do not invent strategy thresholds, exit rules, spread limits, slippage
tolerances, dwell times, data-source selections, or acceptance criteria.
Record every unresolved decision and request owner approval before
proceeding. The `FOREX_SCALPING_MASTER_PLAN.md` §19 lists the current
set of deferred owner decisions.

### VIII. Honest Test Reporting

Report test results only when tests have actually been executed,
including failures and skips with their reasons. A successful compile, a
synthetic/mock-only test, or a skipped integration test is not proof of
end-to-end acceptance. Never record an unrun, skipped, or unreported
test as passed.

### IX. Plan-Aligned Evidence

Keep implementation aligned with the phase ledger and test backlog in
`FOREX_SCALPING_MASTER_PLAN.md`. Update status records only with
verifiable evidence (test output, logs, screenshots, or owner
confirmation). A code file's existence is not evidence of a passing
integration test or a deployed capability.

## Sources of Truth

- **`FOREX_SCALPING_MASTER_PLAN.md`** is the canonical project plan and
  phase/status authority.
- **`TRADING_STRATEGY_DESIGN.md`** is the detailed strategy design and
  MUST remain consistent with the master plan.
- If these documents conflict, do not silently choose or rewrite either
  one. Report the conflict to the owner for resolution.

## Role and Workflow Constraints

- MT5 MCP is permitted for development assistance only. It MUST NOT be
  part of the runtime trading execution path.
- Runtime decisions MUST be deterministic. No AI, LLM, or external API
  dependency is permitted at runtime.
- Architecture C (TCP loopback, one EA per pair, single-pair pilot,
  PostgreSQL for durable state, no Redis initially) is the approved
  implementation target — not approved for live trading or unattended
  demo execution.
- No live-trading approval has been granted. No broker order submission
  is authorized.

## Governance

This constitution is the authoritative governance document for the Forex
Scalping System project. It supersedes ad-hoc guidance when there is a
conflict, except where `FOREX_SCALPING_MASTER_PLAN.md` or
`TRADING_STRATEGY_DESIGN.md` provide more specific technical detail on
the same topic.

**Amendment procedure:**

1. Propose the change with rationale and affected principle numbers.
2. Owner reviews and approves.
3. Update this file with the new version, date, and sync impact report.
4. Record the amendment in the project commit history.

**Versioning:** Semantic versioning (MAJOR.MINOR.PATCH). MAJOR for
principle removals or incompatible redefinitions; MINOR for new
principles or material expansions; PATCH for clarifications and wording.

**Compliance:** All specifications, implementations, and reviews MUST
verify alignment with these principles. Non-compliance MUST be flagged
before merging.

**Version**: 1.0.0 | **Ratified**: 2026-11-10 | **Last Amended**: 2026-11-10
