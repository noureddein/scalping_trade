-- Migration 006: Add HALTED status to reconciliation barrier.
-- PREPARED — NOT APPLIED. Do not run until explicitly approved.
--
-- Depends on: 003_reconciliation_barrier.sql
-- Requires: PostgreSQL 14+
--
-- When an engine receives a broker FILLED result but cannot durably
-- persist it (resolve_admission fails), the barrier must be set to
-- HALTED so all processes' acquire() and gate_submission() calls fail
-- system-wide. Only startup reconciliation can clear the halt:
--   HALTED → RECONCILING (begin()) → READY (complete())
--
-- The HALTED state indicates an unresolved fill exists somewhere in
-- the account. Unlike RECONCILING (which implies a reconciler holds
-- the advisory lock), HALTED is set by a normal engine process and
-- does not require the advisory lock — the next startup reconciler
-- will observe the non-READY state and proceed normally.
--
-- Existing queries that check `status = 'READY'` (acquire, gate_submission)
-- reject HALTED by construction — no query changes needed.

BEGIN;

-- Widen the CHECK constraint to include HALTED.
ALTER TABLE reconciliation_barrier
    DROP CONSTRAINT IF EXISTS reconciliation_barrier_status_check;

ALTER TABLE reconciliation_barrier
    ADD CONSTRAINT reconciliation_barrier_status_check
    CHECK (status IN ('PENDING', 'RECONCILING', 'READY', 'HALTED'));

COMMIT;
