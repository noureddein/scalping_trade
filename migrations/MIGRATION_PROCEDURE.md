# Migration Procedure — Phase 5

## Prerequisites

- PostgreSQL 14+ server running and accessible
- Database `scalping` created: `CREATE DATABASE scalping;`
- Application stopped (no running Python processes)
- Backup taken: `pg_dump scalping > backup_$(date +%Y%m%d_%H%M%S).sql`

## Migration order

Migrations must be applied in sequence. Each depends on the previous.

| Migration | Depends on | What it does |
|-----------|-----------|-------------|
| 001_initial_schema.sql | — | Tables: daily_risk_state, orders, positions, pair_reservations. Indexes. |
| 002_state_guard_and_reservation_owner.sql | 001 | Order state transition trigger, schema_account singleton. |
| 003_reconciliation_barrier.sql | 002 | reconciliation_barrier singleton table, seeded as PENDING. |
| 004_admission_protocol.sql | 003 | admission_status column on pair_reservations. |

## Applying migrations

```bash
# From the project root, one at a time:
psql -d scalping -f migrations/001_initial_schema.sql
psql -d scalping -f migrations/002_state_guard_and_reservation_owner.sql
psql -d scalping -f migrations/003_reconciliation_barrier.sql
psql -d scalping -f migrations/004_admission_protocol.sql
```

Each migration wraps its changes in `BEGIN`/`COMMIT`. If any statement
fails, the entire migration rolls back — no partial state.

## Verification

After applying all four:

```sql
-- Verify tables exist
SELECT tablename FROM pg_tables WHERE schemaname = 'public'
ORDER BY tablename;
-- Expected: daily_risk_state, orders, pair_reservations, positions,
--           reconciliation_barrier, schema_account

-- Verify barrier is seeded
SELECT * FROM reconciliation_barrier;
-- Expected: id=1, status='PENDING'

-- Verify trigger exists
SELECT tgname FROM pg_trigger WHERE tgrelid = 'orders'::regclass;
-- Expected: trg_order_state_guard

-- Verify admission_status column
SELECT column_name, column_default FROM information_schema.columns
WHERE table_name = 'pair_reservations' AND column_name = 'admission_status';
-- Expected: admission_status, default 'IDLE'
```

## Consistency notes

- **001 + 004 interaction**: Migration 001 creates pair_reservations
  without admission_status. Migration 004 adds it with DEFAULT 'IDLE'.
  Pre-existing rows get IDLE (correct for established reservations).
  New inserts from application code explicitly set 'ACQUIRED'.

- **002 trigger + application upsert**: The trigger in 002 validates
  state transitions on UPDATE. The application's ON CONFLICT upsert
  in save_order() uses a WHERE clause that encodes the same matrix.
  The trigger is defense-in-depth for non-application UPDATE paths.

- **003 barrier seed**: Seeded as PENDING. The first process must call
  begin() → reconcile → complete() to set it to READY before any
  acquire() can succeed.

## Rollback

Each migration can be reversed manually if needed:

```sql
-- Reverse 004:
ALTER TABLE pair_reservations DROP COLUMN admission_status;

-- Reverse 003:
DROP TABLE reconciliation_barrier;

-- Reverse 002:
DROP TRIGGER trg_order_state_guard ON orders;
DROP FUNCTION guard_order_state_transition();
DROP FUNCTION valid_order_transition(TEXT, TEXT);
DROP TABLE schema_account;

-- Reverse 001:
DROP TABLE pair_reservations;
DROP TABLE positions;
DROP TABLE orders;
DROP TABLE daily_risk_state;
```

## DO NOT

- Do not apply migrations while the application is running.
- Do not skip migrations or apply out of order.
- Do not modify migration files after they have been applied.
- Do not apply migrations from this task — owner approval required first.
