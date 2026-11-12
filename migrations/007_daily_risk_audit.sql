-- Migration 007: persist floating P/L and auditable daily-risk events.
-- PREPARED — NOT APPLIED. Apply only through MigrationRunner to a disposable DB.
-- Depends on: 001_initial_schema.sql and 002_state_guard_and_reservation_owner.sql

BEGIN;

ALTER TABLE daily_risk_state
    ADD COLUMN floating_pnl_usd NUMERIC NOT NULL DEFAULT 0;

CREATE UNIQUE INDEX IF NOT EXISTS uq_schema_account_account_id
    ON schema_account (account_id);

CREATE TABLE risk_events (
    event_id UUID NOT NULL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES schema_account(account_id),
    event_type TEXT NOT NULL CHECK (event_type IN (
        'ENTRY_REJECTED', 'LIMIT_TRIGGERED', 'LOCK_ACTIVATED', 'LOCK_RESET',
        'OPERATOR_RESOLUTION', 'BARRIER_HELD', 'BARRIER_RELEASED',
        'RECONCILIATION_START', 'RECONCILIATION_COMPLETE',
        'FILL_PERSIST_FAILURE', 'ADMISSION_HALTED'
    )),
    detail TEXT NOT NULL,
    related_intent_id UUID,
    related_position_id UUID,
    operator_id TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_risk_events_account_created
    ON risk_events (account_id, created_at DESC);

COMMIT;
