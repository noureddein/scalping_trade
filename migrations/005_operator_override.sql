-- Migration 005: Operator override audit table and OPERATOR_OVERRIDE state.
-- PREPARED — NOT APPLIED. Do not run until explicitly approved.
--
-- Depends on: 004_admission_protocol.sql
-- Requires: PostgreSQL 14+
--
-- Adds OPERATOR_OVERRIDE to the allowed order states. This state:
--   - Does NOT imply the broker order reached a terminal outcome.
--   - The broker exposure remains unresolved.
--   - The pair reservation is NOT released.
--   - Startup reconciliation still sees the order (it is not terminal).
--   - Allows future transition to FILLED/REJECTED/EXPIRED when broker
--     evidence arrives.
--   - Unblocks the admission protocol (SUBMITTING → IDLE) so the
--     admission slot is not permanently stuck.
--
-- The override path in the application is DISABLED until authenticated
-- operator identity is implemented. operator_id in the audit table is
-- an unauthenticated label, NOT an authentication claim.
--
-- The audit record is persisted atomically with the state change in the
-- same transaction. If the audit insert fails, the override does not
-- take effect.

BEGIN;

-- 1. Widen the order state CHECK constraint to include OPERATOR_OVERRIDE.
ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_state_check;
ALTER TABLE orders ADD CONSTRAINT orders_state_check
    CHECK (state IN (
        'PENDING_SUBMIT','SUBMITTED','FILLED','REJECTED',
        'EXPIRED','FAILED','UNKNOWN','OPERATOR_OVERRIDE'
    ));

-- 2. Update the transition validation function.
--    OPERATOR_OVERRIDE is reachable from PENDING_SUBMIT.
--    OPERATOR_OVERRIDE can transition to FILLED/REJECTED/EXPIRED
--    when authoritative broker evidence arrives later.
CREATE OR REPLACE FUNCTION valid_order_transition(old_state TEXT, new_state TEXT)
RETURNS BOOLEAN
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN old_state = new_state THEN TRUE
        WHEN old_state = 'PENDING_SUBMIT' THEN new_state IN
            ('SUBMITTED','FILLED','REJECTED','EXPIRED','FAILED',
             'UNKNOWN','OPERATOR_OVERRIDE')
        WHEN old_state = 'SUBMITTED' THEN new_state IN
            ('FILLED','REJECTED','EXPIRED','UNKNOWN')
        WHEN old_state = 'UNKNOWN' THEN new_state IN
            ('SUBMITTED','FILLED','REJECTED','EXPIRED')
        WHEN old_state = 'OPERATOR_OVERRIDE' THEN new_state IN
            ('FILLED','REJECTED','EXPIRED')
        ELSE FALSE
    END;
$$;

-- 3. Include OPERATOR_OVERRIDE in the non-terminal partial index so
--    startup reconciliation queries find these orders efficiently.
DROP INDEX IF EXISTS idx_orders_non_terminal;
CREATE INDEX idx_orders_non_terminal
    ON orders (state)
    WHERE state IN ('PENDING_SUBMIT','SUBMITTED','UNKNOWN','OPERATOR_OVERRIDE');

-- 4. Structured operator-override audit table.
--    Persisted atomically with the OPERATOR_OVERRIDE state change.
CREATE TABLE operator_override_audit (
    id                       BIGSERIAL   PRIMARY KEY,
    idempotency_key          TEXT        NOT NULL REFERENCES orders(idempotency_key),
    operator_id              TEXT        NOT NULL,
    reason                   TEXT        NOT NULL,
    broker_inspection_summary TEXT       NOT NULL,
    override_at              TIMESTAMPTZ NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_override_audit_key ON operator_override_audit (idempotency_key);

COMMENT ON TABLE operator_override_audit IS
    'Durable audit trail for operator overrides. Each row records who '
    'overrode an unresolved order, why, and what broker evidence they '
    'inspected. operator_id is an unauthenticated label — the override '
    'path is disabled until authenticated operator identity is implemented.';

COMMIT;
