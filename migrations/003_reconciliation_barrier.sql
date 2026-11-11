-- Migration 003: Database-enforced startup reconciliation barrier.
-- PREPARED — NOT APPLIED. Do not run until explicitly approved.
--
-- Depends on: 002_state_guard_and_reservation_owner.sql
-- Requires: PostgreSQL 14+
--
-- The barrier prevents all entry submissions (pair_reservations INSERT)
-- while reconciliation is in progress. It uses a singleton row whose
-- status is checked atomically inside the INSERT statement itself, so
-- no process-local flag can bypass it.
--
-- Exclusive reconciliation is enforced via pg_advisory_lock (session-level).
-- If the reconciler's connection drops, the lock is released and another
-- process can safely take over and re-reconcile from scratch.

BEGIN;

CREATE TABLE reconciliation_barrier (
    id              INT  NOT NULL PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    status          TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING','RECONCILING','READY')),
    reconciler_id   TEXT,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ
);

COMMENT ON TABLE reconciliation_barrier IS
    'Singleton: gates all entry submissions. Status must be READY before '
    'any pair reservation can be acquired. acquire() takes FOR SHARE on '
    'this row; begin() takes FOR UPDATE — the exclusive row lock blocks '
    'until every in-flight acquire commits. Reconciler holds '
    'pg_advisory_lock(799215217) for exclusive access.';

-- Seed the barrier in PENDING state. First process to start must reconcile.
INSERT INTO reconciliation_barrier (id, status) VALUES (1, 'PENDING');

COMMIT;
