# Implementation Plan: Phase 3 — Market Data and Spread

**Branch**: `004-market-data-spread` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-market-data-spread/spec.md`

## Summary

Implement live tick ingestion and validation, tick batch handling with
deduplication and gap detection, spread calculation from broker contract
specs, rolling spread statistics (9 metrics per pair), hybrid spread
protection gates (manual + adaptive), 60-second stability recovery,
and market anomaly detection (staleness, low activity, abnormal
volatility). All processing is in-memory; no tick-by-tick database
storage.

## Technical Context

**Language/Version**: Python 3.12 (backend), MQL5 (EA tick delivery)

**Primary Dependencies**: Standard library (time, collections, math);
pytest for testing

**Storage**: In-memory for ticks, spread state, and statistics.
Aggregated spread snapshots may persist to PostgreSQL in later phases.

**Testing**: pytest with synthetic tick sequences; end-to-end live-tick
validation requires native Windows MT5 + WSL backend (owner-performed)

**Target Platform**: WSL2 (backend) ↔ Windows (MT5), TCP at 127.0.0.1

**Project Type**: Algorithmic trading system — market data layer

**Performance Goals**: Tick processing < 100ms (SC-001); spread gate
enforcement within 1 tick of violation (SC-005)

**Constraints**: In-memory only; no tick-by-tick PostgreSQL storage;
fail-closed on missing spread gates; adaptive thresholds require owner
approval (§19#2); staleness threshold default requires owner approval

**Scale/Scope**: One pair pilot; tick rates of 1–50 ticks/second per
pair in normal conditions; burst behavior unverified

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1
design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Platform Target | Pass | Ticks delivered via TCP loopback from EA |
| II. Fail-Closed Configuration | Pass | FR-006: no entry without both spread gates configured |
| III. Read-Only Broker Connector | Pass | Tick ingestion is read-only; no order interaction |
| IV. Role Separation | Pass | Claude implements; owner validates live-tick accuracy |
| V. Sequential Phase Discipline | Pass | Spec cites §12, §12.1–12.5, §14.2, strategy design §3.2 |
| VI. Execution Safety Invariants | Pass | Spread gates block entries; spread spikes don't force-close positions (FR-008) |
| VII. No Invented Parameters | Pass | Adaptive thresholds deferred to §19#2; no invented defaults |
| VIII. Honest Test Reporting | Pass | Synthetic tests labeled as such; live-tick validation requires owner |
| IX. Plan-Aligned Evidence | Pass | Phase 3 status notes "live-feed acceptance pending" |

No violations. No complexity tracking needed.

## Project Structure

### Documentation (this feature)

```text
specs/004-market-data-spread/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── contracts/
│   └── tick-protocol.md # Tick message contract (extends Phase 2 TCP protocol)
├── quickstart.md        # Phase 1 output (validation guide)
└── checklists/
    └── requirements.md  # Spec quality checklist
```

### Source Code (repository root)

```text
src/scalping_core/
├── market_data.py        # Tick validation, batching, dedup, staleness
├── spread_engine.py      # Spread calculation, statistics, gates, stability
├── broker_types.py       # Tick and spread types (shared with Phase 2)
└── tcp_broker_adapter.py # Tick message parsing (extends Phase 2)

mql5/
└── ReadOnlyConnector.mq5 # EA tick delivery (extends Phase 2)

tests/
├── test_market_data.py   # Tick validation, batch, dedup tests
└── test_spread_engine.py # Spread calculation, gate, stability tests
```

**Structure Decision**: Extends existing flat module layout. `market_data.py`
and `spread_engine.py` already exist from the code scaffold. Phase 3
fills them with validated tick processing and spread intelligence.

## Complexity Tracking

No violations to justify.
