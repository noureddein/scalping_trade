# Implementation Plan: Phase 7 — Backtesting

**Branch**: `008-backtesting` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/008-backtesting/spec.md`

## Summary

Build a deterministic tick-replay harness that feeds historical
Bid/Ask data through the existing Phase 3–5 pipeline (spread,
strategy, risk) with full cost accounting. Includes walk-forward
evaluation, leakage detection, tried-configuration ledger, and
structured reporting. Three §19 decisions are blocking gates:
#9 (data source), #16 (sampling basis), #18 (exit/cost model).

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: stdlib, hashlib (dataset/config hashing)

**Storage**: PostgreSQL (backtest run metadata, tried-configuration
ledger, reports); file system (historical tick datasets)

**Testing**: pytest, synthetic tick data for harness tests; real
data only after §19#9 approval

**Target Platform**: WSL2 (batch CLI process)

**Project Type**: CLI batch tool (replay harness + report generator)

**Performance Goals**: No latency target — batch offline process.
Replay speed is bounded by I/O and pipeline computation.

**Constraints**: Deterministic (no randomness, no system clock, no
floating-point non-determinism). Same input = same output. All P/L
and cost arithmetic MUST use `Decimal`, not `float`. Phase 3–5
pipeline components that use `float` for spread/strategy calculations
are acceptable only if the replay engine feeds identical inputs —
determinism is guaranteed by identical input ordering and identical
Decimal cost accounting, not by replacing all floats in existing code.

**Scale/Scope**: Single pair pilot; dataset size depends on §19#9
approval. Walk-forward windows scale with dataset length.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| I | Platform Target | PASS | Python 3.12 in WSL, CLI batch tool |
| II | Fail-Closed Configuration | PASS | Refuses to run without approved data source, exit policy, or acceptance criteria |
| III | Read-Only Broker Connector | PASS | No broker contact; pure historical replay |
| IV | Role Separation | PASS | Claude implements; Codex audits; owner approves data/criteria |
| V | Sequential Phase Discipline | PASS | Phase 7 follows Phases 0–6; cites §19#9/#16/#18 |
| VI | Execution Safety Invariants | PASS | Reuses Phase 5 risk pipeline; no order submission |
| VII | No Invented Parameters | PASS | Exit policy, acceptance criteria, and data source require owner approval; no defaults invented |
| VIII | Honest Test Reporting | PASS | Reports include all costs, uncertainty, and sensitivity; no performance claims without evidence |
| IX | Plan-Aligned Evidence | PASS | Dataset/code/config hashes frozen per run; tried-configuration ledger prevents unreported experimentation |

## Project Structure

### Documentation (this feature)

```text
specs/008-backtesting/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── replay-harness.md
└── tasks.md              # Created by /speckit-tasks
```

### Source Code (repository root)

```text
src/
├── scalping_core/
│   ├── backtest/
│   │   ├── replay.py          # Deterministic tick replay engine
│   │   ├── cost_model.py      # Execution cost accounting
│   │   ├── dataset.py         # Dataset loading, validation, hashing
│   │   ├── walk_forward.py    # Walk-forward window management
│   │   ├── leakage.py         # Look-ahead leakage detection
│   │   ├── ledger.py          # Tried-configuration ledger
│   │   ├── report.py          # Structured report generation
│   │   └── slippage.py        # Slippage sensitivity grid
│   └── ...                    # Existing Phase 2–5 modules

tests/
├── test_replay.py
├── test_cost_model.py
├── test_dataset.py
├── test_walk_forward.py
├── test_leakage.py
├── test_ledger.py
└── test_report.py

migrations/
└── 010_backtest_tables.sql
```

**Structure Decision**: Single project with a `backtest/` subpackage
under `src/scalping_core/`. The replay harness wraps the existing Phase
3–5 pipeline — it does not create parallel implementations.

**Sampling Basis (§19#16)**: The replay harness operates on raw ticks
regardless of sampling. §19#16 (sampling basis) is resolved by the
strategy engine configuration, not a separate backtest gate. The
strategy engine's indicator timeframe setting (configured per strategy
by the owner) determines how raw ticks are aggregated. The gate
validation in replay.py checks that the strategy configuration is
complete (which includes the sampling/timeframe setting) before
replay begins. No separate sampling-basis gate entity is needed.
