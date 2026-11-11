# Feature Specification: Phase 4 — Strategy Engine

**Feature Branch**: `005-strategy-engine`

**Created**: 2026-11-10

**Status**: Draft

**Input**: User description: "Create a specification for the Phase 4: Strategy engine"

**Master Plan Reference**: Phase 4 (line 1076), §7 Strategy Framework, §7.1–7.5, §8 Trade Entry pipeline steps 6–8, TRADING_STRATEGY_DESIGN.md §§1–9

## User Scenarios & Testing

### User Story 1 - Classify Market Regime Per Pair (Priority: P1)

The system classifies the current market regime for each active pair
using only past and current observations. Possible regimes: TRENDING,
RANGING, BREAKOUT, HIGH_VOLATILITY, LOW_VOLATILITY, UNSTABLE, or
unknown. Classification uses deterministic, explainable features.
When insufficient history exists, ambiguous conditions arise, or data
quality is degraded, the system returns unknown (no classification).

**Why this priority**: Regime classification gates strategy selection.
An incorrect or unavailable regime blocks the entire signal path,
making it the first dependency in the strategy pipeline.

**Independent Test**: Feed synthetic tick sequences representing each
regime. Verify the classifier produces the expected regime label with
deterministic, reproducible output.

**Acceptance Scenarios**:

1. **Given** a sequence of ticks with a clear directional slope and
   EMA alignment, **When** regime is classified, **Then** the result
   is TRENDING.
2. **Given** a sequence with price oscillating within a narrow range
   and near-zero slope, **When** classified, **Then** the result is
   RANGING.
3. **Given** a price move beyond a prior channel by the configured
   breakout_exceedance margin, **When** classified, **Then** the
   result is BREAKOUT.
4. **Given** insufficient tick history (below warm-up threshold),
   **When** classified, **Then** the result is unknown.
5. **Given** degraded data (gaps, stale feed, crossed quotes), **When**
   classified, **Then** the result is UNSTABLE.
6. **Given** identical input and configuration, **When** classified
   multiple times, **Then** the output is identical every time.

---

### User Story 2 - Generate Momentum Strategy Signals (Priority: P1)

The momentum strategy evaluates EMA alignment, price velocity, and
momentum strength for a pair whose regime is explicitly mapped to
momentum. It emits BUY, SELL, or no signal. It uses Ask as the BUY
reference and Bid as the SELL reference. Missing parameters,
insufficient history, or failed gates produce no signal.

**Why this priority**: Momentum is one of three independent strategy
hypotheses. Each must be testable in isolation before any routing or
comparison.

**Independent Test**: Feed a trending tick sequence with configured
momentum parameters. Verify BUY/SELL signals at expected points and
no signal when conditions are not met.

**Acceptance Scenarios**:

1. **Given** a trending regime with fast EMA above slow EMA by the
   configured minimum and positive velocity, **When** evaluated,
   **Then** a BUY signal is emitted with strategy metadata.
2. **Given** symmetric conditions (fast EMA below slow EMA, negative
   velocity), **When** evaluated, **Then** a SELL signal is emitted.
3. **Given** EMA values at exact equality, **When** evaluated, **Then**
   no signal is produced.
4. **Given** no momentum parameters configured, **When** evaluated,
   **Then** the strategy is disabled and emits no signal.

---

### User Story 3 - Generate Breakout Strategy Signals (Priority: P1)

The breakout strategy evaluates whether the current price has moved
beyond a prior price channel by a configured normalized margin. The
channel must exclude the candidate observation. It uses Ask-side highs
and Bid-side lows for channel boundaries. Spread-only jumps are
filtered out. Missing parameters or insufficient channel history
produce no signal.

**Why this priority**: Breakout is the second independent hypothesis,
requiring isolated testability.

**Independent Test**: Feed a tick sequence that builds a channel then
breaks out. Verify signal generation at breakout and rejection of
false breakouts.

**Acceptance Scenarios**:

1. **Given** a price exceeding the prior channel high by the configured
   margin, **When** evaluated, **Then** a BUY signal is emitted.
2. **Given** a price below the prior channel low by the configured
   margin, **When** evaluated, **Then** a SELL signal is emitted.
3. **Given** a price move caused entirely by a spread widening (not a
   genuine breakout), **When** evaluated, **Then** no signal is
   produced.
4. **Given** a channel width below the configured min_channel_width,
   **When** evaluated, **Then** no signal is produced.

---

### User Story 4 - Generate Mean Reversion Strategy Signals (Priority: P1)

The mean reversion strategy evaluates deviation from a rolling
reference in a ranging regime. It emits BUY when price is below the
mean by a configured standardized deviation, and SELL symmetrically
above. It does not fade moves in trending, breakout, high-volatility,
or unstable regimes. Missing parameters produce no signal.

**Why this priority**: Mean reversion is the third independent
hypothesis, completing the strategy set.

**Independent Test**: Feed a ranging tick sequence with known mean and
deviation. Verify signals at configured thresholds and no signal in
prohibited regimes.

**Acceptance Scenarios**:

1. **Given** a ranging regime with price below the rolling mean by
   the configured deviation threshold, **When** evaluated, **Then**
   a BUY signal is emitted.
2. **Given** a trending regime with the same price deviation, **When**
   evaluated, **Then** no signal is produced (prohibited regime).
3. **Given** zero standard deviation (flat prices), **When** evaluated,
   **Then** no signal is produced.
4. **Given** a deviation caused by a feed gap rather than genuine price
   movement, **When** evaluated, **Then** no signal is produced.

---

### User Story 5 - Route Regime to Strategy (Priority: P1)

The system uses an explicitly configured regime-to-strategy map to
dispatch exactly one strategy per pair per decision. The map defaults
to absent (not to any implicit routing). If the map is missing, if
two regimes overlap, or if required features disagree, the system
returns no signal. Strategy strength values are not compared across
strategies.

**Why this priority**: The router is the integration point connecting
regime detection to strategy execution. Incorrect routing or implicit
defaults violate Constitution Principle VII.

**Independent Test**: Configure a regime map, feed ticks that produce
a known regime, verify the correct strategy is dispatched. Remove the
map and verify no signal is produced.

**Acceptance Scenarios**:

1. **Given** regime TRENDING mapped to momentum strategy, **When** the
   regime is TRENDING, **Then** the momentum strategy is dispatched.
2. **Given** no regime map configured, **When** any regime is detected,
   **Then** no signal is produced for any strategy.
3. **Given** a regime not present in the map (e.g., HIGH_VOLATILITY
   with no mapping), **When** that regime is active, **Then** no
   signal is produced.
4. **Given** regime UNSTABLE, **When** even if mapped, **Then** no
   signal is produced (safety override).

---

### User Story 6 - Validate Signal Quality and Emit Recommendation (Priority: P1)

After a strategy produces a signal, the system validates it against
signal-quality thresholds, minimum evidence requirements, and
permitted direction constraints. A valid signal is packaged as a
recommendation with strategy, regime, pair, direction, reference
Bid/Ask, feature snapshot, and timestamp. The recommendation does not
place orders — downstream execution must obtain a fresh quote and
rerun all gates independently.

**Why this priority**: Signal validation is the final quality gate
before a recommendation enters the execution pipeline. An unvalidated
signal reaching execution violates the deterministic pipeline
requirement.

**Independent Test**: Generate a valid strategy signal, then verify
the recommendation payload contains all required fields. Generate a
signal that fails quality thresholds and verify it is suppressed.

**Acceptance Scenarios**:

1. **Given** a valid momentum BUY signal passing all quality checks,
   **When** packaged, **Then** the recommendation includes strategy
   name, regime, pair, direction (BUY), reference Ask price, feature
   snapshot, and timestamp.
2. **Given** a signal below the configured quality threshold, **When**
   validated, **Then** the signal is suppressed with a structured
   reason.
3. **Given** a signal with no configured quality threshold (missing
   parameter), **When** validated, **Then** the signal is suppressed
   (fail-closed).

---

### Edge Cases

- What happens if a regime changes mid-evaluation? The system uses
  the regime at decision time. A regime change on the next tick
  produces a new classification; the prior signal is not retroactively
  invalidated.
- What happens if strategy parameters are changed mid-session? The
  new parameters apply to the next evaluation. No policy for mid-
  position parameter changes exists; this is deferred (§19).
- What happens if all three strategies are inactive (no parameters
  configured)? The system emits no signals for any pair. This is the
  expected default state per TRADING_STRATEGY_DESIGN.md §5.
- What happens if the regime classifier produces rapid flapping between
  two regimes? Hysteresis or confirmation rules may reduce flapping,
  but their exact parameters are unresolved (§19). Without approved
  hysteresis, the system classifies per-tick and accepts the resulting
  switching behavior.
- What happens if a signal is generated but the strategy module calls
  an order API? This is a test violation. The strategy module is
  recommendation-only and must never call order APIs or change
  account/position state.

## Requirements

### Functional Requirements

- **FR-001**: The system MUST classify the market regime for each
  active pair using deterministic, explainable features derived from
  past and current observations only.
- **FR-002**: Possible regime outputs MUST be: TRENDING, RANGING,
  BREAKOUT, HIGH_VOLATILITY, LOW_VOLATILITY, UNSTABLE, or unknown.
  No other regime labels are permitted.
- **FR-003**: Regime classification MUST return unknown when
  insufficient history, ambiguous conditions, degraded data, or
  missing configuration exist.
- **FR-004**: The momentum strategy MUST emit BUY, SELL, or no signal
  based on EMA alignment, price velocity, and momentum strength. EMA
  calculations MUST use mid_price = (Bid + Ask) / 2 as the input
  series. It MUST use Ask as BUY reference and Bid as SELL reference.
- **FR-005**: The breakout strategy MUST emit BUY, SELL, or no signal
  based on a price move beyond a prior channel. The channel MUST
  exclude the candidate observation. Spread-only jumps MUST be
  rejected.
- **FR-006**: The mean reversion strategy MUST emit BUY, SELL, or no
  signal based on deviation from a rolling reference. It MUST NOT
  produce signals in trending, breakout, high-volatility, or unstable
  regimes.
- **FR-007**: Each strategy MUST remain inactive (emit no signal) when
  its structural parameters, thresholds, or eligible regimes are not
  explicitly configured.
- **FR-008**: The regime-to-strategy map MUST default to absent. No
  implicit default may activate any strategy. Missing map = no signal.
- **FR-009**: Exactly one strategy MUST be dispatched per pair per
  decision. Strategy strength values MUST NOT be compared across
  strategies.
- **FR-010**: Every signal recommendation MUST include: strategy name,
  regime, pair, direction, reference Bid/Ask, feature snapshot, and
  timestamp.
- **FR-011**: The strategy module MUST be recommendation-only. It MUST
  NOT place, amend, or close broker orders, calculate authoritative
  position size, or override spread/risk/execution gates.
- **FR-012**: All feature calculations MUST use only past and current
  data at decision time. No look-ahead is permitted.
- **FR-013**: Identical input and configuration MUST produce identical
  outputs (determinism).
- **FR-014**: Signal validation MUST suppress signals that fail quality
  thresholds, minimum evidence requirements, or permitted direction
  constraints. Missing thresholds = fail-closed.
- **FR-015**: Phase 4 signal diagnostics MUST be kept distinct from
  trade-performance claims. No expectancy, profitability, or
  superiority claim without a complete entry, exit, fill, and cost
  model.

### Key Entities

- **Regime**: A classification of the current market state for a pair
  (TRENDING, RANGING, BREAKOUT, HIGH_VOLATILITY, LOW_VOLATILITY,
  UNSTABLE, unknown).
- **Strategy**: An independent signal-generation hypothesis (Momentum,
  Breakout, Mean Reversion) that emits BUY, SELL, or no signal.
- **Regime Map**: An explicit configuration mapping each regime to
  zero or one strategy. Absent by default.
- **Signal Recommendation**: A structured payload containing strategy,
  regime, pair, direction, reference prices, features, and timestamp.
- **Strategy Configuration**: Per-strategy parameters (thresholds,
  lookbacks, EMA spans, etc.) that must be explicitly set for the
  strategy to activate.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Each strategy independently produces correct BUY/SELL/
  no-signal decisions for all synthetic test scenarios with 100%
  deterministic reproducibility.
- **SC-002**: The regime classifier correctly labels all six defined
  regimes plus unknown in synthetic test scenarios.
- **SC-003**: With no parameters configured, the system produces zero
  signals across all test inputs (inactive-by-default verified).
- **SC-004**: The strategy module never calls order APIs or modifies
  account/position state in any test scenario (recommendation-only
  verified).
- **SC-005**: No feature calculation accesses future data in any test
  scenario (look-ahead prevention verified).
- **SC-006**: Regime-to-strategy routing dispatches exactly one
  strategy per pair per decision, and no strategy is dispatched when
  the map is absent or the regime is unmapped.
- **SC-007**: Signal recommendations contain all required fields
  (strategy, regime, pair, direction, reference Bid/Ask, features,
  timestamp) in every test scenario that produces a signal.

## Assumptions

- Phase 4 covers deterministic strategy/regime behavior and its
  unit/property tests. Historical replay, dataset qualification,
  cost-aware performance measurement, and parameter selection belong
  to Phase 7.
- All strategy parameters, thresholds, and regime maps are unresolved
  and require owner approval before activation (TRADING_STRATEGY_
  DESIGN.md §12, master plan §19).
- The strategies are prototypes, not evidence of an edge. No strategy
  is presumed profitable.
- Empty-interval indicator semantics (how to handle time bars with no
  new quotes) are an explicit design choice requiring testing of
  alternatives (TRADING_STRATEGY_DESIGN.md §3.2). Phase 4 documents
  the chosen approach; Phase 7 compares alternatives.
- Regime classification cadence (every tick, fixed-time bar close, or
  slower refresh) is unresolved and must be tested.
- Hysteresis, confirmation rules, and dwell time for regime
  transitions are unresolved (§19). Phase 4 implements the mechanism;
  actual parameters require owner approval.
- Regime classifier thresholds — what dispersion level constitutes
  HIGH_VOLATILITY, what slope/alignment constitutes TRENDING, what
  range exceedance constitutes BREAKOUT, what dispersion constitutes
  LOW_VOLATILITY — are owner-approved parameters (§19 deferred
  decisions). Fail closed (return UNKNOWN) if not configured.
- The warm-up threshold (minimum tick history for valid classification)
  requires owner approval. Fail closed (return UNKNOWN) if not set.
- Cross-pair features are out of scope for the pilot (one pair).
- Exit rules, position management, and trade lifecycle are Phase 5
  concerns. The strategy module emits recommendations only.
