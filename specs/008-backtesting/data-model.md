# Data Model: Phase 7 — Backtesting

**Date**: 2026-11-10

## Entities

### ApprovedDataSource

Owner-approved historical data source record. Gate entity — must
exist before any backtest runs.

| Field | Type | Constraints |
|-------|------|-------------|
| source_id | uuid | PK |
| provider | string | Data provider name; NOT NULL |
| pair | string | Canonical pair name (e.g. EURUSD); NOT NULL |
| interval_type | string | "real_tick" or "generated"; NOT NULL |
| timezone | string | IANA timezone of timestamps; NOT NULL |
| quality_score | decimal | Owner-assessed quality metric; NOT NULL |
| licensing_notes | string | Usage rights summary; NOT NULL |
| approval_date | date | When owner approved; NOT NULL |
| approval_notes | string | Owner rationale; NOT NULL |
| approved_by | string | Owner identifier; NOT NULL |

### HistoricalDataset

A specific file of historical tick data with frozen hash.

| Field | Type | Constraints |
|-------|------|-------------|
| dataset_id | uuid | PK |
| source_id | uuid | FK to ApprovedDataSource; NOT NULL |
| file_path | string | Path to tick data file; NOT NULL |
| file_hash | string | SHA-256 of file contents; NOT NULL; UNIQUE |
| pair | string | Canonical pair name; NOT NULL |
| start_time | timestamp | First tick timestamp; NOT NULL |
| end_time | timestamp | Last tick timestamp; NOT NULL |
| tick_count | integer | Total ticks in file; NOT NULL |
| missing_intervals | integer | Count of detected gaps; NOT NULL |
| quality_flags | string | JSON array of quality issues; NOT NULL |
| loaded_at | timestamp | When imported; NOT NULL |

### BacktestRun

A single deterministic replay execution.

| Field | Type | Constraints |
|-------|------|-------------|
| run_id | uuid | PK |
| dataset_id | uuid | FK to HistoricalDataset; NOT NULL |
| strategy_name | string | Which strategy was evaluated; NOT NULL |
| configuration_hash | string | SHA-256 of sorted config JSON; NOT NULL |
| code_hash | string | SHA-256 of relevant source modules; NOT NULL |
| exit_policy_version | string | Approved exit policy identifier; NOT NULL |
| window_type | string | "full", "development", "validation", "test"; NOT NULL |
| window_start | timestamp | Period start; NOT NULL |
| window_end | timestamp | Period end; NOT NULL |
| total_trades | integer | Number of trades in this window; NOT NULL |
| net_pnl | decimal | After all costs; NOT NULL |
| gross_pnl | decimal | Before costs; NOT NULL |
| total_costs | decimal | Sum of all cost components; NOT NULL |
| max_drawdown | decimal | Maximum peak-to-trough; NOT NULL |
| started_at | timestamp | When run began; NOT NULL |
| completed_at | timestamp | When run finished; NOT NULL |
| report_path | string | Path to full report file; NOT NULL |

### TriedConfiguration

Append-only ledger of every parameter combination tested.

| Field | Type | Constraints |
|-------|------|-------------|
| entry_id | uuid | PK |
| run_id | uuid | FK to BacktestRun; NOT NULL |
| dataset_hash | string | From HistoricalDataset; NOT NULL |
| code_hash | string | NOT NULL |
| configuration_hash | string | NOT NULL |
| configuration_json | string | Full parameter set as JSON; NOT NULL |
| strategy_name | string | NOT NULL |
| summary_result | string | JSON summary (trades, P/L, drawdown); NOT NULL |
| created_at | timestamp | NOT NULL |

**Constraint**: Insert-only — no UPDATE or DELETE permitted at
application level.

### AcceptanceCriteria

Owner-defined quantitative thresholds. Gate entity — must exist
before parameter selection.

| Field | Type | Constraints |
|-------|------|-------------|
| criteria_id | uuid | PK |
| criteria_version | string | Semantic version; NOT NULL; UNIQUE |
| criteria_hash | string | SHA-256 of criteria JSON; NOT NULL |
| criteria_json | string | Structured criteria definitions; NOT NULL |
| approved_date | date | When owner approved; NOT NULL |
| approved_by | string | Owner identifier; NOT NULL |
| notes | string | Owner rationale; nullable |

### CostModelConfig

Configuration for execution cost accounting per pair/broker.

| Field | Type | Constraints |
|-------|------|-------------|
| config_id | uuid | PK |
| pair | string | Canonical pair name; NOT NULL |
| commission_per_lot | decimal | NOT NULL |
| swap_long_per_lot | decimal | Per overnight hold; NOT NULL |
| swap_short_per_lot | decimal | Per overnight hold; NOT NULL |
| rollover_time | time | When swap is charged; NOT NULL |
| slippage_scenarios | string | JSON array of {label, pips} entries; NOT NULL |
| source_notes | string | Where these values came from; NOT NULL |
| approved_by | string | Owner identifier; nullable |

### BacktestReport

Structured output of a backtest run, including all required analyses.

| Field | Type | Constraints |
|-------|------|-------------|
| report_id | uuid | PK |
| run_id | uuid | FK to BacktestRun; NOT NULL; UNIQUE |
| dataset_hash | string | NOT NULL |
| code_hash | string | NOT NULL |
| configuration_hash | string | NOT NULL |
| no_trade_benchmark_pnl | decimal | P/L from doing nothing; NOT NULL |
| parameter_sensitivity | string | JSON sensitivity analysis; NOT NULL |
| uncertainty_range | string | JSON confidence intervals; NOT NULL |
| drawdown_analysis | string | JSON drawdown details; NOT NULL |
| trade_count_analysis | string | JSON trade frequency details; NOT NULL |
| slippage_sensitivity | string | JSON slippage grid results; nullable |
| leakage_check_passed | boolean | NOT NULL |
| meets_acceptance_criteria | boolean | Nullable — null if no criteria defined |
| criteria_version | string | FK to AcceptanceCriteria; nullable |
| generated_at | timestamp | NOT NULL |

## Relationships

```
ApprovedDataSource 1──* HistoricalDataset
HistoricalDataset 1──* BacktestRun
BacktestRun 1──1 BacktestReport
BacktestRun 1──1 TriedConfiguration
AcceptanceCriteria 0..1──* BacktestReport
CostModelConfig *──1 pair (TEXT, canonical pair name)
```

## Notes

- ApprovedDataSource and AcceptanceCriteria are gate entities. The
  system refuses to operate without them (FR-001, FR-012).
- TriedConfiguration is append-only. Application code enforces
  insert-only; no DELETE or UPDATE queries exist.
- All hashes are SHA-256. Dataset hash covers raw file bytes; code
  hash covers relevant Python source; configuration hash covers
  sorted JSON of all parameters.
- Migration 010 adds these tables. It does not modify existing
  Phase 2–6 tables.
- The exit policy version in BacktestRun references the
  owner-approved policy (§19#18). Until approved, strategy
  evaluation runs are blocked.
