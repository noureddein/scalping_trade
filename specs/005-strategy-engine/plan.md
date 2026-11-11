# Implementation Plan: Phase 4 — Strategy Engine

**Branch**: `005-strategy-engine` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/005-strategy-engine/spec.md`

## Summary

Implement deterministic market regime classification (6 regimes +
unknown), three independent strategy engines (momentum, breakout,
mean reversion), an explicit regime-to-strategy router (absent by
default), signal validation, and structured recommendation payloads.
All strategies inactive until parameters are explicitly configured.
Recommendation-only — no order placement, no position modification.
Phase 4 covers unit/property tests; historical replay and performance
evaluation belong to Phase 7.

## Technical Context

**Language/Version**: Python 3.12 (backend), no MQL5 changes in Phase 4

**Primary Dependencies**: Standard library (math, collections,
dataclasses); pytest for testing

**Storage**: In-memory. Regime state, indicator values, and
configuration are held per pair in memory. No database persistence in
Phase 4.

**Testing**: pytest with synthetic tick sequences; deterministic
replay fixtures; property tests for boundary conditions

**Target Platform**: WSL2 (backend only for Phase 4)

**Project Type**: Algorithmic trading system — strategy layer

**Performance Goals**: Deterministic reproducibility (SC-001); no
explicit latency target for Phase 4 (tick processing latency is
Phase 3's concern)

**Constraints**: Recommendation-only (FR-011); inactive by default
(FR-007/008); no look-ahead (FR-012); deterministic (FR-013);
fail-closed on missing params (FR-014); all thresholds/maps require
owner approval (§19)

**Scale/Scope**: One pair pilot; per-tick evaluation

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1
design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Platform Target | Pass | Python 3.12 backend; no EA changes |
| II. Fail-Closed Configuration | Pass | FR-007/008/014: missing params/map/thresholds = no signal |
| III. Read-Only Broker Connector | Pass | FR-011: recommendation-only, no order APIs |
| IV. Role Separation | Pass | Claude implements; owner validates parameters |
| V. Sequential Phase Discipline | Pass | Spec cites §7, §7.1–7.5, §8, TRADING_STRATEGY_DESIGN.md |
| VI. Execution Safety Invariants | Pass | Strategy cannot place/amend/close orders (FR-011) |
| VII. No Invented Parameters | Pass | All thresholds/maps deferred to §19; inactive by default |
| VIII. Honest Test Reporting | Pass | FR-015: diagnostics distinct from performance claims |
| IX. Plan-Aligned Evidence | Pass | Phase 4 status: "deterministic prototypes; validation not started" |

No violations. No complexity tracking needed.

## Project Structure

### Documentation (this feature)

```text
specs/005-strategy-engine/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── contracts/
│   └── signal-contract.md # Signal recommendation contract
├── quickstart.md        # Phase 1 output (validation guide)
└── checklists/
    └── requirements.md  # Spec quality checklist
```

### Source Code (repository root)

```text
src/scalping_core/
├── strategy_engine.py    # Regime classifier, router, signal validation
├── momentum_strategy.py  # Momentum continuation hypothesis
├── breakout_strategy.py  # Range breakout hypothesis
├── meanrev_strategy.py   # Mean reversion hypothesis
├── regime_types.py       # Regime enum, regime map, strategy config types
└── market_data.py        # Phase 3 tick stream (consumed by strategies)

tests/
├── test_strategy_engine.py  # Regime, routing, signal validation tests
├── test_momentum.py         # Momentum-specific unit/property tests
├── test_breakout.py         # Breakout-specific unit/property tests
└── test_meanrev.py          # Mean reversion-specific unit/property tests
```

**Structure Decision**: Extends existing flat module layout.
`strategy_engine.py` already exists from the code scaffold. Phase 4
fills it with deterministic regime classification, routing, and
validation. Each strategy gets its own module for independent testing.

## Complexity Tracking

No violations to justify.
