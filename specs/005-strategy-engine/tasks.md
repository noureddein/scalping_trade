# Tasks: Phase 4 — Strategy Engine

**Input**: Design documents from `specs/005-strategy-engine/`

**Prerequisites**: plan.md, spec.md, data-model.md, contracts/signal-contract.md, research.md, quickstart.md

**Note**: Phase 4 implements deterministic regime classification, three independent strategy
hypotheses (momentum, breakout, mean reversion), regime-to-strategy routing, and signal
validation. All strategies inactive by default. Recommendation-only — no order placement.
All processing in-memory.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US6)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: Shared type definitions for regime, strategy config, and signal types

- [x] T001 Create src/scalping_core/regime_types.py defining: MarketRegime enum (TRENDING, RANGING, BREAKOUT, HIGH_VOLATILITY, LOW_VOLATILITY, UNSTABLE, UNKNOWN — no other labels permitted per FR-002), SignalDirection enum (BUY, SELL), NoSignalReasonCode enum (INSUFFICIENT_HISTORY, DEGRADED_DATA, UNSTABLE_REGIME, NO_REGIME_MAP, REGIME_NOT_MAPPED, STRATEGY_INACTIVE, MISSING_PARAMS, INVALID_CONFIG, BELOW_QUALITY_THRESHOLD, NO_SIGNAL_CONDITIONS, PROHIBITED_REGIME, ZERO_VARIANCE, SPREAD_ONLY_BREAKOUT, CHANNEL_TOO_NARROW), SpreadTrend enum reuse from Phase 3 if present
- [x] T002 Add to src/scalping_core/regime_types.py: RegimeClassification dataclass (pair: str, regime: MarketRegime, confidence_features: dict, timestamp: datetime, is_valid: bool — False if insufficient history or degraded data), RegimeMap dataclass (mappings: dict str→str — regime→strategy_name, is_configured: bool default False), StrategyConfig dataclass (strategy_name: str one of "momentum"/"breakout"/"meanrev", is_active: bool True only when all required params set, parameters: dict all must be finite/valid), FeatureSnapshot dataclass (all 16 fields from data-model.md: pair str, timestamp datetime, mid_price Decimal, bid Decimal, ask Decimal, fast_ema Decimal|None, slow_ema Decimal|None, ema_spread Decimal|None, price_velocity Decimal|None, channel_high Decimal|None, channel_low Decimal|None, channel_width Decimal|None, rolling_mean Decimal|None, rolling_std Decimal|None, z_score Decimal|None, volatility Decimal|None), RegimeClassifierConfig dataclass (warm_up_threshold: positive int or None fail-closed, volatility_baseline: positive Decimal or None fail-closed, breakout_exceedance: positive Decimal or None fail-closed, trending_min_slope: positive Decimal or None fail-closed, trending_ema_alignment_min: positive Decimal or None fail-closed, low_volatility_ceiling: positive Decimal or None fail-closed, is_configured: bool True only when ALL thresholds set — all require owner approval per §19)
- [x] T003 Add to src/scalping_core/regime_types.py: SignalRecommendation dataclass (pair: str, direction: SignalDirection, strategy_name: str, regime: MarketRegime, reference_bid: Decimal, reference_ask: Decimal, features: FeatureSnapshot, strength: Decimal strategy-local/not cross-comparable, timestamp: datetime, signal_id: str UUID), NoSignalReason dataclass (pair: str, reason_code: NoSignalReasonCode, detail: str, timestamp: datetime)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Strategy base class and config validation that all strategies depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T004 Implement abstract strategy base in src/scalping_core/strategy_engine.py: define a Strategy protocol/ABC with evaluate(pair, tick, features) → SignalRecommendation | NoSignalReason. Strategies MUST NOT call order APIs, modify positions, or change account state (FR-011). Include validate_config(config: StrategyConfig) → bool that checks all required params are present and finite
- [x] T005 Implement StrategyConfig validation in src/scalping_core/strategy_engine.py: for each strategy name, define required parameter names — momentum: (fast_ema_period: positive int, slow_ema_period: positive int, min_ema_spread: positive Decimal, min_velocity: positive Decimal, velocity_lookback: positive int, signal_quality_threshold: positive Decimal), breakout: (channel_lookback: positive int, min_channel_width: positive Decimal, breakout_margin: positive Decimal, signal_quality_threshold: positive Decimal), meanrev: (rolling_period: positive int, deviation_threshold: positive Decimal, signal_quality_threshold: positive Decimal). Strategy is_active = True only when ALL required params are set and valid

**Checkpoint**: Strategy protocol and config validation ready — strategies can be implemented

---

## Phase 2.5: Feature Computation (Blocking Prerequisite for US1–US6)

**Purpose**: Compute shared FeatureSnapshot from validated tick stream — feeds both classifier and strategies

**⚠️ CRITICAL**: Regime classifier and all strategies consume FeatureSnapshot; this must exist first

- [x] T005b Implement feature computation in src/scalping_core/strategy_engine.py: given a validated tick and pair's StrategyConfig(s), compute FeatureSnapshot with all 16 fields from data-model.md. EMA (fast/slow) from mid_price series. price_velocity = Δmid_price / Δtime over configurable velocity_lookback (owner-approved). Channel high/low from Ask-side highs and Bid-side lows over channel_lookback. rolling_mean/rolling_std over rolling_period. z_score = (mid_price - rolling_mean) / rolling_std (None if std=0). volatility = rolling dispersion. Fields are None when the corresponding strategy is inactive or insufficient history exists. Single computation per tick, shared by classifier and all strategies
- [x] T005c Write unit tests in tests/test_strategy_engine.py: test FeatureSnapshot computation for known tick sequence (verify EMA, velocity, channel, rolling stats against manual calculation), test None fields when strategy inactive, test insufficient history returns None fields, test EMA uses mid_price

**Checkpoint**: FeatureSnapshot computed from ticks — classifier and strategies have input

---

## Phase 3: User Story 1 — Classify Market Regime Per Pair (Priority: P1) 🎯 MVP

**Goal**: Deterministic regime classification for each pair; unknown when data insufficient

**Independent Test**: Feed synthetic tick sequences → verify correct regime labels with deterministic output

- [x] T006 [US1] Implement regime classifier in src/scalping_core/strategy_engine.py: classify per pair using classification priority from data-model.md — (1) UNSTABLE: degraded data/stale/gapped/insufficient history (from MarketHealthState), (2) HIGH_VOLATILITY: volatility > RegimeClassifierConfig.volatility_baseline, (3) BREAKOUT: price outside channel by RegimeClassifierConfig.breakout_exceedance, (4) TRENDING: slope > RegimeClassifierConfig.trending_min_slope with EMA spread > RegimeClassifierConfig.trending_ema_alignment_min, (5) LOW_VOLATILITY: volatility < RegimeClassifierConfig.low_volatility_ceiling, (5b) RANGING: not LOW_VOLATILITY but narrow range near-zero slope, (6) UNKNOWN: ambiguous, none match, or RegimeClassifierConfig not configured (fail-closed). Return RegimeClassification with confidence_features dict. Use only past and current data (no look-ahead per FR-012). Identical input → identical output (FR-013). Default cadence: evaluate per tick. Cadence is a configurable policy — per-tick is the Phase 4 default; alternatives (per bar, throttled) deferred to Phase 7
- [x] T007 [US1] Implement warm-up and degraded-data handling in src/scalping_core/strategy_engine.py: return UNKNOWN (is_valid=False) when insufficient tick history exists (below warm-up threshold). Return UNSTABLE when data quality is degraded (gaps from Phase 3 MarketHealthState, stale feed, crossed quotes). Warm-up threshold is a configurable parameter — fail closed if not set (FR-003)
- [x] T008 [US1] Write unit tests in tests/test_strategy_engine.py: test each regime label with synthetic tick sequences (TRENDING: directional slope + EMA alignment, RANGING: narrow oscillation + zero slope, BREAKOUT: channel exceedance, HIGH_VOLATILITY: high dispersion, LOW_VOLATILITY: low dispersion, UNSTABLE: degraded data, UNKNOWN: insufficient history), test determinism (same input → same output), test classification priority ordering, test no-look-ahead property: feed N ticks and record regime at tick K, then append different ticks after K — regime at K must be identical (SC-005)

**Checkpoint**: Regime classifier produces correct labels deterministically

---

## Phase 4: User Story 2 — Generate Momentum Strategy Signals (Priority: P1)

**Goal**: BUY/SELL/no-signal based on EMA alignment, velocity, strength; Ask=BUY ref, Bid=SELL ref

**Independent Test**: Feed trending ticks with configured momentum params → verify BUY/SELL at expected points

- [x] T009 [P] [US2] Implement momentum strategy in src/scalping_core/momentum_strategy.py: evaluate EMA alignment (fast_ema vs slow_ema by min_ema_spread), price_velocity (positive → BUY, negative → SELL), momentum strength = min(1.0, abs(ema_spread) / min_ema_spread × abs(price_velocity) / min_velocity) clamped [0, 1], strategy-local. Use Ask as BUY reference price, Bid as SELL reference price (FR-004). Emit SignalRecommendation with strategy_name="momentum", full FeatureSnapshot, and signal_id (UUID). At EMA equality → no signal. When no momentum params configured → STRATEGY_INACTIVE NoSignalReason. All calculations use past/current data only (FR-012)
- [x] T010 [P] [US2] Write unit tests in tests/test_momentum.py: test BUY signal (fast EMA > slow EMA by min_ema_spread, positive velocity), test SELL signal (symmetric), test no signal at EMA equality, test inactive when no params configured (SC-003), test reference price correctness (BUY uses Ask, SELL uses Bid), test determinism, test all required fields in SignalRecommendation (SC-007)

**Checkpoint**: Momentum strategy produces correct signals in isolation

---

## Phase 5: User Story 3 — Generate Breakout Strategy Signals (Priority: P1)

**Goal**: BUY/SELL on channel breakout; reject spread-only jumps and narrow channels

**Independent Test**: Build channel → break out → verify signal; widen spread only → verify no signal

- [x] T011 [P] [US3] Implement breakout strategy in src/scalping_core/breakout_strategy.py: build price channel from channel_lookback observations excluding the candidate (Ask-side highs, Bid-side lows per FR-005). BUY when price > channel_high + breakout_margin (normalized), SELL when price < channel_low - breakout_margin. Reject spread-only jumps: if the move is entirely attributable to spread widening, emit NoSignalReason SPREAD_ONLY_BREAKOUT. Reject channels narrower than min_channel_width with NoSignalReason CHANNEL_TOO_NARROW. Strength = min(1.0, (price - channel_boundary) / breakout_margin) where channel_boundary is channel_high for BUY or channel_low for SELL — clamped [0, 1], strategy-local. When no breakout params configured → STRATEGY_INACTIVE
- [x] T012 [P] [US3] Write unit tests in tests/test_breakout.py: test BUY on genuine upside breakout, test SELL on genuine downside breakout, test spread-only jump rejection, test narrow channel rejection, test channel excludes candidate observation, test inactive when no params, test determinism

**Checkpoint**: Breakout strategy correctly identifies genuine breakouts

---

## Phase 6: User Story 4 — Generate Mean Reversion Strategy Signals (Priority: P1)

**Goal**: BUY/SELL on deviation from rolling mean in RANGING regime only; prohibited in other regimes

**Independent Test**: Feed ranging ticks → verify signals at deviation threshold; switch to trending → verify suppression

- [x] T013 [P] [US4] Implement mean reversion strategy in src/scalping_core/meanrev_strategy.py: compute rolling_mean and rolling_std over rolling_period observations. BUY when z_score = (price - mean) / std < -deviation_threshold, SELL when z_score > +deviation_threshold. MUST NOT produce signals in TRENDING, BREAKOUT, HIGH_VOLATILITY, or UNSTABLE regimes (FR-006) — emit NoSignalReason PROHIBITED_REGIME. When rolling_std is zero → NoSignalReason ZERO_VARIANCE (no division by zero). Strength = min(1.0, abs(z_score) / deviation_threshold) — clamped [0, 1], strategy-local. When no meanrev params configured → STRATEGY_INACTIVE
- [x] T014 [P] [US4] Write unit tests in tests/test_meanrev.py: test BUY signal below mean by threshold in RANGING, test SELL signal above mean in RANGING, test suppression in TRENDING regime, test suppression in BREAKOUT regime, test zero-variance handling, test inactive when no params, test determinism

**Checkpoint**: Mean reversion generates correct signals only in permitted regimes

---

## Phase 7: User Story 5 — Route Regime to Strategy (Priority: P1)

**Goal**: Dispatch exactly one strategy per pair per decision via explicit map; absent map = no signal

**Independent Test**: Configure map → verify correct strategy dispatch; remove map → verify zero signals

- [x] T015 [US5] Implement regime-to-strategy router in src/scalping_core/strategy_engine.py: accept RegimeMap and current RegimeClassification, dispatch to exactly one strategy (FR-009). When RegimeMap.is_configured is False → NoSignalReason NO_REGIME_MAP. When regime is not in mappings → NoSignalReason REGIME_NOT_MAPPED. When regime is UNSTABLE → NoSignalReason UNSTABLE_REGIME regardless of mapping (safety override). Strength values from different strategies MUST NOT be compared (FR-009)
- [x] T016 [US5] Write unit tests in tests/test_strategy_engine.py: test correct dispatch (TRENDING→momentum), test no signal when map absent (SC-003/SC-006), test no signal when regime unmapped, test UNSTABLE override (even if mapped), test exactly one strategy per decision, test no cross-strategy strength comparison

**Checkpoint**: Routing dispatches correct strategy per regime; absent map = no signals

---

## Phase 8: User Story 6 — Validate Signal Quality and Emit Recommendation (Priority: P1)

**Goal**: Quality-check signals against thresholds; package valid signals as recommendations

**Independent Test**: Generate valid signal → verify all fields present; fail quality → verify suppression

- [x] T017 [US6] Implement signal validation in src/scalping_core/strategy_engine.py: after strategy produces a signal, validate against signal_quality_threshold (per strategy config). Suppress signals where strength < signal_quality_threshold with NoSignalReason BELOW_QUALITY_THRESHOLD. Suppress signals with missing quality threshold with NoSignalReason MISSING_PARAMS (fail-closed per FR-014). Validate all required recommendation fields per contracts/signal-contract.md: signal_id, pair, direction, strategy_name, regime, reference_bid, reference_ask, strength, features (FeatureSnapshot), timestamp
- [x] T018 [US6] Write unit tests in tests/test_strategy_engine.py: test valid signal passes quality check and contains all 10 required fields (SC-007), test signal below threshold is suppressed, test missing threshold = fail-closed, test recommendation payload matches signal-contract.md schema, test that strategy module never calls order APIs in any test scenario (SC-004)

**Checkpoint**: Signal validation enforces quality gates; recommendations contain all required fields

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Integration, cross-strategy validation, and end-to-end scenarios

- [x] T019 [P] Wire the full pipeline in src/scalping_core/strategy_engine.py: tick → regime classification → routing → strategy dispatch → signal validation → recommendation/no-signal. Ensure the pipeline is callable from Phase 3 market_data consumer (takes validated tick, returns SignalRecommendation or NoSignalReason)
- [x] T020 Write integration tests in tests/test_strategy_engine.py: test full pipeline with all three strategies configured (one active per regime), test pipeline with zero strategies configured (no signals for any input per SC-003), test pipeline with partial configuration (only momentum configured), test FR-015 (diagnostics do not make performance claims)
- [x] T021 Run quickstart.md validation scenarios end-to-end and record PASS/FAIL evidence

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — T001–T003 can start immediately
- **Foundational (Phase 2)**: Depends on Setup — T004/T005 need regime_types
- **Feature Computation (Phase 2.5)**: Depends on Foundational — T005b/T005c need types and config validation
- **User Stories (Phases 3–8)**: All depend on Feature Computation (Phase 2.5)
  - US1 must complete before US5 (routing needs regime classification)
  - US2, US3, US4 can run in parallel (independent strategies, separate files)
  - US5 depends on US1 + at least one strategy (US2/US3/US4)
  - US6 depends on US5 (validation needs routed signals)
- **Polish (Phase 9)**: Depends on all user stories

### User Story Dependencies

- **US1 (P1)**: No dependencies — regime classification is foundational
- **US2 (P1)**: Depends on Foundational only (independent strategy)
- **US3 (P1)**: Depends on Foundational only (independent strategy)
- **US4 (P1)**: Depends on Foundational only (independent strategy)
- **US5 (P1)**: Depends on US1 (needs regime) + US2/US3/US4 (needs strategies to dispatch)
- **US6 (P1)**: Depends on US5 (needs routed signal to validate)

### Parallel Opportunities

- US2, US3, US4 can all run in parallel (separate files: momentum_strategy.py, breakout_strategy.py, meanrev_strategy.py)
- Within each strategy story, implementation and tests are [P] (separate files)
- T001–T003 are sequential (same file) but T001 can be split if needed

---

## Parallel Example: Three Strategies in Parallel

```bash
# After US1 (regime classifier) completes:
# US2: T009-T010 in momentum_strategy.py + test_momentum.py
# US3: T011-T012 in breakout_strategy.py + test_breakout.py
# US4: T013-T014 in meanrev_strategy.py + test_meanrev.py
# All three are independent — different files, no shared state
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete T001–T003 (Setup: types and enums)
2. Complete T004–T005 (Foundational: strategy protocol and config validation)
3. Complete T006–T008 (US1: regime classifier)
4. **STOP and VALIDATE**: Regime labels correct for all synthetic scenarios
5. Proceed to US2–US6

### Incremental Delivery

1. Setup + Foundational → types and protocol ready
2. US1 (T006–T008) → regime classification works
3. US2 + US3 + US4 (parallel: T009–T014) → all three strategies work independently
4. US5 (T015–T016) → routing dispatches correct strategy
5. US6 (T017–T018) → signal validation enforces quality
6. Polish (T019–T021) → full pipeline wired, integration tested

---

## Notes

- All strategies inactive by default — no signals until params explicitly configured (FR-007/008)
- All strategy parameters are unresolved (§19) — implement the mechanism, not the values
- Strategy module is recommendation-only — never calls order APIs (FR-011, constitution Principle III)
- Strength values are strategy-local and MUST NOT be compared across strategies (FR-009)
- Phase 4 diagnostics are distinct from performance claims (FR-015)
- No look-ahead in any feature calculation (FR-012)
- Identical input + configuration → identical output (FR-013)
- No database persistence in Phase 4; all state in-memory
