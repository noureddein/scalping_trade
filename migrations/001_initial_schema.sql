-- Migration 001: Initial schema for durable state and pair reservations.
-- PREPARED — NOT APPLIED. Do not run until explicitly approved.
--
-- Requires: PostgreSQL 14+
-- Database: scalping (independent, per §1.1)

BEGIN;

-- Daily risk state: one row per trading day.
-- Upserted each time risk state or P/L changes.
CREATE TABLE daily_risk_state (
    trading_day    DATE    NOT NULL PRIMARY KEY,
    risk_state     TEXT    NOT NULL DEFAULT 'ACTIVE'
        CHECK (risk_state IN ('ACTIVE','PROFIT_LOCKED','LOSS_LOCKED','DRAINING','DISABLED')),
    realized_pnl_usd NUMERIC NOT NULL DEFAULT 0,
    commission_usd   NUMERIC NOT NULL DEFAULT 0,
    swap_usd         NUMERIC NOT NULL DEFAULT 0,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Order lifecycle: one row per idempotency key.
-- Request columns are immutable after insert; result columns update on state change.
CREATE TABLE orders (
    idempotency_key    TEXT    NOT NULL PRIMARY KEY,
    canonical_pair     TEXT    NOT NULL,
    broker_symbol      TEXT    NOT NULL,
    side               TEXT    NOT NULL CHECK (side IN ('BUY','SELL')),
    volume_lots        NUMERIC NOT NULL,
    stop_loss_price    NUMERIC NOT NULL,
    take_profit_price  NUMERIC,
    signal_timestamp_ms BIGINT NOT NULL,
    fresh_quote_bid    NUMERIC NOT NULL,
    fresh_quote_ask    NUMERIC NOT NULL,
    fresh_quote_time_ms BIGINT NOT NULL,
    state              TEXT    NOT NULL
        CHECK (state IN ('PENDING_SUBMIT','SUBMITTED','FILLED','REJECTED','EXPIRED','FAILED','UNKNOWN')),
    broker_ticket      BIGINT,
    fill_price         NUMERIC,
    fill_volume        NUMERIC,
    fill_time_ms       BIGINT,
    reject_reason      TEXT,
    broker_retcode     INTEGER,
    raw_comment        TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Partial index: only non-terminal orders need fast lookup for reconciliation.
CREATE INDEX idx_orders_non_terminal
    ON orders (state)
    WHERE state IN ('PENDING_SUBMIT','SUBMITTED','UNKNOWN');

CREATE INDEX idx_orders_pair ON orders (canonical_pair);
CREATE INDEX idx_orders_broker_ticket ON orders (broker_ticket) WHERE broker_ticket IS NOT NULL;

-- Open position tracking.
-- closed_at NULL = open. Broker ticket is the natural key.
CREATE TABLE positions (
    broker_ticket  BIGINT      NOT NULL PRIMARY KEY,
    canonical_pair TEXT        NOT NULL,
    broker_symbol  TEXT        NOT NULL,
    side           TEXT        NOT NULL CHECK (side IN ('BUY','SELL')),
    volume_lots    NUMERIC     NOT NULL,
    open_price     NUMERIC     NOT NULL,
    stop_loss      NUMERIC     NOT NULL,
    take_profit    NUMERIC,
    open_time_ms   BIGINT      NOT NULL,
    closed_at      TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_positions_open
    ON positions (canonical_pair)
    WHERE closed_at IS NULL;

-- Atomic pair reservation: INSERT succeeds only if no row exists.
-- Cross-process safety via unique constraint on canonical_pair.
CREATE TABLE pair_reservations (
    canonical_pair TEXT        NOT NULL PRIMARY KEY,
    reserved_by    TEXT        NOT NULL,
    reserved_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
