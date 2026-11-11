-- Migration 002: Order state transition enforcement + single-account guard.
-- PREPARED — NOT APPLIED. Do not run until explicitly approved.
--
-- Depends on: 001_initial_schema.sql
-- Requires: PostgreSQL 14+

BEGIN;

-- 1. Transition validation function.
--    Encodes the full allowed-transition matrix. Used by the trigger and
--    available for ad-hoc queries.
--
--    PENDING_SUBMIT → SUBMITTED, FILLED, REJECTED, EXPIRED, FAILED, UNKNOWN
--    SUBMITTED      → FILLED, REJECTED, EXPIRED, UNKNOWN
--    UNKNOWN        → SUBMITTED, FILLED, REJECTED, EXPIRED
--    Terminal        → (nothing — same-state no-op allowed)
CREATE OR REPLACE FUNCTION valid_order_transition(old_state TEXT, new_state TEXT)
RETURNS BOOLEAN
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN old_state = new_state THEN TRUE
        WHEN old_state = 'PENDING_SUBMIT' THEN new_state IN
            ('SUBMITTED','FILLED','REJECTED','EXPIRED','FAILED','UNKNOWN')
        WHEN old_state = 'SUBMITTED' THEN new_state IN
            ('FILLED','REJECTED','EXPIRED','UNKNOWN')
        WHEN old_state = 'UNKNOWN' THEN new_state IN
            ('SUBMITTED','FILLED','REJECTED','EXPIRED')
        ELSE FALSE
    END;
$$;

-- 2. Trigger: RAISE on invalid transitions (defense-in-depth).
--    The application layer's WHERE clause is the primary guard. This
--    trigger catches any UPDATE path that bypasses the application
--    (manual fix-ups, migration scripts, direct psql).
CREATE OR REPLACE FUNCTION guard_order_state_transition()
RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT valid_order_transition(OLD.state, NEW.state) THEN
        RAISE EXCEPTION 'invalid order state transition: % → %',
            OLD.state, NEW.state
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_order_state_guard
    BEFORE UPDATE ON orders
    FOR EACH ROW
    EXECUTE FUNCTION guard_order_state_transition();

-- 3. Single-account enforcement.
--    One-row singleton table. The application calls verify_account() on
--    startup; a second account_id is rejected with AccountMismatchError.
--    Multi-account requires adding account_id to all tables — see the
--    ALTER statements in the comments below.
CREATE TABLE schema_account (
    id          INT  NOT NULL PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    account_id  TEXT NOT NULL,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE schema_account IS
    'Singleton: binds this database to one MT5 account. '
    'Multi-account requires account_id columns on all data tables.';

-- 4. Table-level documentation of single-account scope.
COMMENT ON TABLE daily_risk_state IS 'Single-account: trading_day PK assumes one account per database.';
COMMENT ON TABLE orders IS 'Single-account: idempotency_key PK is scoped to one account.';
COMMENT ON TABLE positions IS 'Single-account: broker_ticket PK is unique only within one MT5 account.';
COMMENT ON TABLE pair_reservations IS 'Single-account: canonical_pair PK assumes one account per database.';

-- To support multi-account in a future migration:
--   ALTER TABLE orders ADD COLUMN account_id TEXT NOT NULL DEFAULT 'default';
--   ALTER TABLE positions ADD COLUMN account_id TEXT NOT NULL DEFAULT 'default';
--   ALTER TABLE daily_risk_state ADD COLUMN account_id TEXT NOT NULL DEFAULT 'default';
--   ALTER TABLE pair_reservations ADD COLUMN account_id TEXT NOT NULL DEFAULT 'default';
-- Then rebuild PKs and indexes to include account_id.

COMMIT;
