-- Migration 010: Backtesting tables (Phase 7)
-- Deterministic replay harness metadata, tried-configuration ledger, reports

BEGIN;

CREATE TABLE IF NOT EXISTS approved_data_source (
    source_id       UUID PRIMARY KEY,
    provider        TEXT NOT NULL,
    pair            TEXT NOT NULL,
    interval_type   TEXT NOT NULL CHECK (interval_type IN ('real_tick', 'generated')),
    timezone        TEXT NOT NULL,
    quality_score   DECIMAL NOT NULL,
    licensing_notes TEXT NOT NULL,
    approval_date   DATE NOT NULL,
    approval_notes  TEXT NOT NULL,
    approved_by     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS historical_dataset (
    dataset_id        UUID PRIMARY KEY,
    source_id         UUID NOT NULL REFERENCES approved_data_source(source_id),
    file_path         TEXT NOT NULL,
    file_hash         TEXT NOT NULL UNIQUE,
    pair              TEXT NOT NULL,
    start_time        TIMESTAMPTZ NOT NULL,
    end_time          TIMESTAMPTZ NOT NULL,
    tick_count        INTEGER NOT NULL,
    missing_intervals INTEGER NOT NULL,
    quality_flags     JSONB NOT NULL,
    loaded_at         TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS acceptance_criteria (
    criteria_id      UUID PRIMARY KEY,
    criteria_version TEXT NOT NULL UNIQUE,
    criteria_hash    TEXT NOT NULL,
    criteria_json    JSONB NOT NULL,
    approved_date    DATE NOT NULL,
    approved_by      TEXT NOT NULL,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS cost_model_config (
    config_id          UUID PRIMARY KEY,
    pair               TEXT NOT NULL,
    commission_per_lot DECIMAL NOT NULL,
    swap_long_per_lot  DECIMAL NOT NULL,
    swap_short_per_lot DECIMAL NOT NULL,
    rollover_time      TIME NOT NULL,
    slippage_scenarios JSONB NOT NULL,
    source_notes       TEXT NOT NULL,
    approved_by        TEXT
);

CREATE TABLE IF NOT EXISTS backtest_run (
    run_id              UUID PRIMARY KEY,
    dataset_id          UUID NOT NULL REFERENCES historical_dataset(dataset_id),
    strategy_name       TEXT NOT NULL,
    configuration_hash  TEXT NOT NULL,
    code_hash           TEXT NOT NULL,
    exit_policy_version TEXT NOT NULL,
    window_type         TEXT NOT NULL CHECK (window_type IN ('full', 'development', 'validation', 'test')),
    window_start        TIMESTAMPTZ NOT NULL,
    window_end          TIMESTAMPTZ NOT NULL,
    total_trades        INTEGER NOT NULL,
    net_pnl             DECIMAL NOT NULL,
    gross_pnl           DECIMAL NOT NULL,
    total_costs         DECIMAL NOT NULL,
    max_drawdown        DECIMAL NOT NULL,
    started_at          TIMESTAMPTZ NOT NULL,
    completed_at        TIMESTAMPTZ NOT NULL,
    report_path         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tried_configuration (
    entry_id           UUID PRIMARY KEY,
    run_id             UUID NOT NULL REFERENCES backtest_run(run_id),
    dataset_hash       TEXT NOT NULL,
    code_hash          TEXT NOT NULL,
    configuration_hash TEXT NOT NULL,
    configuration_json JSONB NOT NULL,
    strategy_name      TEXT NOT NULL,
    summary_result     JSONB NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_report (
    report_id                UUID PRIMARY KEY,
    run_id                   UUID NOT NULL UNIQUE REFERENCES backtest_run(run_id),
    dataset_hash             TEXT NOT NULL,
    code_hash                TEXT NOT NULL,
    configuration_hash       TEXT NOT NULL,
    no_trade_benchmark_pnl   DECIMAL NOT NULL,
    parameter_sensitivity    JSONB NOT NULL,
    uncertainty_range        JSONB NOT NULL,
    drawdown_analysis        JSONB NOT NULL,
    trade_count_analysis     JSONB NOT NULL,
    slippage_sensitivity     JSONB,
    leakage_check_passed     BOOLEAN NOT NULL,
    meets_acceptance_criteria BOOLEAN,
    criteria_version         TEXT REFERENCES acceptance_criteria(criteria_version),
    generated_at             TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_historical_dataset_pair ON historical_dataset(pair);
CREATE INDEX IF NOT EXISTS idx_backtest_run_dataset ON backtest_run(dataset_id);
CREATE INDEX IF NOT EXISTS idx_tried_configuration_run ON tried_configuration(run_id);
CREATE INDEX IF NOT EXISTS idx_tried_configuration_strategy ON tried_configuration(strategy_name, dataset_hash);

COMMIT;
