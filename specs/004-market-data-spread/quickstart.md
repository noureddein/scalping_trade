# Quickstart Validation Guide: Phase 3 — Market Data and Spread

**Date**: 2026-11-10

## Prerequisites

- Python 3.12 environment (WSL2)
- Phase 2 broker connectivity passing (connection, symbol discovery,
  contract specs)
- pytest installed
- At least one canonical symbol mapped with contract specification

## Validation Scenarios

### 1. Tick Validation (FR-001, SC-001, SC-002)

**What to verify**: Valid ticks accepted, invalid ticks rejected with
structured reasons, processing under 100ms.

**Test approach**: Feed synthetic tick sequences with known valid and
invalid ticks. Verify acceptance/rejection and reason codes.

| Input | Expected Result |
|-------|-----------------|
| Valid tick (ask > bid, advancing timestamp) | Accepted, forwarded |
| Crossed tick (ask < bid) | Rejected: CROSSED |
| Duplicate timestamp | Rejected: DUPLICATE |
| Non-advancing timestamp | Rejected: REORDERED |
| Non-finite value (NaN, inf) | Rejected: MALFORMED |
| Zero or negative price | Rejected: MALFORMED |

**Command**: `pytest tests/test_market_data.py -k "test_tick_validation" -v`

---

### 2. Batch Processing and Deduplication (FR-002, SC-007)

**What to verify**: Batches processed, duplicates discarded, gaps
detected, EA run boundaries recognized.

| Input | Expected Result |
|-------|-----------------|
| Batch with 3 unique ticks | All 3 accepted |
| Batch with 1 duplicate tick | Duplicate discarded, others accepted |
| Sequence gap (batch 5 → batch 8) | Gap interval marked degraded |
| New run_counter | Run boundary logged, sequences reset |

**Command**: `pytest tests/test_market_data.py -k "test_batch" -v`

---

### 3. Spread Calculation (FR-003, SC-003)

**What to verify**: Spread calculated using broker contract spec, not
hardcoded pip values.

| Symbol | Digits | Point | Bid | Ask | Expected Spread (pips) |
|--------|--------|-------|-----|-----|----------------------|
| EURUSD | 5 | 0.00001 | 1.08542 | 1.08557 | 1.5 |
| USDJPY | 3 | 0.001 | 149.123 | 149.138 | 1.5 |
| XAUUSD | 2 | 0.01 | 2650.50 | 2651.00 | 50.0 |

**Command**: `pytest tests/test_spread_engine.py -k "test_spread_calculation" -v`

---

### 4. Rolling Spread Statistics (FR-004, SC-004)

**What to verify**: All 9 metrics populated after warm-up, update on
each new tick.

**Metrics to check**: current, average, median, max, min, volatility,
percentile, trend, anomaly_flag.

**Test approach**: Feed N ticks with known spread values. Verify each
metric matches hand-calculated expected values.

**Command**: `pytest tests/test_spread_engine.py -k "test_statistics" -v`

---

### 5. Spread Gate Enforcement (FR-005, FR-006, SC-005)

**What to verify**: Entry blocked when manual or adaptive gate fails;
fail-closed when gates unconfigured.

| Scenario | Manual Max | Adaptive Threshold | Current Spread | Entry Eligible? |
|----------|-----------|-------------------|---------------|----------------|
| Both passing | 2.0 | 1.8 | 1.5 | Yes |
| Manual fails | 2.0 | 1.8 | 2.5 | No |
| Adaptive fails | 2.0 | 1.8 | 1.9 | No |
| Manual unconfigured | NULL | 1.8 | 1.5 | No (fail-closed) |
| Adaptive unconfigured | 2.0 | NULL | 1.5 | No (fail-closed) |
| Both unconfigured | NULL | NULL | 1.5 | No (fail-closed) |

**Command**: `pytest tests/test_spread_engine.py -k "test_spread_gate" -v`

---

### 6. Stability Recovery (FR-007, SC-005)

**What to verify**: 60-second stable period required after abnormality;
timer resets on new spike; per-pair isolation.

| Scenario | Expected |
|----------|----------|
| Spread spike → 60s stable | Entries re-enabled |
| Spread spike → 30s stable → spike | Timer resets to 0 |
| Pair A spike, Pair B normal | Only A blocked |

**Command**: `pytest tests/test_spread_engine.py -k "test_stability" -v`

---

### 7. Stale Data Detection (FR-009, SC-006)

**What to verify**: Staleness detected after configurable threshold;
signal generation blocked for affected pair.

| Scenario | Expected |
|----------|----------|
| No ticks for > threshold | Pair marked stale, entries blocked |
| Tick arrives after stale period | Stale cleared, stability check starts |

**Command**: `pytest tests/test_market_data.py -k "test_staleness" -v`

---

### 8. Existing Position Protection (FR-008)

**What to verify**: A spread spike does NOT force-close an open
position. Spread protection applies to new entries only.

**Test approach**: Simulate an open position, trigger a spread spike,
verify the position is unaffected and only new entries are blocked.

**Command**: `pytest tests/test_spread_engine.py -k "test_position_protection" -v`

---

## Test Matrix

| Scenario | Automated (pytest) | Manual (live MT5) |
|----------|-------------------|-------------------|
| Tick validation | Yes | Owner validates live-tick accuracy |
| Batch/dedup | Yes | Owner validates EA batching behavior |
| Spread calculation | Yes | Owner verifies against MT5 display |
| Rolling statistics | Yes | — |
| Spread gates | Yes | — |
| Stability recovery | Yes | Owner observes during volatile session |
| Stale detection | Yes | Owner tests during market close/open |
| Position protection | Yes | — |

**Note**: Live-feed acceptance tests require native Windows MT5 with
the EA connected to the WSL2 backend. These are owner-performed
validation, not automated CI tests (Constitution Principle VIII).
