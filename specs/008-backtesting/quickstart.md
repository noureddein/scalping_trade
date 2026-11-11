# Quickstart Validation Guide: Phase 7 — Backtesting

**Date**: 2026-11-10

## Prerequisites

- Python 3.12 environment (WSL2)
- PostgreSQL instance (disposable test database)
- Phases 2–5 passing
- pytest installed
- Migration 008 (backtest tables) applied
- Synthetic tick dataset available for harness testing

**Note**: Real historical data requires §19#9 owner approval. All
harness validation uses synthetic data with known properties.

## Validation Scenarios

### 1. Gate Prerequisites (FR-001, FR-008, FR-012, SC-005)

**What to verify**: System refuses to run without required approvals.

| Scenario | Expected |
|----------|----------|
| No ApprovedDataSource | Refuses: "no approved data source" |
| No exit policy approved | Refuses: "no approved exit policy" |
| No AcceptanceCriteria (parameter selection) | Refuses: "no acceptance criteria" |
| All gates satisfied | Replay proceeds |

**Command**: `pytest tests/test_replay.py -k "test_gates" -v`

---

### 2. Deterministic Replay (FR-002, FR-003, SC-001)

**What to verify**: Same input produces identical output; ticks in
chronological order.

| Scenario | Expected |
|----------|----------|
| Two runs, same dataset + config | Bit-for-bit identical reports |
| Ticks with out-of-order timestamps in file | Rejected or sorted by loader |
| Dataset with 1000 ticks | All 1000 replayed in order |

**Command**: `pytest tests/test_replay.py -k "test_deterministic" -v`

---

### 3. Missing Interval Handling (FR-004)

**What to verify**: Gaps are flagged, not filled with fabricated
quotes.

| Scenario | Expected |
|----------|----------|
| 30-minute gap in tick data | Gap flagged in quality_flags |
| Gap longer than lookback window | "Insufficient history" — no signals until window fills |
| No gaps | No quality flags for gaps |

**Command**: `pytest tests/test_dataset.py -k "test_gaps" -v`

---

### 4. Cost Accounting (FR-005, SC-002)

**What to verify**: All cost components included, no double-counting,
unknowns reported as ranges.

| Scenario | Expected |
|----------|----------|
| Trade with known spread + commission | P/L matches manual calc |
| Trade held past rollover | Swap cost included |
| Trade closed same session | No swap |
| Unknown slippage component | Reported as sensitivity range |
| Verify no double-counted spread | Spread from Bid/Ask gap only |

**Command**: `pytest tests/test_cost_model.py -v`

---

### 5. Walk-Forward Evaluation (FR-006, FR-007, SC-003)

**What to verify**: Independent periods, no look-ahead, no state
leakage across periods.

| Scenario | Expected |
|----------|----------|
| 3-period walk-forward | Dev/val/test reports independent |
| Check tick visibility per period | No ticks from future periods |
| State at period boundary | Fresh — no carried indicators |
| Leakage check injection | Detects injected future tick |

**Command**: `pytest tests/test_walk_forward.py -v && pytest tests/test_leakage.py -v`

---

### 6. Hash Integrity (FR-009, SC-004)

**What to verify**: All three hashes frozen per run, dataset
modification detected.

| Scenario | Expected |
|----------|----------|
| Run produces report | dataset_hash, code_hash, config_hash present |
| Modify dataset, re-run | Different dataset_hash, ledger flags non-comparable |
| Modify config, re-run | Different config_hash, new ledger entry |
| Same everything, re-run | Identical hashes |

**Command**: `pytest tests/test_dataset.py -k "test_hash" -v && pytest tests/test_report.py -k "test_hash" -v`

---

### 7. Tried-Configuration Ledger (FR-010)

**What to verify**: Every run recorded, append-only, no deletions.

| Scenario | Expected |
|----------|----------|
| Run a backtest | Ledger entry created |
| Run same config again | Second entry (not deduplicated) |
| Attempt to delete entry | Application rejects DELETE |
| Query ledger | All runs visible with hashes and results |

**Command**: `pytest tests/test_ledger.py -v`

---

### 8. Report Completeness (FR-011, FR-014, FR-015)

**What to verify**: Reports include all required analyses with
correct labels.

| Scenario | Expected |
|----------|----------|
| Completed backtest | Report includes: no-trade benchmark, sensitivity, uncertainty, drawdown, trade count |
| Slippage grid | Labeled "scenario analysis" |
| Break-even friction | Labeled "diagnostic" |
| No-trade benchmark | Shows P/L of doing nothing |

**Command**: `pytest tests/test_report.py -v`

---

## Test Matrix

| Scenario | Unit (synthetic) | Integration (DB) | Owner Verification |
|----------|-----------------|------------------|-------------------|
| Gate prerequisites | Yes | Yes (table check) | — |
| Deterministic replay | Yes | — | Owner runs twice |
| Missing intervals | Yes | — | — |
| Cost accounting | Yes | — | Owner verifies formulas |
| Walk-forward | Yes | — | — |
| Hash integrity | Yes | Yes (persistence) | — |
| Tried-config ledger | — | Yes (append-only) | — |
| Report completeness | Yes | Yes (persistence) | Owner reviews report |

**Note**: All tests use synthetic tick data until §19#9 is resolved.
Synthetic tests validate the harness mechanics — they make no
performance claims about any strategy. Real-data evaluation requires
separate owner approval per the master plan Phase 7 checklist.
