# Feature Specification: Phase 7 — Backtesting

**Feature Branch**: `008-backtesting`

**Created**: 2026-11-10

**Status**: Draft

**Input**: User description: "Create a specification for the Phase 7: Backtesting"

**Master Plan Reference**: Phase 7 (line 1129), §19#9 (historical data source), §19#16 (sampling basis), §19#18 (reference exit/cost model)

## User Scenarios & Testing

### User Story 1 - Resolve Historical Data Source (Priority: P0)

Before any backtesting can begin, the owner evaluates and approves a
historical tick data source. This includes licensing/usage rights,
broker/pair coverage, Bid/Ask quality (real vs. generated intervals),
missing-period handling, timezone conventions, and acceptable quality
thresholds. No data is procured or purchased until the owner records
approval.

**Why this priority**: §19#9 is a blocking dependency. The master plan
explicitly requires this decision before building the replay harness.
No backtest work can proceed without an approved data source.

**Independent Test**: Present a data source evaluation report to the
owner with quality metrics. Owner reviews and records approval or
rejection.

**Acceptance Scenarios**:

1. **Given** a candidate data source, **When** evaluated, **Then** a
   structured report documents: provider, licensing, pair coverage,
   Bid/Ask availability, interval type (real vs. generated), missing
   period count, timezone, and quality score.
2. **Given** the evaluation report, **When** the owner reviews it,
   **Then** approval or rejection is recorded with rationale.
3. **Given** no approved data source, **When** any backtest is
   attempted, **Then** the system refuses with "no approved data
   source" error.

---

### User Story 2 - Replay Historical Ticks (Priority: P1)

The system replays historical Bid/Ask tick data in strict
chronological order through the same strategy, spread, and risk
pipeline used in live trading. Replay is deterministic — the same
input produces the same output every time. Missing intervals, data
quality flags, and contract specifications are handled explicitly.

**Why this priority**: The replay harness is the foundation for all
backtesting. Without deterministic replay, no strategy evaluation is
meaningful.

**Independent Test**: Feed the same historical dataset twice. Verify
identical signal, entry, and exit sequences both times.

**Acceptance Scenarios**:

1. **Given** an approved historical dataset, **When** replayed,
   **Then** ticks are fed in strict chronological order (oldest first).
2. **Given** a dataset with missing intervals, **When** replayed,
   **Then** missing periods are flagged, not forward-filled with
   fabricated quotes.
3. **Given** the same dataset and configuration, **When** replayed
   twice, **Then** the results are bit-for-bit identical.
4. **Given** a dataset, **When** replayed, **Then** contract
   specifications (point, digits, pip value) match the approved
   source.

---

### User Story 3 - Account for Execution Costs (Priority: P1)

Every backtest accounts for realistic execution costs: Bid/Ask
round-trip spread, commissions, swaps, slippage estimates, stop gaps,
and currency conversion costs. Unknown costs are reported as
sensitivity ranges, never silently set to zero. Double-counting is
prevented.

**Why this priority**: Cost-unaware backtests produce misleading
results. The master plan explicitly requires cost accounting against
a documented benchmark.

**Independent Test**: Run a backtest with known costs. Verify the
reported P/L matches manual calculation including all cost components.

**Acceptance Scenarios**:

1. **Given** a completed backtest trade, **When** P/L is calculated,
   **Then** it includes spread cost, commission, swap (if held
   overnight), and estimated slippage.
2. **Given** an unknown cost component, **When** reported, **Then**
   the report shows a sensitivity range rather than zero.
3. **Given** a trade with known costs, **When** manually verified,
   **Then** no cost is double-counted.
4. **Given** a slippage estimate, **When** reported, **Then** it is
   labeled as a scenario analysis, not a forecast.

---

### User Story 4 - Evaluate Strategies Independently (Priority: P1)

Each strategy (momentum, breakout, mean reversion) and entry variant
is evaluated separately on chronological development, validation, and
untouched test periods using walk-forward windows. A common
owner-approved reference exit policy is used for fair comparison.
Strategies are not compared against each other — each stands alone.

**Why this priority**: Independent evaluation prevents cross-strategy
contamination and ensures each hypothesis is tested on its own merit
with proper out-of-sample discipline.

**Independent Test**: Run each strategy on the same dataset. Verify
each produces an independent report with its own metrics and no
cross-strategy comparisons.

**Acceptance Scenarios**:

1. **Given** a strategy, **When** evaluated, **Then** results are
   reported for separate development, validation, and test periods.
2. **Given** two strategies, **When** both evaluated, **Then** neither
   report references or compares to the other.
3. **Given** walk-forward windows, **When** evaluated, **Then** no
   future data leaks into past windows (no look-ahead).
4. **Given** the exit policy used, **When** checked, **Then** it
   matches the owner-approved reference exit policy, not an invented
   one.

---

### User Story 5 - Detect Data Leakage and Overfitting (Priority: P1)

The system includes leakage checks, a tried-configuration ledger,
parameter sensitivity analysis, benchmark/no-trade comparison,
uncertainty quantification, drawdown analysis, and trade-count
analysis. Dataset and code/config hashes are frozen in each report.

**Why this priority**: Without these safeguards, backtest results are
unreliable and parameter selection is vulnerable to overfitting.

**Independent Test**: Introduce an intentional look-ahead leak.
Verify the leakage check detects and reports it.

**Acceptance Scenarios**:

1. **Given** a backtest run, **When** completed, **Then** the report
   includes dataset hash, code hash, and configuration hash.
2. **Given** a parameter change, **When** re-run, **Then** the
   tried-configuration ledger records the previous and new
   configuration.
3. **Given** a backtest result, **When** reported, **Then** it
   includes a no-trade benchmark comparison showing whether the
   strategy outperforms doing nothing.
4. **Given** a parameter, **When** sensitivity analysis runs, **Then**
   nearby parameter values produce results within a documented range
   (not a cliff edge).

---

### User Story 6 - Define Acceptance Criteria Before Selection (Priority: P0)

The owner defines quantitative acceptance criteria before backtest
results are used to select strategy parameters. Backtest results do
not authorize MT5 Strategy Tester actions, Demo orders, or live
trading.

**Why this priority**: The master plan explicitly requires
pre-defined acceptance criteria to prevent post-hoc rationalization.
This is a governance gate, not a technical feature.

**Independent Test**: Attempt to use backtest results for parameter
selection without recorded acceptance criteria. Verify the system
blocks this.

**Acceptance Scenarios**:

1. **Given** no owner-approved acceptance criteria, **When** parameter
   selection is attempted, **Then** the system refuses.
2. **Given** approved acceptance criteria, **When** a strategy meets
   them, **Then** the result is recorded as "meets criteria" with the
   criteria version hash.
3. **Given** a strategy that meets acceptance criteria, **When**
   reviewed, **Then** the result explicitly states it does not
   authorize Strategy Tester, Demo, or live trading.

---

### User Story 7 - Assess Slippage Sensitivity (Priority: P2)

A slippage sensitivity grid is provided as labeled scenario analysis.
Asymmetric and conditioned slippage is assessed where data permits. A
break-even friction estimate is diagnostic, not a forecast or
acceptance criterion.

**Why this priority**: Slippage is a significant unknown in scalping.
The sensitivity grid helps the owner understand the range of outcomes
without making false precision claims.

**Independent Test**: Run slippage scenarios from 0 to 2x expected.
Verify each is labeled as scenario analysis.

**Acceptance Scenarios**:

1. **Given** a strategy backtest, **When** slippage sensitivity is
   run, **Then** results are labeled "scenario analysis" not
   "expected slippage."
2. **Given** the sensitivity grid, **When** a break-even friction
   point is found, **Then** it is labeled "diagnostic" not
   "acceptance criterion."
3. **Given** data with session-dependent patterns, **When** analyzed,
   **Then** asymmetric slippage per session is reported where data
   supports it.

---

### Edge Cases

- What happens if the historical data contains gaps longer than the
  strategy's lookback window? The replay marks the period as
  "insufficient history" and does not generate signals until the
  lookback window is full again. No fabricated quotes fill the gap.
- What happens if a dataset is modified between runs? The frozen
  dataset hash changes, the tried-configuration ledger flags the run
  as non-comparable with previous runs on the original dataset.
- What happens if the owner-approved exit policy has not been defined?
  The system refuses to run strategy evaluations. The exit policy is a
  blocking dependency (§19#18).
- What happens if a strategy produces zero trades in a test period?
  The report records zero trades with no performance claims. A
  zero-trade result is not a failure — it may indicate the strategy
  correctly rejected all opportunities in that period.
- What happens if the cost model produces negative round-trip costs
  (e.g., rebates)? Cost rebates are included if documented in the
  cost model. The report notes the source and conditions for any
  negative cost component.

## Requirements

### Functional Requirements

- **FR-001**: The system MUST refuse all backtest operations until an
  owner-approved historical data source is recorded (§19#9).
- **FR-002**: The replay harness MUST feed ticks in strict
  chronological order with no reordering.
- **FR-003**: The replay MUST be deterministic — same input and
  configuration produces identical output.
- **FR-004**: Missing intervals MUST be flagged with data-quality
  indicators, not forward-filled with fabricated quotes.
- **FR-005**: Every backtest trade MUST account for Bid/Ask spread,
  commissions, swaps, and estimated slippage. Unknown costs MUST be
  reported as sensitivity ranges, never zero.
- **FR-006**: Each strategy MUST be evaluated independently on
  separate development/validation/test periods.
- **FR-007**: Walk-forward evaluation MUST prevent future data from
  leaking into past windows (no look-ahead).
- **FR-008**: Strategy evaluation MUST use the owner-approved
  reference exit policy. No unapproved ATR multiples or exit rules.
- **FR-009**: Each backtest report MUST include frozen dataset hash,
  code hash, and configuration hash.
- **FR-010**: A tried-configuration ledger MUST record every parameter
  combination that has been tested.
- **FR-011**: Reports MUST include no-trade benchmark comparison,
  parameter sensitivity, uncertainty quantification, drawdown, and
  trade-count analysis.
- **FR-012**: The owner MUST define quantitative acceptance criteria
  before backtest results can be used for parameter selection.
- **FR-013**: Backtest results MUST NOT authorize MT5 Strategy Tester
  actions, Demo orders, or live trading.
- **FR-014**: Slippage sensitivity MUST be labeled as scenario
  analysis, not forecasts or acceptance criteria.
- **FR-015**: Break-even friction estimates MUST be labeled as
  diagnostic, not acceptance criteria.
- **FR-016**: The replay harness MUST use the same strategy, spread,
  and risk pipeline as the live system (no separate backtest-only
  logic).

### Key Entities

- **Historical Dataset**: An approved collection of Bid/Ask tick data
  with provenance, quality metrics, and frozen hash.
- **Backtest Run**: A single deterministic replay of a dataset through
  a strategy with a specific configuration, producing a report.
- **Backtest Report**: Cost-aware results including all required
  analyses (sensitivity, leakage, benchmark, drawdown).
- **Tried-Configuration Ledger**: Immutable record of every parameter
  combination tested, preventing unreported experimentation.
- **Acceptance Criteria**: Owner-defined quantitative thresholds that
  a strategy must meet before parameters are selected.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Two replays of the same dataset and configuration
  produce bit-for-bit identical results in 100% of test cases.
- **SC-002**: Every backtest trade includes all documented cost
  components with no double-counting, verified against manual
  calculation.
- **SC-003**: No future data appears in any past evaluation window
  (verified by leakage check in 100% of walk-forward runs).
- **SC-004**: Every backtest report includes dataset hash, code hash,
  configuration hash, and tried-configuration ledger entry.
- **SC-005**: The system refuses backtest operations when the data
  source is not approved, exit policy is not approved, or acceptance
  criteria are not defined (as applicable per operation).
- **SC-006**: Slippage sensitivity results are labeled "scenario
  analysis" in 100% of reports.
- **SC-007**: Strategy evaluations use the owner-approved reference
  exit policy in 100% of runs.

## Assumptions

- The historical data source decision (§19#9) blocks Phase 7. The
  system can be built and tested with synthetic data, but no
  meaningful strategy evaluation occurs until a real dataset is
  approved.
- The reference exit policy (§19#18) must be approved before strategy
  evaluation runs. The replay harness and cost model can be built
  and tested independently.
- The sampling basis decision (§19#16) must be resolved before
  indicator calculations in replay. The harness itself operates on
  raw ticks regardless of sampling.
- "Deterministic" means no randomness, no system-clock dependency,
  no floating-point non-determinism. The same binary, config, and
  data produce the same output.
- Backtest results are informational. They do not grant any trading
  authorization. Phase 8 (Demo forward test) requires separate
  explicit owner approval.
- The replay harness reuses the existing Phase 3 (spread), Phase 4
  (strategy), and Phase 5 (risk) pipeline components. It does not
  create parallel backtest-only implementations.
- Swap costs are included only for trades that would be held
  overnight in the replay timeline. Scalping trades closed within
  the same session have zero swap.
