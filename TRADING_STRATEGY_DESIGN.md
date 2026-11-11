# Forex Scalping — Trading Strategy Design

**Status:** Design proposal; not approved for trading  
**Scope:** Strategy behavior from validated market data to a recommendation. This document does not implement code, approve parameters, or authorize broker orders.  
**Runtime context:** Python 3.12 backend in WSL; native MT5 on Windows; one EA per pair; start with one Demo pair.  
**Relationship to the plan:** This document expands §7 and the Phase 4/7 test requirements in `FOREX_SCALPING_MASTER_PLAN.md`. The master plan remains canonical for phase status, safety gates, and unresolved owner decisions.

## 1. Purpose and boundaries

Define a deterministic, explainable strategy framework for short-horizon Forex signals using broker Bid/Ask ticks. The strategy layer emits `BUY`, `SELL`, or no signal. It does not place, amend, or close orders; it does not calculate authoritative position size; and it cannot override spread, risk, broker, freshness, or execution gates.

No strategy is presumed profitable. Momentum, breakout, and mean reversion are separate hypotheses to evaluate independently after costs. The existing strategy code is a synthetic-data prototype, not evidence of an edge.

## 2. Proposed decision pipeline

Process each tick for a pair in this order:

1. **Validate feed:** accept only a structurally valid, finite, positive Bid/Ask tick with `ask >= bid`, correct pair mapping, advancing broker timestamp, and fresh local receipt time. Duplicate, reordered, stale, malformed, or gapped data cannot produce a new entry signal.
2. **Construct features:** retain the raw Bid/Ask and timestamp. Use Mid = (Bid + Ask) / 2 for direction/indicator calculations only. Use Ask as a BUY reference and Bid as a SELL reference; both are informational snapshots, never executable prices.
3. **Apply market eligibility:** reject signal generation during unstable feed, disconnected broker, stale contract data, prohibited session/news periods once those policies are approved, excessive spread, insufficient spread stability, or a risk lock.
4. **Classify regime:** classify the current pair state using only observations available at that timestamp. If insufficient history or ambiguous/unstable classification, return no signal.
5. **Select one strategy:** use an explicitly configured regime map. The map defaults to absent; no implicit default may activate. Dispatch to exactly one strategy and do not rank incomparable strategy-strength scores.
6. **Validate signal:** require all strategy-specific conditions, minimum evidence/history, permitted direction, and configured signal-quality threshold. A missing parameter means disabled.
7. **Pass recommendation downstream:** include strategy, regime, pair, direction, reference Bid/Ask, feature snapshot, and timestamp. Downstream execution must obtain a separate fresh quote and rerun all spread/risk/account/reservation checks.

Any failed or unavailable prerequisite produces `NO_TRADE`/`None`, with a structured reason suitable for logs and tests. Existing-position management is a separate permission path; a strategy entry signal never grants permission to close or modify a position.

## 3. Market data and feature conventions

### 3.1 Tick quality

- Keep broker time and local monotonic receipt time distinct.
- Do not interpolate missing live ticks and then treat them as observed market data.
- Track batch sequence gaps, EA ring-buffer overwrites, duplicate batches, and reconnect boundaries. Mark affected intervals as degraded.
- Reset or quarantine rolling indicators after a sufficiently large gap, clock discontinuity, symbol remapping, contract-spec change, or EA run transition. The exact gap policy and threshold require approval and testing.
- One chart/EA feed serves one canonical pair in the pilot. Cross-pair features are out of scope until separately designed.

### 3.2 Time basis and normalization

The current prototype updates indicators per tick. Tick arrival rates vary by pair and session, so a fixed number of ticks does not represent a fixed elapsed time. The prototype EMA is indexed by observations, so its effective elapsed-time horizon changes with quote rate. Rolling standard deviation remains defined over the sampled values, but event-time sampling weights periods with more quote updates more heavily than quiet periods; it is not automatically a clock-time volatility estimate. Before performance evaluation, compare tick-count windows with deterministic time-based aggregation (for example, fixed-duration quote bars); select the basis using out-of-sample evidence. A 5-second interval may be included as an experimental candidate, not an approved baseline. An interval with no new quote is missing/stale input, not a real zero-volume bar; do not forward-fill it as if a new observation arrived. Fixed-time bars are not proof of stationarity. Do not silently mix tick-count, seconds, and bar-count parameters. For OTC Forex feeds, quote-update/tick density is not centralized traded volume; label and use it as quote activity unless the broker explicitly supplies a validated volume measure. Any bar sampling/aggregation rule must state how Bid, Ask, missing intervals, and bar boundaries are handled. Price-event bars (range/volatility/Renko-like) may be compared as a separate research variant, but must preserve wall-clock timestamps and Bid/Ask execution semantics; they do not replace elapsed-time monitoring and may distort holding-time/latency comparisons if evaluated only by bar count.

**Empty-interval indicator semantics are an explicit design choice.** Omitting a scheduled time bar with no new valid quote preserves observed data but makes an N-row window span a variable amount of clock time. Inserting a synthetic flat bar or carrying forward the previous close regularizes the grid but treats an old quote as a new observation. Neither is neutral. Compare and document alternatives such as (a) observation-indexed updates plus a separate elapsed-time/staleness gate, and (b) elapsed-time-aware indicator updates with a clearly defined hold/decay rule. In all cases, stale data blocks new signals immediately; no bar may fabricate a fresh executable quote. Replay tests must assert both indicator behavior and the separate freshness decision across empty intervals.

All price-distance thresholds must declare units and normalization. Raw quote-price units are not portable across pairs with different pip scales. Candidate representations are broker-correct pips or a dimensionless volatility-normalized distance; the project must pick and test one per feature. Convert using the broker contract specification, not a hard-coded pip assumption.

Use only past and current data at decision time. For a breakout, calculate the reference channel from observations strictly preceding the candidate tick/bar. For rolling statistics, define whether the current observation is included; tests must prevent look-ahead and boundary ambiguity.

## 4. Regime model

Regime detection is a gating/classification layer, not a prediction of future returns. Proposed outputs are `TRENDING`, `RANGING`, `BREAKOUT`, `HIGH_VOLATILITY`, `LOW_VOLATILITY`, `UNSTABLE`, or unknown/no classification. Classification cadence (every tick, fixed-time bar close, or a slower refresh) is unresolved and must be tested. The six-state set is a proposal, not a requirement to recompute on every tick. This design does not reset indicator history merely because a regime label changes; any future reset policy needs separate justification and tests.

Candidate features:

- **Trend:** direction and magnitude of a smoothed price slope, normalized by volatility; optionally agreement between short and long EMA slopes.
- **Range:** rolling high-low width and slope near zero, with width normalized by a volatility or price scale.
- **Breakout:** close/quote outside a prior range by a minimum normalized margin, with a tick-gap and spread check.
- **Volatility:** rolling realized dispersion/range compared with an approved pair/session baseline. “High” and “low” boundaries must be calibrated without future data.
- **Unstable:** stale/gapped/out-of-order feed, abrupt volatility/spread excursion, insufficient sample count, inconsistent classification, or invalid contract metadata.

Recommended evaluation order: data/feed instability first; then abnormal/high volatility; then confirmed breakout; then trend; then range/low volatility; otherwise unknown. Priority avoids labeling the same observation as both a normal trend and an unstable market. Exact thresholds, lookbacks, hysteresis, warm-up, and minimum dwell time are unresolved.

Classification should use hysteresis or a confirmation rule if evidence shows rapid regime flapping. A minimum dwell duration/bar count is an optional control to compare, not an approved requirement: it may reduce switching but also delay genuine transitions. Compare zero dwell with candidate dwell ranges under ordinary and abrupt volatility changes; no fixed three-to-five-bar value is approved. Stale/invalid data and `UNSTABLE` conditions must still fail closed immediately; dwell logic must never preserve entry eligibility after a safety gate fails. Any cadence, hysteresis, confirmation, or dwell values must be explicit, logged, and tested. The current implementation's regime formulas and default map are prototypes; no classifier or map is approved for production.

## 5. Candidate strategies

These are three independent, testable hypotheses. Each remains inactive until its structural parameters, thresholds, eligible regimes, and costs are approved. Strength values are strategy-local diagnostics; they are not comparable across strategies.

### 5.1 Momentum continuation

**Hypothesis:** when a sufficiently persistent directional move is present, short-term continuation may exceed round-trip costs and adverse selection.

**Candidate BUY conditions (EMA alignment, not necessarily a crossover event):**

1. Regime is explicitly mapped to momentum and classified as trending.
2. Fast EMA is above slow EMA by an approved normalized minimum.
3. EMA spread is not shrinking beyond a specified rule; positive price velocity exceeds its approved minimum.
4. Tick/feed quality, spread, session, risk, and execution filters all pass.
5. Optional tick-activity confirmation is used only after its definition and data quality are validated.

SELL conditions are symmetric (fast EMA below slow EMA and negative velocity). No entry occurs on equality, insufficient history, zero/invalid elapsed time, or conflicting conditions. Avoid treating high tick count alone as traded volume; tick activity may reflect quote updates rather than executed volume.

**Candidate invalidation/exit research:** thesis reversal (EMA/slope reversal), time-based expiry, and volatility/structure stop are separate exit hypotheses. They must be evaluated independently against fixed protective stops and target rules. No automatic exit rule is selected here.

### 5.2 Range breakout

**Hypothesis:** a confirmed move beyond a prior, sufficiently meaningful range may continue after accounting for spread, slippage, and false breaks.

**Candidate BUY conditions:** current executable-side quote exceeds the prior channel high by the approved normalized breakout margin; the prior channel width meets a minimum meaningful-range criterion; the move is not caused by a spread-only jump; regime is explicitly classified as breakout; and all shared gates pass. SELL uses the prior channel low symmetrically.

The channel must exclude the candidate observation. Use Ask-side highs and Bid-side lows or a rigorously defined mid-price channel; do not mix these definitions silently. Signal generation is not an order price guarantee. Optional momentum confirmation, a breakout-then-retest entry, and false-break filters are research variants, not enabled defaults. Compare immediate confirmation and retest variants with identical data, exit rules, and cost assumptions; do not assert a general false-break frequency without broker/pair/session-specific evidence.

**Candidate invalidation/exit research:** return inside the prior range, structural stop, time expiry, or volatility-adjusted objective. Compare each variant out of sample; the strategy cannot assume that a breakout will continue.

### 5.3 Mean reversion

**Hypothesis:** in a stable, sufficiently range-bound regime, extreme deviation from a rolling reference may revert enough to cover round-trip costs.

**Candidate BUY conditions:** regime is explicitly mapped to mean reversion and is ranging (or another separately approved regime); price is below a rolling mean by an approved standardized deviation; the deviation is not explained by a feed gap, spread jump, or high-volatility event; and all shared gates pass. SELL is symmetric above the mean.

Use a clearly specified rolling mean and dispersion estimator. The current Bollinger-style z-score is a prototype. A high absolute z-score can mean a persistent trend or a regime shift rather than a temporary dislocation; therefore do not fade a move classified as trending, breakout, high-volatility, or unstable. Optional reversal confirmation must be explicit and tested, not inferred from the existence of an extreme reading.

**Candidate invalidation/exit research:** return toward a reference level, thesis invalidation beyond an approved excursion, protective stop, or time expiry. Do not average down, widen stops to accommodate losses, or treat a statistical deviation as guaranteed reversion.

## 6. Strategy routing and conflict rules

Initial research mapping (not approved for activation):

| Regime | Candidate strategy | Default behavior until approved |
|---|---|---|
| TRENDING | Momentum | No signal |
| BREAKOUT | Breakout | No signal |
| RANGING | Mean reversion | No signal |
| LOW_VOLATILITY | Undecided; test no-trade vs range strategy | No signal |
| HIGH_VOLATILITY | None | No signal |
| UNSTABLE / unknown | None | No signal |

Only one strategy is selected for a pair at a decision time. If a regime map is missing, two regimes overlap, required features disagree, or multiple implementations could dispatch, return no signal. Do not resolve disagreement by comparing strategy `strength`, because each existing strategy currently computes it on a different scale.

## 7. Shared entry filters and precedence

The strategy proposes a direction only. The system-wide entry gate must separately verify, in order:

1. Correct account, pair, symbol alias, and contract specification.
2. Fresh, valid, ordered market data and broker connectivity.
3. Pair enabled, session/news policy satisfied when defined, and spread below the approved pair/session limit with required stability.
4. Strategy/regime configuration explicitly active and a valid non-expired signal.
5. No open position, unresolved order, pair reservation, reconciliation/halt barrier, or duplicate request.
6. Daily/account risk state permits a new entry; backend and durable state are available.
7. Fixed lot and broker volume constraints pass; estimated loss (including the approved cost model) is within the intended ceiling. The stated $0.50 is not a guaranteed maximum realized loss.
8. Stop/target distances satisfy broker constraints without widening risk to fit those constraints; margin and exposure limits pass.
9. A fresh quote is obtained immediately before any separately approved execution request; stale signal reference price is never used as a live execution price.

Any failure blocks the entry. Entry denial must not be interpreted as permission to abandon, close, or modify an existing position. Close-management permissions remain a separate unresolved owner policy.

## 8. Risk and trade-management interface

The strategy layer must not own or bypass account-wide risk. It may attach an explanatory invalidation level or proposed thesis expiry for analysis, but Phase 5 risk/execution owns authoritative lot validation, intended-loss calculation, protective-order validation, reservations, broker outcome classification, and durable state.

An intended loss ceiling is an estimate, not a guarantee. Gaps, slippage, commissions, swaps, conversion error, stop rejection, and execution failure can make realized loss larger. If the proposed protective stop cannot satisfy broker minimum distance and the approved risk estimate simultaneously, reject the entry; do not widen the stop automatically.

Exit rules need explicit owner choices for initial SL/TP, adaptive TP, early exit, maximum holding time, trailing behavior, partial fill/close handling, and what actions remain permitted during DRAINING, risk locks, backend outage, or reconciliation. Until those are resolved, this document defines no deployable exit policy.

## 9. Configuration contract

Every active parameter must be explicit, validated, versioned, and included in signal/backtest logs. Missing, non-finite, negative where disallowed, contradictory, or unit-ambiguous values disable the affected strategy. Configuration changes must not silently reset state or apply mid-position without a separately defined policy.

Configuration groups:

- Sampling basis, warm-up and lookback lengths.
- Regime features, thresholds, hysteresis, and mapping.
- Strategy thresholds and confirmation rules.
- Per-pair spread/freshness/session/news filters.
- Exit/holding policies (currently unresolved).
- Cost model: spread, commission, swap, slippage, rejected/partial execution, and currency conversion.

For every run, preserve source revision, parameter/config hash, pair/broker, contract metadata, data-source and tick-quality summary, date range, time zone, and random seed if any stochastic component is introduced.

## 10. Research and validation protocol

1. Freeze a trustworthy historical Bid/Ask tick dataset for the target broker/account type, pair, and contract specification. Document missing periods, generated-vs-real tick coverage, timezone, and source changes.
2. Implement deterministic replay that processes ticks chronologically and reproduces the same decisions from the same data/configuration.
3. Define market-order fill assumptions using Ask for BUY entry and Bid for SELL entry; reverse sides for closing. Include round-trip spread, commission, swap when held across rollover, slippage, latency, rejected requests, stop gaps, and conversion costs. Define the benchmark (usually mid-price) and calculate each cost once: if fill-side prices already include Bid/Ask, do not add the same spread again; treat latency-induced adverse movement as part of measured slippage unless a separate, non-overlapping definition is justified. If an input is unknown, report sensitivity/scenarios rather than silently set it to zero.
4. Split chronologically into development, validation, and untouched test periods. Include walk-forward evaluation. Never select parameters using the final test segment.
5. Test each strategy alone and against a no-trade/baseline policy. Entry-signal diagnostics may be measured before an exit rule is approved, but do not report trade expectancy, profitability, or strategy superiority without a fully specified entry, exit, fill, and cost model. For a complete strategy comparison, freeze the same approved reference exit policy across candidates first; evaluate alternate exits separately. Only test a hybrid after each component has independent evidence. Record every configuration tried to expose selection bias.
6. Report net expectancy per trade, profit factor, drawdown, win/loss distribution, exposure, holding-time distribution, turnover, trades per session, spread/commission/slippage breakdown, rejects, and uncertainty. Include a simple baseline and adverse-cost scenarios. Do not impose a generic fixed slippage floor or latency penalty without evidence; calibrate scenarios from recorded broker/session observations where possible, otherwise label them as sensitivity assumptions and show a range. A slippage sensitivity grid (such as 0.0–1.0 pip by 0.1) may illustrate break-even sensitivity, but remains an illustrative assumption until calibrated and is not an acceptance criterion. Also test asymmetric or volatility/spread-conditioned slippage if the data supports it. Avoid double counting latency-induced price movement as both slippage and a separate latency charge. A maximum tolerable friction estimate is a diagnostic for the specified dataset/model, not a forecast or standalone approval.
7. Run sensitivity analysis around each chosen parameter, across sessions and representative volatility/spread regimes. A narrow optimum or major degradation under small perturbations is a warning, not a robust result.
8. Review out-of-sample results and data quality independently. Backtest results do not guarantee future performance and do not authorize Demo or live orders.
9. Define quantitative acceptance criteria before comparing final results; positive net expectancy under one arbitrarily chosen stress scenario is not sufficient by itself. Assess uncertainty, trade count, drawdown, sensitivity, execution quality, and stability across periods. Only after approval, run a separately scoped Demo forward-test protocol. Record expected-vs-observed fills, costs, signal timing, feed gaps, and operational failures. Do not enable live trading by implication.

MT5 Strategy Tester can use real historical ticks, but MetaQuotes documents that missing tick intervals may be generated from minute data in real-tick mode. Record actual tick-history quality and substitutions; a “real ticks” mode label alone does not prove complete real-tick coverage. See the official documentation below.

## 11. Required strategy tests

### Unit and property tests

- Default construction of every config emits no regime and no signal.
- Missing map, missing threshold, invalid unit, or invalid numeric value fails closed.
- Exact threshold boundary, just-below, and just-above cases for every signal condition.
- Insufficient warm-up, zero variance, zero/negative elapsed time, duplicate timestamp, out-of-order tick, gap, NaN/infinity, crossed/invalid quotes, and contract change.
- Empty fixed-time intervals: assert the chosen observation/elapsed-time update semantics, report actual rolling-window duration, and ensure stale intervals cannot produce a fresh signal or executable quote.
- EMA ordering and direction symmetry; no BUY on non-positive spread and no SELL on non-negative spread.
- Breakout channel excludes current candidate tick; both directions; exact channel boundary; spread-only apparent breakout rejection.
- Mean-reversion direction symmetry; no fade during prohibited regimes; zero standard deviation and persistent trend cases.
- Regime priority, hysteresis, unknown-state behavior, and no rapid flapping at boundaries.
- Pair isolation, EA run transition, data freshness, and no cross-pair state leakage.
- Signal payload identity/timestamp/reference-side; downstream fresh quote is independently required.
- Identical input/config gives identical outputs and logs; feature calculation has no future-data access.
- No signal strategy path calls order APIs or changes account/position state.

### Replay/backtest validation

- Golden replay fixtures for each strategy and regime; deterministic output hashes.
- Bid/Ask side correctness for entry and exit; variable spread; commission, swap, slippage, latency, gaps, requotes/rejections, and stop execution assumptions.
- Missing/synthesized tick interval detection and report; no silent replacement of missing data.
- Chronological splits, look-ahead/leakage checks, walk-forward windows, tried-configuration ledger, and parameter perturbation tests.
- Reproducibility from frozen source/config/data hashes; full cost reconciliation against each trade record.
- Baseline comparison, adverse execution assumptions, and uncertainty reporting.

### Safety and operational tests

- Broker/backend/database outage, stale feed, halted barrier, risk lock, pair reservation, unresolved order, and startup reconciliation all suppress new entries.
- Strategy module remains recommendation-only; any future execution path must pass the distinct risk and execution gates.
- No automated test may submit a real broker order. Strategy Tester or broker-connected mutation requires separate explicit owner approval.

## 12. Decisions required before activation

This document intentionally does not set profitable parameters. Owner approval and evidence are required for:

1. Whether the project tests the three hypotheses at all, and which one is the first pilot.
2. Sampling basis (ticks vs time bars vs price-event bars), lookbacks, EMA spans, breakout channel, mean/dispersion estimator, and all thresholds with units.
3. Regime feature definitions, classification cadence/priority, hysteresis or dwell/confirmation behavior, warm-up, and regime-to-strategy map.
4. Per-pair and session spread limits, spread-stability requirements, trading sessions, and news blackout policy.
5. A reference exit policy for fair strategy comparison, then initial stop/target, time stop, early exit, trailing, and position-management rules. ATR-based SL/TP is one research candidate, not selected; multipliers such as a 1.5×ATR stop and 1.0×ATR target are unapproved examples and must not be used as the benchmark without explicit approval. Every candidate must satisfy the intended-loss and broker-distance constraints and include full costs; a stop/target ratio alone does not establish positive expectancy.
6. Broker/account-specific costs, USD conversion source/freshness, slippage assumptions, margin/exposure limits, and partial-fill behavior.
7. Historical data source, acceptable quality/coverage, test windows, and quantitative acceptance criteria.

Until these choices are made and independently validated, keep all strategies inactive and the system read-only.

## 13. References

- MetaQuotes, [Testing trading strategies — MQL5 Reference](https://www.mql5.com/en/docs/runtime/testing): tick generation modes, spread simulation, real ticks, and historical-data behavior. Real-tick testing may substitute generated ticks where real tick history is missing.
- Bailey et al., [The Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253): motivation for recording configurations tried and preserving an untouched evaluation sample. This is a methodological reference, not validation of this project's strategies.

