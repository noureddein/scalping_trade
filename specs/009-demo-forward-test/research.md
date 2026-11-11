# Research: Phase 8 — Demo Forward Test

**Date**: 2026-11-10

No NEEDS CLARIFICATION items in the technical context. The primary
unknown (Constitution Principle III gate) is a governance decision,
not a technical research item. Research covers design patterns for
the Demo forward test infrastructure.

## Findings

### EA Order Handler Isolation

- **Decision**: Implement the Demo order handler as a separate MQL5
  file (`DemoOrderHandler.mq5`), not as a modification of the
  existing `ReadOnlyConnector.mq5`. The read-only connector remains
  unchanged and available for non-Demo use. The Demo handler extends
  the connector's functionality with order submission while preserving
  all read-only capabilities.
- **Rationale**: Constitution Principle III requires that the current
  read-only connector is not modified without authorization. A
  separate file keeps the read-only connector intact as a fallback and
  makes the scope of the new code reviewable in isolation.
- **Alternatives considered**: Modifying the existing EA with a
  compile-time flag was rejected — it risks accidentally enabling
  orders in read-only mode if the flag is misconfigured.

### Demo Scope Gate Pattern

- **Decision**: Implement a Demo scope approval as a durable
  PostgreSQL record that must exist before the execution pipeline
  submits any order. The gate checks: approved account ID matches the
  connected account, approved pair matches the requested pair, lot
  size matches, and the current time is within the approved duration.
  Any mismatch blocks the order.
- **Rationale**: FR-001 through FR-004 require explicit scope
  enforcement. A durable record survives restarts and is auditable.
  The gate is checked in the execution pipeline before the broker
  adapter call — it does not replace Phase 5 risk checks but adds
  a Demo-specific authorization layer.
- **Alternatives considered**: Environment variable-based gating was
  rejected — it is not auditable, not durable, and easy to
  misconfigure.

### Complete Evidence Recording

- **Decision**: Extend the existing Phase 5 RiskEvent table with
  additional event types for Demo-specific recording. Add a dedicated
  ForwardTestEvent table for high-frequency events (every signal,
  every spread snapshot at decision time) that would overwhelm the
  RiskEvent table. The evidence log captures every signal generation,
  every entry decision (with reason), every broker request/response,
  and every cost component.
- **Rationale**: FR-009 and FR-010 require 100% event recording with
  no silent drops. The existing RiskEvent table handles risk-related
  events well but lacks granularity for signal-level recording.
  Separating high-frequency events prevents the RiskEvent table from
  growing unbounded during a forward test.
- **Alternatives considered**: Writing all events to a single table
  was rejected — it would mix operational risk events with diagnostic
  signal events, making both harder to query.

### Honest Reporting Pattern

- **Decision**: The forward test report generator includes mandatory
  statistical limitation warnings. For samples below a configurable
  threshold (owner-defined), the report includes "insufficient sample
  size" in bold. No report uses the phrase "positive expectancy"
  without a documented statistical test. Every report ends with:
  "These results do not authorize live trading."
- **Rationale**: FR-011 and FR-012 require honest reporting. The
  master plan explicitly warns against inferring positive expectancy
  from short Demo tests. The mandatory disclaimer prevents
  misinterpretation.
- **Alternatives considered**: Making the disclaimer optional was
  rejected — it would violate Constitution Principle VIII.

### Duration Expiry Handling

- **Decision**: When the approved Demo duration expires, the system
  transitions to a state equivalent to DRAINING: new entries are
  blocked, but open positions continue to be managed (SL/TP remain
  active). The transition is automatic and logged. The system does
  not force-close positions on expiry.
- **Rationale**: FR-013 requires stopping new submissions on expiry.
  Constitution Principle VI prohibits force-closing positions. The
  DRAINING analogy is consistent with the existing Phase 5 state
  machine.
- **Alternatives considered**: Force-closing positions on expiry was
  rejected — it violates the "never force-close" safety invariant.

### Discrepancy Detection

- **Decision**: After each fill, the system compares the actual fill
  price against the expected price (the reference quote at submission
  time). Any difference exceeding one pip is logged as a discrepancy
  with both values. Execution latency (time between submission and
  fill) is recorded for every order. These metrics feed into the
  slippage calibration for Phase 7 backtest refinement.
- **Rationale**: The master plan requires recording "every discrepancy"
  between expected and actual execution. These measurements are the
  first real broker observations and will calibrate the backtest
  slippage model.
- **Alternatives considered**: Ignoring sub-pip discrepancies was
  considered but rejected — even small systematic slippage accumulates
  in scalping and must be measured.
