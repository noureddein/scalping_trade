-- Migration 009: Dashboard tables (Phase 6)
-- audit_log: durable record of every configuration change
-- pair_configuration: per-pair dashboard settings (enabled/disabled)

BEGIN;

CREATE TABLE IF NOT EXISTS audit_log (
    entry_id       UUID PRIMARY KEY,
    account_id     TEXT NOT NULL,
    parameter_name TEXT NOT NULL,
    old_value      TEXT NOT NULL,
    new_value      TEXT NOT NULL,
    change_source  TEXT NOT NULL,
    operator_id    TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_account_created
    ON audit_log (account_id, created_at DESC);

CREATE TABLE IF NOT EXISTS pair_configuration (
    pair_id         UUID PRIMARY KEY,
    canonical_pair  TEXT UNIQUE NOT NULL,
    broker_symbol   TEXT NOT NULL,
    trading_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pair_configuration_pair
    ON pair_configuration (canonical_pair);

COMMIT;
