# Research: Phase 7 — Backtesting

**Date**: 2026-11-10

No NEEDS CLARIFICATION items in the technical context. Three §19
decisions are documented as blocking gates, not research items — they
require owner approval, not technical investigation. Research covers
design patterns for the replay and evaluation infrastructure.

## Findings

### Deterministic Replay Architecture

- **Decision**: Build a replay engine that wraps the existing Phase
  3–5 pipeline. The engine replaces the live TCP tick source with a
  sequential file reader. All other components (spread engine,
  strategy engine, risk gate) receive ticks through the same interface
  as live trading. No backtest-only strategy or risk logic exists.
- **Rationale**: FR-016 requires the replay harness to use the same
  pipeline as the live system. A separate backtest implementation
  would diverge from production behavior and produce misleading
  results.
- **Alternatives considered**: A lightweight in-memory simulator with
  simplified spread/risk was rejected — it would violate FR-016 and
  Constitution Principle VIII (honest test reporting).

### Walk-Forward Window Management

- **Decision**: Implement chronological walk-forward evaluation with
  non-overlapping development/validation/test periods. The window
  manager takes a dataset and a split specification (ratios or fixed
  dates), then yields period boundaries. Each period is replayed
  independently. Future data never leaks into past windows.
- **Rationale**: FR-007 requires no look-ahead. Walk-forward is the
  standard approach for time-series validation that prevents data
  leakage while testing strategy robustness over time.
- **Alternatives considered**: Simple train/test split was rejected —
  it tests only one boundary and is more vulnerable to regime-specific
  overfitting. K-fold cross-validation was rejected — it violates
  chronological ordering.

### Cost Model Design

- **Decision**: A pluggable cost model that computes per-trade costs
  from documented components: Bid/Ask spread (from the tick data
  itself), commission (configurable per broker/pair), swap (if held
  past rollover time), and estimated slippage (configurable scenarios).
  Unknown components are reported as sensitivity ranges. All
  components are summed once per trade — no double-counting.
- **Rationale**: FR-005 requires all cost components with no
  double-counting and sensitivity ranges for unknowns. A pluggable
  design allows the cost model to be updated as §19#18 is resolved.
- **Alternatives considered**: Hardcoded cost assumptions were
  rejected — they would violate Constitution Principle VII (no
  invented parameters).

### Dataset Integrity and Hashing

- **Decision**: Each dataset is hashed (SHA-256) on load. The hash
  covers the raw tick data file contents. Each backtest run records
  the dataset hash, a hash of the Python source code (relevant
  modules), and a hash of the configuration (all parameters as
  sorted JSON). These three hashes are frozen in the report and the
  tried-configuration ledger.
- **Rationale**: FR-009 requires frozen hashes per report. FR-010
  requires a tried-configuration ledger. Hashing prevents unreported
  dataset modifications and makes every run reproducible.
- **Alternatives considered**: Git commit hash alone was rejected —
  it doesn't detect uncommitted changes or dataset modifications
  outside the repo.

### Leakage Detection

- **Decision**: Implement explicit leakage checks that verify no
  future data is accessible to the strategy during replay. The check
  works by ensuring the replay engine only exposes ticks up to the
  current replay timestamp. A validation mode runs each walk-forward
  window with an intentional future-data injection and verifies the
  strategy's output changes — if it doesn't, the check flags a
  potential leak.
- **Rationale**: FR-007 and SC-003 require 100% verification of no
  future data in past windows. Automated leakage detection catches
  subtle bugs (e.g., a rolling window accidentally including one
  tick too many).
- **Alternatives considered**: Manual code review alone was rejected —
  it cannot catch runtime leakage from data-dependent edge cases.

### Tried-Configuration Ledger

- **Decision**: An append-only PostgreSQL table that records every
  parameter combination tested, with timestamp, dataset hash, code
  hash, configuration hash, and summary results. Entries are never
  deleted or modified. The ledger prevents "researcher degrees of
  freedom" — every experiment is recorded, preventing selective
  reporting of favorable runs.
- **Rationale**: FR-010 requires recording every tested combination.
  Constitution Principle IX requires verifiable evidence. An
  append-only ledger ensures no experimentation goes unreported.
- **Alternatives considered**: File-based ledger was rejected —
  files can be deleted or modified without audit trail. PostgreSQL
  provides immutability via application-level insert-only policy.
