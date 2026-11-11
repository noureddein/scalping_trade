# Quickstart Validation Guide: Phase 4 — Strategy Engine

**Date**: 2026-11-10

## Prerequisites

- Python 3.12 environment (WSL2)
- Phase 3 market data passing (tick validation, spread calculation)
- pytest installed
- No strategy parameters configured (inactive-by-default is the
  starting state)

## Validation Scenarios

### 1. Inactive-by-Default (FR-007, FR-008, SC-003)

**What to verify**: With no parameters or regime map configured, the
system produces zero signals.

| Input | Expected Result |
|-------|-----------------|
| Any tick sequence, no config | Zero signals, all NO_SIGNAL reasons logged |
| Regime map absent | NO_REGIME_MAP reason |
| Strategy params absent | STRATEGY_INACTIVE reason |

**Command**: `pytest tests/test_strategy_engine.py -k "test_inactive_default" -v`

---

### 2. Regime Classification (FR-001, FR-002, FR-003, SC-002)

**What to verify**: Each regime is correctly classified from synthetic
tick sequences. Unknown returned for insufficient history or degraded
data.

| Input | Expected Regime |
|-------|-----------------|
| Clear uptrend (aligned EMAs, positive slope) | TRENDING |
| Narrow oscillation, near-zero slope | RANGING |
| Price breaks above prior channel | BREAKOUT |
| High dispersion, wide swings | HIGH_VOLATILITY |
| Very narrow range, low dispersion | LOW_VOLATILITY |
| Gapped data, stale feed | UNSTABLE |
| 3 ticks (below warm-up) | UNKNOWN |

**Command**: `pytest tests/test_strategy_engine.py -k "test_regime" -v`

---

### 3. Momentum Strategy (FR-004, SC-001)

**What to verify**: BUY/SELL signals at correct conditions; no signal
on equality, insufficient history, or missing params.

| Scenario | Expected |
|----------|----------|
| Fast EMA > slow EMA by min, positive velocity | BUY signal |
| Fast EMA < slow EMA by min, negative velocity | SELL signal |
| EMAs equal | No signal |
| Insufficient EMA history | No signal |
| Missing any momentum parameter | Strategy inactive |

**Command**: `pytest tests/test_momentum.py -v`

---

### 4. Breakout Strategy (FR-005, SC-001)

**What to verify**: BUY/SELL on genuine channel breaks; rejection of
spread-only jumps and narrow channels.

| Scenario | Expected |
|----------|----------|
| Price > channel high by margin | BUY signal |
| Price < channel low by margin | SELL signal |
| Spread-only apparent breakout | No signal (filtered) |
| Channel width < minimum | No signal |
| Channel includes candidate tick | Test failure (look-ahead) |

**Command**: `pytest tests/test_breakout.py -v`

---

### 5. Mean Reversion Strategy (FR-006, SC-001)

**What to verify**: BUY/SELL on deviation from mean in ranging regime;
no signal in prohibited regimes; no signal on zero variance.

| Scenario | Expected |
|----------|----------|
| Ranging, price below mean by threshold | BUY signal |
| Ranging, price above mean by threshold | SELL signal |
| Trending regime, same deviation | No signal (prohibited) |
| Zero standard deviation | No signal |
| Feed gap causing deviation | No signal |

**Command**: `pytest tests/test_meanrev.py -v`

---

### 6. Regime-to-Strategy Routing (FR-008, FR-009, SC-006)

**What to verify**: Correct dispatch via regime map; no dispatch when
map absent or regime unmapped.

| Scenario | Expected |
|----------|----------|
| TRENDING mapped to momentum, regime=TRENDING | Momentum dispatched |
| RANGING mapped to meanrev, regime=RANGING | Mean reversion dispatched |
| Regime not in map | No signal |
| Map absent | No signal for all regimes |
| UNSTABLE even if mapped | No signal (safety override) |

**Command**: `pytest tests/test_strategy_engine.py -k "test_routing" -v`

---

### 7. Signal Validation and Payload (FR-010, FR-014, SC-007)

**What to verify**: Signals contain all required fields; signals below
quality threshold are suppressed; missing threshold = fail-closed.

| Scenario | Expected |
|----------|----------|
| Valid signal above threshold | Full payload with all fields |
| Signal below quality threshold | Suppressed, reason logged |
| No quality threshold configured | Suppressed (fail-closed) |
| Payload missing any required field | Test failure |

**Command**: `pytest tests/test_strategy_engine.py -k "test_signal_validation" -v`

---

### 8. Determinism and No-Look-Ahead (FR-012, FR-013, SC-005)

**What to verify**: Identical inputs produce identical outputs; no
feature calculation accesses future data.

| Scenario | Expected |
|----------|----------|
| Same ticks + config run twice | Identical signals |
| Breakout channel boundary check | Channel excludes candidate tick |
| EMA with future tick removed | Same EMA value at prior timestamps |

**Command**: `pytest tests/test_strategy_engine.py -k "test_determinism or test_lookahead" -v`

---

### 9. Recommendation-Only (FR-011, SC-004)

**What to verify**: The strategy module never calls order APIs or
modifies account/position state.

**Test approach**: Verify that no strategy code path imports or calls
order/execution/position modules. Integration test with mock execution
layer confirms no side effects.

**Command**: `pytest tests/test_strategy_engine.py -k "test_recommendation_only" -v`

---

## Test Matrix

| Scenario | Automated (pytest) | Manual |
|----------|-------------------|--------|
| Inactive-by-default | Yes | — |
| Regime classification | Yes | — |
| Momentum signals | Yes | — |
| Breakout signals | Yes | — |
| Mean reversion signals | Yes | — |
| Routing | Yes | — |
| Signal validation | Yes | — |
| Determinism/no-look-ahead | Yes | — |
| Recommendation-only | Yes | — |

**Note**: Phase 4 is entirely testable with synthetic data and pytest.
No live MT5 connection required. Live-feed strategy validation requires
Phase 7 replay infrastructure and approved parameters.
