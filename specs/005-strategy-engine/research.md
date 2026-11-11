# Research: Phase 4 — Strategy Engine

**Date**: 2026-11-10

No NEEDS CLARIFICATION items in the technical context. Research covers
design patterns for the regime classification and strategy framework.

## Findings

### Regime Classification Design

- **Decision**: Implement a priority-ordered classification using
  deterministic features: data/feed instability first, then abnormal/
  high volatility, then confirmed breakout, then trend, then range/
  low volatility, otherwise unknown. This matches TRADING_STRATEGY_
  DESIGN.md §4 recommended evaluation order.
- **Rationale**: Priority ordering prevents the same observation from
  being labeled as both a normal trend and an unstable market. It
  ensures safety-critical conditions (UNSTABLE, HIGH_VOLATILITY) take
  precedence.
- **Alternatives considered**: Parallel multi-label classification
  was rejected — the spec requires exactly one regime per pair per
  decision (FR-009), and the strategy design explicitly prohibits
  overlapping dispatch.

### Strategy Independence

- **Decision**: Each strategy (momentum, breakout, mean reversion) is
  implemented as an independent module with its own configuration,
  feature calculations, and signal generation. No shared mutable
  state between strategies. No cross-strategy strength comparison.
- **Rationale**: TRADING_STRATEGY_DESIGN.md §5 states these are
  "three independent, testable hypotheses." The spec (FR-009) and
  strategy design §6 prohibit cross-strategy strength comparison
  because each computes strength on a different scale.
- **Alternatives considered**: A unified strategy class with mode
  switching was rejected — it would couple the hypotheses and make
  independent testing and future removal harder.

### Inactive-by-Default Enforcement

- **Decision**: Every strategy and the regime-to-strategy map default
  to absent/None. A strategy with any missing parameter (threshold,
  lookback, EMA span) emits no signal. The router with no map emits
  no signal. Configuration validation rejects non-finite, negative
  (where disallowed), or contradictory values.
- **Rationale**: Constitution Principle II (fail-closed) and Principle
  VII (no invented parameters). The strategy design §12 lists 7
  categories of decisions required before activation, all requiring
  owner approval.
- **Alternatives considered**: Providing "research defaults" was
  rejected — the master plan and constitution explicitly prohibit
  invented parameters even for research convenience.

### Feature Calculation: No Look-Ahead

- **Decision**: All feature calculations (EMAs, rolling statistics,
  channel boundaries, deviation measures) use only past and current
  data at the decision timestamp. The breakout channel excludes the
  candidate observation. Rolling windows are observation-indexed for
  the pilot.
- **Rationale**: TRADING_STRATEGY_DESIGN.md §3.2 and spec FR-012
  require strict no-look-ahead. The strategy design explicitly states
  "calculate the reference channel from observations strictly preceding
  the candidate tick/bar."
- **Alternatives considered**: None — this is a hard requirement, not
  a design choice.

### Reference Price Convention

- **Decision**: Use Ask as the BUY reference price and Bid as the
  SELL reference price in signal recommendations. Mid = (Bid + Ask)/2
  is used for direction/indicator calculations only, never as an
  executable price.
- **Rationale**: TRADING_STRATEGY_DESIGN.md §2 step 2 specifies
  this convention. It avoids the common error of generating signals
  at mid-price then executing at a worse Bid/Ask.
- **Alternatives considered**: Mid-price-only signals were rejected
  per the strategy design document's explicit prohibition.

### Signal Payload Structure

- **Decision**: A signal recommendation is a structured payload
  containing: strategy name, regime label, canonical pair, direction
  (BUY/SELL), reference Bid, reference Ask, feature snapshot (dict of
  indicator values at decision time), and decision timestamp.
  Downstream must obtain a fresh quote independently.
- **Rationale**: Spec FR-010 and TRADING_STRATEGY_DESIGN.md §2 step 7
  require all these fields. The fresh-quote requirement prevents
  stale signal prices from being used as execution prices.
- **Alternatives considered**: A minimal signal (just direction) was
  rejected — insufficient for logging, diagnostics, and downstream
  validation.
