# Quickstart Validation: Phase 1 — Architecture and Design

**Date**: 2026-11-10

## Prerequisites

- Access to `FOREX_SCALPING_MASTER_PLAN.md` and
  `TRADING_STRATEGY_DESIGN.md`
- Access to `.specify/memory/constitution.md`

## Validation Steps

### 1. Verify approved decisions are complete (SC-001)

```bash
# §14.1 should have a row for each architecture area
grep -c "|" FOREX_SCALPING_MASTER_PLAN.md | head -1
# Manually review §14.1 table — each row must have a concrete value
```

**Expected**: Every row in the §14.1 table has an approved decision,
no "TBD" or research questions.

### 2. Verify domain completeness (SC-002)

Review each domain section:

| Section | Domain | Check |
|---------|--------|-------|
| §5 | Broker Abstraction | Requirements, adapter interface, pilot scope |
| §5.1 | Symbol Registry | Canonical symbols, discovery, mapping |
| §5.2 | Contract Specs | Fields to discover and store |
| §6 | Pair Management | Dynamic registry, per-pair config |
| §7 | Strategy Architecture | Framework, validation, design doc reference |
| §8 | Trade Entry/Execution | Entry flow, guards, gates |
| §9 | Position Management | Adaptive management, duration |
| §10 | P/L Management | TP, loss ceiling |
| §11 | Daily Risk | Net P/L, reset, state machine |
| §12 | Spread Intelligence | Metrics, protection, stability |
| §13 | Dashboard | Overview, pairs, spread, risk, positions |
| §14.2 | Database Design | Entities, constraints, safety, migrations |

**Expected**: Each section states requirements, entities, and
constraints. No gaps requiring implementer invention.

### 3. Verify unresolved decisions catalogue (SC-003)

```bash
# Count numbered items in §19
grep -cE "^[0-9]+\." FOREX_SCALPING_MASTER_PLAN.md
# Verify cross-references
grep -n "§19" FOREX_SCALPING_MASTER_PLAN.md | wc -l
```

**Expected**: 18 numbered decisions in §19; all §19 cross-references
point to valid entries.

### 4. Verify source-of-truth consistency (SC-004)

```bash
# Check strategy design defers to master plan
head -10 TRADING_STRATEGY_DESIGN.md
```

**Expected**: Strategy design header states the master plan is canonical
for phase status and safety gates. No contradictions on shared topics.

### 5. Verify definition of success (SC-005)

```bash
# Count criteria in §21
grep -cE "^- " FOREX_SCALPING_MASTER_PLAN.md | tail -1
# Check for live-trading rule
grep "live trading" FOREX_SCALPING_MASTER_PLAN.md | tail -3
```

**Expected**: At least 10 concrete criteria in §21; final rule requires
explicit owner authorization for live trading.

### 6. Verify constitution alignment (SC-006)

Cross-check each constitution principle against the master plan:

| Principle | Master Plan Section | Check |
|-----------|-------------------|-------|
| I. Platform Target | §14.1 row 1 | Topology matches |
| II. Fail-Closed | §19 (all params unresolved) | No invented defaults |
| III. Read-Only | §14.1 trading authority | Confirmed read-only |
| IV. Role Separation | §15, Phase status notes | Claude/Codex/owner split |
| V. Phase Discipline | Phase ledger | Sequential, with gates |
| VI. Safety Invariants | §14.2 | Order safety, reservations, barriers |
| VII. No Invented Params | §19 | All deferred, none invented |
| VIII. Honest Reporting | Phase status notes | Evidence requirements stated |
| IX. Plan-Aligned Evidence | Phase ledger | Verifiable evidence required |

**Expected**: All 9 principles consistent with master plan content.

## Success Summary

| Check | Criteria | Status |
|-------|----------|--------|
| Approved decisions complete | §14.1 has no TBD values | |
| Domain completeness | §§5–14 have requirements + entities + constraints | |
| Unresolved decisions | §19 has 18 items, valid cross-refs | |
| Source-of-truth consistency | No contradictions, strategy doc defers | |
| Definition of success | §21 has 10+ criteria + live-trading rule | |
| Constitution alignment | All 9 principles consistent | |

Fill the Status column with PASS/FAIL after each check.
