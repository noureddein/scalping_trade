# Tasks: Phase 7 — Backtesting

**Input**: Design documents from `specs/008-backtesting/`

**Prerequisites**: plan.md, spec.md, data-model.md, contracts/replay-harness.md, research.md, quickstart.md

**Note**: Phase 7 builds a deterministic tick-replay harness that feeds historical data through the
existing Phase 3–5 pipeline (spread, strategy, risk) with full cost accounting. Three §19 decisions
are blocking gates: #9 (data source), #16 (sampling basis), #18 (exit/cost model). The harness
reuses live pipeline components — no parallel backtest-only implementations.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US7)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: Backtest package structure, shared types, and database migration

- [ ] T001 Create the backtest subpackage directory at src/scalping/backtest/ with __init__.py
- [ ] T002 Create migration 008 in migrations/008_backtest_tables.sql adding tables: approved_data_source (source_id uuid PK, provider string NOT NULL, pair string FK NOT NULL, interval_type string "real_tick"/"generated" NOT NULL, timezone string IANA NOT NULL, quality_score decimal NOT NULL, licensing_notes string NOT NULL, approval_date date NOT NULL, approval_notes string NOT NULL, approved_by string NOT NULL), historical_dataset (dataset_id uuid PK, source_id uuid FK NOT NULL, file_path string NOT NULL, file_hash string SHA-256 NOT NULL UNIQUE, pair string FK NOT NULL, start_time timestamp NOT NULL, end_time timestamp NOT NULL, tick_count integer NOT NULL, missing_intervals integer NOT NULL, quality_flags string JSON NOT NULL, loaded_at timestamp NOT NULL), backtest_run (run_id uuid PK, dataset_id uuid FK NOT NULL, strategy_name string NOT NULL, configuration_hash string NOT NULL, code_hash string NOT NULL, exit_policy_version string NOT NULL, window_type string "full"/"development"/"validation"/"test" NOT NULL, window_start timestamp NOT NULL, window_end timestamp NOT NULL, total_trades integer NOT NULL, net_pnl decimal NOT NULL, gross_pnl decimal NOT NULL, total_costs decimal NOT NULL, max_drawdown decimal NOT NULL, started_at timestamp NOT NULL, completed_at timestamp NOT NULL, report_path string NOT NULL), tried_configuration (entry_id uuid PK, run_id uuid FK NOT NULL, dataset_hash string NOT NULL, code_hash string NOT NULL, configuration_hash string NOT NULL, configuration_json string NOT NULL, strategy_name string NOT NULL, summary_result string JSON NOT NULL, created_at timestamp NOT NULL — INSERT only, no UPDATE/DELETE), acceptance_criteria (criteria_id uuid PK, criteria_version string NOT NULL UNIQUE, criteria_hash string SHA-256 NOT NULL, criteria_json string NOT NULL, approved_date date NOT NULL, approved_by string NOT NULL, notes string nullable), cost_model_config (config_id uuid PK, pair string FK NOT NULL, commission_per_lot decimal NOT NULL, swap_long_per_lot decimal NOT NULL, swap_short_per_lot decimal NOT NULL, rollover_time time NOT NULL, slippage_scenarios string JSON array of {label, pips} NOT NULL, source_notes string NOT NULL, approved_by string nullable), backtest_report (report_id uuid PK, run_id uuid FK NOT NULL UNIQUE, dataset_hash string NOT NULL, code_hash string NOT NULL, configuration_hash string NOT NULL, no_trade_benchmark_pnl decimal NOT NULL, parameter_sensitivity string JSON NOT NULL, uncertainty_range string JSON NOT NULL, drawdown_analysis string JSON NOT NULL, trade_count_analysis string JSON NOT NULL, slippage_sensitivity string JSON nullable, leakage_check_passed boolean NOT NULL, meets_acceptance_criteria boolean nullable, criteria_version string FK nullable, generated_at timestamp NOT NULL)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Dataset loading/hashing and gate validation that all stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T003 Implement dataset loading and hashing in src/scalping/backtest/dataset.py: load historical tick data file, compute SHA-256 file hash, validate tick structure (pair, bid, ask, timestamp), count total ticks, detect missing intervals (gaps), generate quality_flags JSON array. Store HistoricalDataset record in PostgreSQL. Verify hash on reload matches stored hash (reject on mismatch). Ticks MUST have Bid/Ask (not mid-price only)
- [ ] T004 Implement gate prerequisite validation in src/scalping/backtest/replay.py: before any backtest operation, check all gates per contracts/replay-harness.md — ApprovedDataSource exists for pair (FR-001), HistoricalDataset loaded and hash verified, CostModelConfig exists for pair, exit_policy_version is approved (§19#18 — refuse if not approved). For strategy evaluation: AcceptanceCriteria exists (FR-012). Return structured error identifying which gate failed
- [ ] T005 [P] Implement hash computation utilities in src/scalping/backtest/dataset.py: SHA-256 for dataset file (raw bytes), SHA-256 for source code (hash of sorted relevant module paths), SHA-256 for configuration (sorted JSON of all parameters). All three hashes frozen before replay begins (FR-009)

**Checkpoint**: Dataset loading, hashing, and gate validation ready — replay can proceed

---

## Phase 3: User Story 1 — Resolve Historical Data Source (Priority: P0) 🎯 MVP

**Goal**: Evaluate and record approval of a historical tick data source (§19#9 blocking gate)

**Independent Test**: Generate evaluation report for a candidate source → owner reviews → approval/rejection recorded

- [ ] T006 [US1] Implement data source evaluation in src/scalping/backtest/dataset.py: accept a candidate data file path + metadata, produce structured evaluation report with fields: provider, licensing, pair coverage, Bid/Ask availability (real vs generated), interval type, missing period count, timezone, quality score. Report stored as ApprovedDataSource record only after owner approval is recorded
- [ ] T007 [US1] Implement data source gate enforcement in src/scalping/backtest/dataset.py: when no ApprovedDataSource exists for a pair, refuse all backtest operations with "no approved data source" error (FR-001, SC-005). Gate check called from replay.py prerequisite validation (T004)
- [ ] T008 [US1] Write unit tests in tests/test_dataset.py: test evaluation report contains all required fields, test gate refusal when no approved source, test gate passes when approved source exists, test approval recording stores all metadata

**Checkpoint**: Data source evaluation and gate enforcement operational

---

## Phase 4: User Story 6 — Define Acceptance Criteria Before Selection (Priority: P0)

**Goal**: Owner-defined quantitative criteria gate parameter selection; no post-hoc rationalization

**Independent Test**: Attempt parameter selection without criteria → system refuses; define criteria → selection allowed

- [ ] T009 [US6] Implement acceptance criteria management in src/scalping/backtest/ledger.py: store AcceptanceCriteria records in PostgreSQL — criteria_version (semantic version, UNIQUE), criteria_hash (SHA-256 of criteria JSON), criteria_json (structured definitions), approved_date, approved_by. Gate: refuse parameter selection when no AcceptanceCriteria exists (FR-012, SC-005). When strategy meets criteria, record "meets criteria" with criteria_version hash. Result MUST explicitly state it does not authorize Strategy Tester, Demo, or live trading (FR-013)
- [ ] T010 [US6] Write unit tests in tests/test_ledger.py: test system refuses parameter selection without criteria (SC-005), test "meets criteria" recorded with version hash when met, test result states no authorization for Strategy Tester/Demo/live, test criteria_version uniqueness enforced

**Checkpoint**: Acceptance criteria gate enforced; no parameter selection without pre-defined criteria

---

## Phase 5: User Story 2 — Replay Historical Ticks (Priority: P1)

**Goal**: Deterministic chronological replay through existing Phase 3–5 pipeline; identical input = identical output

**Independent Test**: Feed same dataset twice → verify bit-for-bit identical signal/entry/exit sequences

- [ ] T011 [US2] Implement deterministic replay engine in src/scalping/backtest/replay.py: feed ticks in strict chronological order (oldest first, FR-002). Replace system clock with replay clock derived from tick timestamps (no system-clock dependency). No randomness, no stochastic elements. Sorted iteration over all dicts/sets. Initialize Phase 3 spread engine (replay mode, no live timer), Phase 4 strategy engine (specified config), Phase 5 risk gate (replay mode, simulated daily reset) per contracts/replay-harness.md. For each tick: set replay clock → feed to spread → feed to strategy → if signal → feed to risk gate → if approved → simulate fill. Record trade outcome
- [ ] T012 [US2] Implement missing interval handling in src/scalping/backtest/replay.py: flag missing periods with data-quality indicators (FR-004). Never forward-fill with fabricated quotes. When gap exceeds strategy lookback window, mark period as "insufficient history" and suppress signal generation until lookback window refills. Contract specifications (point, digits, pip value) must match the approved data source
- [ ] T013 [US2] Write unit tests in tests/test_replay.py: test strict chronological tick ordering (SC-001), test determinism — two runs produce bit-for-bit identical output (SC-001), test missing intervals flagged not filled (FR-004), test no system clock usage (replay clock only), test pipeline components receive ticks in correct order, test gap longer than lookback window suppresses signals

**Checkpoint**: Replay engine produces deterministic results through live pipeline

---

## Phase 6: User Story 3 — Account for Execution Costs (Priority: P1)

**Goal**: Full cost accounting per trade: spread, commission, swap, slippage; unknown costs as sensitivity ranges

**Independent Test**: Run backtest with known costs → verify P/L matches manual calculation including all components

- [ ] T014 [P] [US3] Implement cost model in src/scalping/backtest/cost_model.py: for each simulated trade calculate: spread cost (Bid/Ask gap at fill time — not added separately, it IS the gap per cost model contract), commission (CostModelConfig.commission_per_lot, applied once per round-trip), swap (swap_{long,short}_per_lot only if held past rollover_time — scalping trades closed same session have zero swap), slippage (from CostModelConfig.slippage_scenarios, applied as scenario not default). Unknown costs reported as sensitivity range with "unknown" label, never silently zero (FR-005). Prevent double-counting: spread is the Bid/Ask gap not an additive fee
- [ ] T015 [P] [US3] Write unit tests in tests/test_cost_model.py: test all cost components included in P/L (SC-002), test no double-counting (spread is gap not additive), test unknown costs as sensitivity range not zero, test swap zero for same-session trades, test swap applied for overnight holds past rollover_time, test manual calculation match, test negative costs (rebates) included if documented in config

**Checkpoint**: Cost model produces accurate, verifiable P/L with no double-counting

---

## Phase 7: User Story 4 — Evaluate Strategies Independently (Priority: P1)

**Goal**: Each strategy evaluated separately on dev/validation/test periods with walk-forward; owner-approved exit policy

**Independent Test**: Run each strategy on same dataset → verify independent reports with no cross-strategy comparisons

- [ ] T016 [US4] Implement walk-forward window manager in src/scalping/backtest/walk_forward.py: split dataset into non-overlapping chronological periods — development, validation, test (contracts/replay-harness.md). Periods strictly chronological: dev < validation < test. Each period's pipeline state starts fresh (no carried-over indicators). Multiple walk-forward windows slide chronologically across dataset. No future data leaks into past windows (FR-007, SC-003)
- [ ] T017 [US4] Implement independent strategy evaluation in src/scalping/backtest/replay.py: evaluate each strategy (momentum, breakout, meanrev) independently on separate dev/validation/test periods (FR-006). Use owner-approved reference exit policy — refuse to run if exit policy not approved (§19#18, FR-008, SC-007). Reports MUST NOT reference or compare other strategies. Neither report references or compares to the other (acceptance scenario US4-2)
- [ ] T018 [US4] Write unit tests in tests/test_walk_forward.py: test periods are strictly chronological (SC-003), test no data leakage across period boundaries, test pipeline state resets at period boundaries, test multiple walk-forward windows slide correctly, test refusal without approved exit policy (SC-005/SC-007)

**Checkpoint**: Strategies evaluated independently with walk-forward discipline

---

## Phase 8: User Story 5 — Detect Data Leakage and Overfitting (Priority: P1)

**Goal**: Leakage checks, tried-config ledger, sensitivity analysis, benchmark comparison, frozen hashes per report

**Independent Test**: Inject intentional look-ahead leak → verify detection and reporting

- [ ] T019 [US5] Implement leakage detection in src/scalping/backtest/leakage.py: after each walk-forward run verify per contracts/replay-harness.md — (1) replay tick buffer at time T contains only ticks with timestamp <= T, (2) strategy feature snapshot at time T computed only from ticks <= T, (3) no global state carries future information across period boundaries. Verification method: inject known future tick; if strategy output changes, leakage confirmed. Report leakage_check_passed boolean (SC-003)
- [ ] T020 [US5] Implement tried-configuration ledger in src/scalping/backtest/ledger.py: append-only record of every parameter combination tested (FR-010). Fields: entry_id, run_id, dataset_hash, code_hash, configuration_hash, configuration_json (full param set), strategy_name, summary_result (JSON: trades, P/L, drawdown), created_at. INSERT only — no UPDATE or DELETE at application level. When dataset modified between runs, hash change flags run as non-comparable with previous runs
- [ ] T021 [US5] Implement report generation in src/scalping/backtest/report.py: generate BacktestReport with all required analyses (FR-011) — no-trade benchmark comparison (P/L from doing nothing), parameter sensitivity (nearby values produce results within documented range, not cliff edge), uncertainty quantification (confidence intervals), drawdown analysis (max peak-to-trough), trade-count analysis (frequency details). Include frozen dataset hash, code hash, configuration hash (FR-009, SC-004). Zero-trade result recorded with no performance claims
- [ ] T022 [US5] Write unit tests in tests/test_leakage.py: test leakage detection catches injected future tick, test clean run passes leakage check, test global state doesn't carry across period boundaries
- [ ] T023 [US5] Write unit tests in tests/test_report.py: test report includes all three hashes (SC-004), test no-trade benchmark included (FR-011), test parameter sensitivity included, test ledger entry created for every run (FR-010), test zero-trade result has no performance claims

**Checkpoint**: Leakage detection, tried-config ledger, and full reporting operational

---

## Phase 9: User Story 7 — Assess Slippage Sensitivity (Priority: P2)

**Goal**: Slippage sensitivity grid labeled as scenario analysis; break-even friction as diagnostic

**Independent Test**: Run slippage scenarios 0 to 2x expected → verify each labeled "scenario analysis"

- [ ] T024 [US7] Implement slippage sensitivity grid in src/scalping/backtest/slippage.py: generate grid of slippage scenarios from CostModelConfig.slippage_scenarios (JSON array of {label, pips}). Run each scenario against the backtest results. All results MUST be labeled "scenario analysis" not "expected slippage" (FR-014, SC-006). Calculate break-even friction point — label as "diagnostic estimate" not "acceptance criterion" (FR-015). Where data supports it, report asymmetric slippage per session
- [ ] T025 [US7] Write unit tests in tests/test_report.py: test slippage results labeled "scenario analysis" (SC-006), test break-even labeled "diagnostic" not "acceptance criterion" (FR-015), test multiple scenarios in grid, test asymmetric slippage reported where data permits

**Checkpoint**: Slippage sensitivity provides scenario analysis without false precision

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: End-to-end pipeline integration, determinism verification, cross-cutting validation

- [ ] T026 Wire full backtest pipeline in src/scalping/backtest/replay.py: gate validation → hash computation → pipeline init → chronological replay → cost accounting → report generation → ledger entry. Ensure the pipeline reuses existing Phase 3/4/5 components with no backtest-only logic (FR-016). Pipeline components must not access system clock or external I/O during replay
- [ ] T027 Write integration tests in tests/test_replay.py: test full pipeline end-to-end with synthetic data, test determinism across full pipeline (two runs identical, SC-001), test all gates enforced (no data source → refused, no exit policy → refused, no criteria for selection → refused), test pipeline uses live components not backtest-special-cased versions (FR-016)
- [ ] T028 Run quickstart.md validation scenarios end-to-end and record PASS/FAIL evidence

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — T001/T002 can start immediately
- **Foundational (Phase 2)**: Depends on Setup — T003–T005 need package structure and tables
- **US1 (Phase 3)**: Depends on Foundational (dataset loading, gate validation)
- **US6 (Phase 4)**: Depends on Foundational only (acceptance criteria is an independent gate)
- **US2 (Phase 5)**: Depends on US1 (needs approved data source) and Foundational
- **US3 (Phase 6)**: Can run in parallel with US2 (cost model is independent, different file)
- **US4 (Phase 7)**: Depends on US2 (walk-forward needs replay engine)
- **US5 (Phase 8)**: Depends on US2 and US4 (leakage checks need walk-forward runs)
- **US7 (Phase 9)**: Depends on US3 (slippage grid needs cost model)
- **Polish (Phase 10)**: Depends on all user stories

### User Story Dependencies

- **US1 (P0)**: No dependencies on other stories — data source gate is foundational
- **US6 (P0)**: No dependencies on other stories — acceptance criteria gate is independent
- **US2 (P1)**: Depends on US1 (needs approved data source to replay)
- **US3 (P1)**: Depends on Foundational only (cost model is independent)
- **US4 (P1)**: Depends on US2 (walk-forward runs through replay engine)
- **US5 (P1)**: Depends on US2 + US4 (leakage/reporting need replay + walk-forward)
- **US7 (P2)**: Depends on US3 (slippage grid uses cost model scenarios)

### Parallel Opportunities

- US1 and US6 can run in parallel (both P0, independent gates)
- US3 (cost model) can run in parallel with US2 (replay engine) — different files
- T005 (hash utilities) can run in parallel with T003/T004
- T014/T015 (cost model) can run in parallel with T011–T013 (replay)

---

## Parallel Example: P0 Gates + Cost Model

```bash
# After Foundational, start P0 gates in parallel:
# US1: T006-T008 (data source evaluation — dataset.py)
# US6: T009-T010 (acceptance criteria — ledger.py)

# After US1, start replay + cost model in parallel:
# US2: T011-T013 (replay engine — replay.py)
# US3: T014-T015 (cost model — cost_model.py, different file)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete T001–T002 (Setup: package + migration)
2. Complete T003–T005 (Foundational: dataset loading + gates + hashing)
3. Complete T006–T008 (US1: data source evaluation and gate)
4. **STOP and VALIDATE**: Owner can evaluate and approve a data source; system refuses without it
5. Proceed to US6, then US2–US7

### Incremental Delivery

1. Setup + Foundational → package, tables, dataset loading, gates, hashing ready
2. US1 + US6 (parallel: T006–T010) → data source and acceptance criteria gates
3. US2 + US3 (parallel: T011–T015) → replay engine + cost model
4. US4 (T016–T018) → walk-forward evaluation
5. US5 (T019–T023) → leakage detection, ledger, reporting
6. US7 (T024–T025) → slippage sensitivity grid
7. Polish (T026–T028) → end-to-end pipeline, determinism verification

---

## Notes

- Three §19 decisions are blocking gates: #9 (data source), #16 (sampling basis), #18 (exit/cost model)
- System can be built and tested with synthetic data; real evaluation requires §19#9 approval
- Replay harness reuses Phase 3/4/5 pipeline — no backtest-only parallel implementations (FR-016)
- TriedConfiguration ledger is append-only: INSERT only, no UPDATE or DELETE
- Backtest results are informational — they do NOT authorize Strategy Tester, Demo, or live trading (FR-013)
- "Deterministic" means no randomness, no system clock, no floating-point non-determinism
- All hashes are SHA-256: dataset (raw file bytes), code (relevant modules), configuration (sorted JSON)
- Swap costs only for overnight holds past rollover_time; same-session scalping trades have zero swap
