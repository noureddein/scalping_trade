-- Migration 004: In-flight admission tracking for entry attempts.
-- PREPARED — NOT APPLIED. Do not run until explicitly approved.
--
-- Depends on: 003_reconciliation_barrier.sql
-- Requires: PostgreSQL 14+
--
-- Closes the in-flight entry race: after acquire() commits, an entry
-- attempt can proceed toward broker submission while the reconciler
-- starts. Without this column, the reconciler cannot distinguish
-- "reservation acquired, broker submission not yet started" from
-- "stale reservation from a crashed process."
--
-- admission_status tracks entry attempt lifecycle:
--   ACQUIRED   — reservation held, broker not yet contacted
--   SUBMITTING — broker submission in progress; order intent (PENDING_SUBMIT)
--                is durably committed in the orders table within the same
--                transaction that sets this status (FOR SHARE held, so
--                begin()'s FOR UPDATE waits)
--   IDLE       — broker responded; order outcome persisted in orders table
--                within the same transaction that sets this status
--
-- Valid transitions (enforced in application code):
--   ACQUIRED   → SUBMITTING  (gate_submission: barrier check + intent persist
--                              + status update, all in one transaction)
--   SUBMITTING → IDLE         (resolve_admission: outcome persist + status
--                              update, all in one transaction)
--   New INSERT always sets ACQUIRED; DEFAULT 'IDLE' is for pre-migration rows.
--
-- Durable order-intent guarantee: a SUBMITTING row always has a
-- corresponding PENDING_SUBMIT row in the orders table (same transaction).
-- On crash, the reconciler can recover the idempotency_key from the
-- orders table and attempt broker correlation.
--
-- Reconciler protocol after begin():
--   1. Poll for SUBMITTING entries. Wait until none remain or timeout.
--   2. SUBMITTING entries that survive the timeout are NOT released.
--      Neither an empty broker query, a dead submitter process, nor
--      an absent PostgreSQL backend proves the already-transmitted
--      request will not still execute at the broker. No local fencing
--      mechanism can revoke a network-in-flight request. Resolution
--      requires: (a) the submitting process resolves to IDLE,
--      (b) authoritative broker evidence tied to the exact request
--      (idempotency key / request ID) proves its terminal state, or
--      (c) manual operator intervention after broker inspection.
--   3. ACQUIRED entries cannot proceed (barrier is RECONCILING), so
--      they are safe to handle after the drain completes.

BEGIN;

ALTER TABLE pair_reservations
    ADD COLUMN admission_status TEXT NOT NULL DEFAULT 'IDLE'
    CHECK (admission_status IN ('ACQUIRED', 'SUBMITTING', 'IDLE'));

COMMENT ON COLUMN pair_reservations.admission_status IS
    'Entry attempt lifecycle. ACQUIRED: reserved, broker not contacted. '
    'SUBMITTING: broker call in progress — reconciler must wait. '
    'IDLE: broker responded or pre-existing reservation. '
    'Default IDLE is correct for pre-migration rows (established reservations).';

COMMIT;
