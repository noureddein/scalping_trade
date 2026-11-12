-- Migration 011: Demo Forward Test tables (Phase 8)
-- Demo scope gate, evidence recording, execution discrepancy, reports

BEGIN;

CREATE TABLE IF NOT EXISTS demo_scope_approval (
    approval_id             UUID PRIMARY KEY,
    account_id              TEXT NOT NULL,
    account_type            TEXT NOT NULL CHECK (account_type = 'DEMO'),
    approved_pair           TEXT NOT NULL,
    approved_lot_size       DECIMAL NOT NULL,
    start_time              TIMESTAMPTZ NOT NULL,
    end_time                TIMESTAMPTZ NOT NULL CHECK (end_time > start_time),
    stop_conditions         JSONB NOT NULL,
    monitoring_requirements JSONB NOT NULL,
    status                  TEXT NOT NULL CHECK (status IN ('ACTIVE', 'EXPIRED', 'REVOKED')),
    approved_by             TEXT NOT NULL,
    approved_at             TIMESTAMPTZ NOT NULL,
    revoked_at              TIMESTAMPTZ,
    revocation_reason       TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_demo_scope_active
    ON demo_scope_approval (status) WHERE status = 'ACTIVE';

CREATE TABLE IF NOT EXISTS forward_test_session (
    session_id              UUID PRIMARY KEY,
    approval_id             UUID NOT NULL REFERENCES demo_scope_approval(approval_id),
    started_at              TIMESTAMPTZ NOT NULL,
    ended_at                TIMESTAMPTZ,
    end_reason              TEXT CHECK (end_reason IN (
        'duration_expired', 'owner_revoked', 'emergency_stop', 'manual_stop'
    )),
    total_signals           INTEGER NOT NULL DEFAULT 0,
    total_entries_attempted INTEGER NOT NULL DEFAULT 0,
    total_entries_rejected  INTEGER NOT NULL DEFAULT 0,
    total_fills             INTEGER NOT NULL DEFAULT 0,
    total_rejections        INTEGER NOT NULL DEFAULT 0,
    net_pnl                 DECIMAL,
    total_costs             DECIMAL
);

CREATE TABLE IF NOT EXISTS forward_test_event (
    event_id                UUID PRIMARY KEY,
    session_id              UUID NOT NULL REFERENCES forward_test_session(session_id),
    event_type              TEXT NOT NULL CHECK (event_type IN (
        'SIGNAL_GENERATED', 'SIGNAL_REJECTED',
        'ENTRY_APPROVED', 'ENTRY_REJECTED',
        'ORDER_SUBMITTED', 'ORDER_FILLED', 'ORDER_REJECTED', 'ORDER_TIMEOUT',
        'FILL_DISCREPANCY', 'COST_RECORDED',
        'SPREAD_AT_DECISION', 'LATENCY_RECORDED',
        'DURATION_EXPIRED', 'APPROVAL_REVOKED'
    )),
    timestamp               TIMESTAMPTZ NOT NULL,
    pair                    TEXT NOT NULL,
    detail                  JSONB NOT NULL,
    related_intent_id       UUID,
    related_signal_id       UUID
);

CREATE INDEX IF NOT EXISTS ix_forward_test_event_session
    ON forward_test_event (session_id, timestamp);

CREATE TABLE IF NOT EXISTS execution_discrepancy (
    discrepancy_id          UUID PRIMARY KEY,
    session_id              UUID NOT NULL REFERENCES forward_test_session(session_id),
    intent_id               UUID NOT NULL,
    expected_price          DECIMAL NOT NULL,
    actual_price            DECIMAL NOT NULL,
    slippage_pips           DECIMAL NOT NULL,
    submission_time         TIMESTAMPTZ NOT NULL,
    fill_time               TIMESTAMPTZ NOT NULL,
    latency_ms              INTEGER NOT NULL,
    direction               TEXT NOT NULL CHECK (direction IN ('BUY', 'SELL'))
);

CREATE TABLE IF NOT EXISTS forward_test_report (
    report_id               UUID PRIMARY KEY,
    session_id              UUID NOT NULL UNIQUE REFERENCES forward_test_session(session_id),
    sample_size             INTEGER NOT NULL,
    sample_sufficient       BOOLEAN NOT NULL,
    net_pnl                 DECIMAL NOT NULL,
    gross_pnl               DECIMAL NOT NULL,
    total_spread_cost       DECIMAL NOT NULL,
    total_commission        DECIMAL NOT NULL,
    total_swap              DECIMAL NOT NULL,
    avg_slippage_pips       DECIMAL NOT NULL,
    max_drawdown            DECIMAL NOT NULL,
    win_rate                DECIMAL NOT NULL,
    avg_trade_duration      INTERVAL NOT NULL,
    statistical_warnings    JSONB NOT NULL,
    generated_at            TIMESTAMPTZ NOT NULL
);

COMMIT;
