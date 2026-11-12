-- Migration 008: Widen order state CHECK and transition function to match
-- the full OrderState enum: DRAFT, SUBMITTING, CANCELLED, OPERATOR_RESOLVED.
-- PREPARED — NOT APPLIED. Do not run until explicitly approved.
--
-- Depends on: 005_operator_override.sql
-- Requires: PostgreSQL 14+
--
-- The application code defines these states in the OrderState enum and the
-- state guard validates transitions at the application layer. This migration
-- aligns the database CHECK constraint and transition function so the DB
-- accepts all states the application may persist.

BEGIN;

-- 1. Widen CHECK to include all OrderState values.
ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_state_check;
ALTER TABLE orders ADD CONSTRAINT orders_state_check
    CHECK (state IN (
        'DRAFT','PENDING_SUBMIT','SUBMITTING','SUBMITTED',
        'FILLED','REJECTED','CANCELLED','EXPIRED','FAILED',
        'UNKNOWN','OPERATOR_OVERRIDE','OPERATOR_RESOLVED'
    ));

-- 2. Update transition function to cover all states.
CREATE OR REPLACE FUNCTION valid_order_transition(old_state TEXT, new_state TEXT)
RETURNS BOOLEAN
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN old_state = new_state THEN TRUE
        WHEN old_state = 'DRAFT' THEN new_state IN
            ('PENDING_SUBMIT','CANCELLED')
        WHEN old_state = 'PENDING_SUBMIT' THEN new_state IN
            ('SUBMITTING','SUBMITTED','FILLED','REJECTED','CANCELLED',
             'EXPIRED','FAILED','UNKNOWN','OPERATOR_OVERRIDE')
        WHEN old_state = 'SUBMITTING' THEN new_state IN
            ('SUBMITTED','FILLED','REJECTED','CANCELLED',
             'UNKNOWN','OPERATOR_RESOLVED')
        WHEN old_state = 'SUBMITTED' THEN new_state IN
            ('FILLED','REJECTED','EXPIRED','UNKNOWN','CANCELLED')
        WHEN old_state = 'UNKNOWN' THEN new_state IN
            ('SUBMITTED','FILLED','REJECTED','EXPIRED','CANCELLED')
        WHEN old_state = 'OPERATOR_OVERRIDE' THEN new_state IN
            ('FILLED','REJECTED','EXPIRED')
        ELSE FALSE
    END;
$$;

-- 3. Update non-terminal index to include DRAFT, SUBMITTING, OPERATOR_RESOLVED.
DROP INDEX IF EXISTS idx_orders_non_terminal;
CREATE INDEX idx_orders_non_terminal
    ON orders (state)
    WHERE state IN (
        'DRAFT','PENDING_SUBMIT','SUBMITTING','SUBMITTED',
        'UNKNOWN','OPERATOR_OVERRIDE'
    );

COMMIT;
