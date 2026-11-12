# Replay Harness Contract

**Date**: 2026-11-10

**Scope**: Defines the interface between the replay harness and the
existing Phase 3–5 pipeline. The harness is a tick source adapter —
it replaces the live TCP feed with sequential file reads.

## Replay Execution Sequence

1. Validate gate prerequisites:
   - ApprovedDataSource exists for the requested pair
   - HistoricalDataset loaded and hash verified
   - CostModelConfig exists for the pair
   - Exit policy version is approved (§19#18)
   - If strategy evaluation: AcceptanceCriteria exists (§19#18)
2. Compute and record hashes:
   - Dataset file hash (SHA-256)
   - Source code hash (SHA-256 of relevant modules)
   - Configuration hash (SHA-256 of sorted parameter JSON)
3. Initialize pipeline components:
   - Spread engine (Phase 3) — in replay mode (no live timer)
   - Strategy engine (Phase 4) — with specified config
   - Risk gate (Phase 5) — in replay mode (simulated daily reset)
4. For each tick in chronological order:
   - Set replay clock to tick timestamp
   - Feed tick to spread engine
   - Feed spread result to strategy engine
   - If signal produced: feed to risk gate
   - If entry approved: simulate fill using cost model
   - Record trade outcome
5. Generate report with all required analyses
6. Write TriedConfiguration ledger entry
7. Write BacktestReport

## Determinism Guarantees

The replay engine MUST produce identical output for identical input:

- **No system clock**: All time references use the replay clock
  (derived from tick timestamps).
- **No randomness**: No random number generation, no random
  sampling, no stochastic elements.
- **No floating-point non-determinism**: Operations that produce
  platform-dependent floating-point results (e.g., transcendental
  functions in different orders) must be avoided or pinned.
- **Sorted iteration**: Any iteration over dictionaries or sets
  must use sorted order.
- **Verification**: Two runs of the same input produce bit-for-bit
  identical BacktestReport JSON output.

## Walk-Forward Contract

The walk-forward manager splits a dataset into non-overlapping
chronological periods:

| Period | Purpose | Data Visible |
|--------|---------|-------------|
| Development | Parameter exploration | Only this period's ticks |
| Validation | Early out-of-sample check | Only this period's ticks |
| Test | Final untouched evaluation | Only this period's ticks |

**Rules**:
- Periods are strictly chronological: dev < validation < test.
- No future data leaks into past periods.
- Each period's pipeline state starts fresh (no carried-over
  indicators from previous period).
- Multiple walk-forward windows slide chronologically across the
  dataset.

## Cost Model Contract

Each simulated trade is costed using:

| Component | Source | Double-Count Guard |
|-----------|--------|-------------------|
| Spread | Bid/Ask from tick data at fill time | Not added separately — it's the Bid/Ask gap |
| Commission | CostModelConfig.commission_per_lot | Applied once per round-trip |
| Swap | CostModelConfig.swap_{long,short}_per_lot | Only if held past rollover_time |
| Slippage | CostModelConfig.slippage_scenarios | Applied as scenario, not default |

**Unknown costs**: Reported as sensitivity range with explicit
"unknown" label. Never silently set to zero.

**Break-even friction**: Calculated as diagnostic. Labeled
"diagnostic estimate" in report. Not an acceptance criterion.

## Leakage Check Contract

After each walk-forward run, the leakage checker verifies:

1. The replay engine's tick buffer at any point T contains only
   ticks with timestamp <= T.
2. The strategy's feature snapshot at any point T was computed
   from ticks with timestamp <= T.
3. No global state (module-level variables, cached values) carries
   future information across period boundaries.

**Verification method**: Inject a known future tick into the buffer
at a predetermined point. If the strategy output changes, leakage is
confirmed. If it doesn't change, the check passes.

## Consumer/Producer Obligations

**Replay engine (producer) guarantees**:
- Ticks fed in strict chronological order
- Replay clock matches tick timestamps exactly
- No fabricated quotes for missing intervals
- Missing intervals flagged with quality indicators
- All three hashes frozen before replay begins
- TriedConfiguration entry written for every run

**Pipeline components (consumer) guarantees**:
- Same behavior as live mode (no backtest-special-casing)
- No system clock access (use replay clock only)
- No external I/O during replay (no network, no user input)
- State resets at period boundaries in walk-forward mode
