"""PostgreSQL-backed durable state store and pair reservation provider.

Implements the persistence prerequisites for Phase 5. Requires the schema
from migrations/001_initial_schema.sql to be applied.

Uses psycopg 3 (sync API). No connection pool — single connection per
instance, reconnects on failure. Add pooling when concurrency requires it.

Two-gate admission protocol: acquire() (gate 1) and gate_submission()
(gate 2) both run in explicit transactions with FOR SHARE on the
reconciliation_barrier row. begin() runs with FOR UPDATE on the same
row. The exclusive row lock in begin() blocks until every in-flight
FOR SHARE holder (acquire or gate_submission) commits. This ensures:
  - load_all_reservations() sees every reservation (from acquire)
  - The drain step sees every SUBMITTING entry (from gate_submission)
An entry that passed gate 1 but not gate 2 is ACQUIRED; its
gate_submission() will fail because the barrier is now RECONCILING.

Durable order-intent lifecycle: gate_submission() atomically persists
the OrderRequest as PENDING_SUBMIT in the orders table within the same
transaction that sets SUBMITTING. resolve_admission() atomically persists
the broker's OrderResult and sets IDLE. A crash at any point leaves
recoverable state — see crash-point documentation in execution_engine.py.

Single-account assumption: all tables key on broker_ticket, trading_day,
or canonical_pair WITHOUT an account_id qualifier. Running two accounts
against the same database causes key collisions (broker_ticket reuse
across accounts, risk state clobbering). Enforce via separate databases
or add an account_id partition — see migration 002.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row

from .daily_risk import DailyPnL
from .execution_engine import DurableStateStore, PairReservationProvider, StartupReconciler
from .order_types import (
    AccountMismatchError,
    OrderRecord,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderState,
    OverrideAuditRecord,
    PositionInfo,
    StaleOrderStateError,
    is_terminal,
    is_valid_transition,
)
from .risk_gate import RiskState


def _conninfo() -> str:
    return os.environ.get(
        "SCALPING_DATABASE_URL",
        "postgresql://localhost:5432/scalping",
    )


class PostgresDurableStateStore(DurableStateStore):
    """PostgreSQL implementation of DurableStateStore.

    Idempotent writes, recovery reads. Single connection, no pool.
    """

    def __init__(self, conninfo: str | None = None) -> None:
        self._conninfo = conninfo or _conninfo()
        self._conn: psycopg.Connection | None = None

    def _get_conn(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(
                self._conninfo, row_factory=dict_row, autocommit=True,
            )
        return self._conn

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
            self._conn = None

    def is_available(self) -> bool:
        try:
            conn = self._get_conn()
            conn.execute("SELECT 1")
            return True
        except Exception:
            self._conn = None
            return False

    # -- Daily risk ----------------------------------------------------------

    def save_risk_snapshot(
        self, trading_day: date, state: RiskState, pnl: DailyPnL,
    ) -> None:
        self._get_conn().execute(
            """
            INSERT INTO daily_risk_state
                (trading_day, risk_state, realized_pnl_usd, commission_usd, swap_usd, updated_at)
            VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (trading_day) DO UPDATE SET
                risk_state       = EXCLUDED.risk_state,
                realized_pnl_usd = EXCLUDED.realized_pnl_usd,
                commission_usd   = EXCLUDED.commission_usd,
                swap_usd         = EXCLUDED.swap_usd,
                updated_at       = now()
            """,
            (trading_day, state.value, pnl.realized_pnl_usd, pnl.commission_usd, pnl.swap_usd),
        )

    def load_risk_snapshot(
        self, trading_day: date,
    ) -> tuple[RiskState, DailyPnL] | None:
        row = self._get_conn().execute(
            "SELECT risk_state, realized_pnl_usd, commission_usd, swap_usd "
            "FROM daily_risk_state WHERE trading_day = %s",
            (trading_day,),
        ).fetchone()
        if row is None:
            return None
        return (
            RiskState(row["risk_state"]),
            DailyPnL(
                realized_pnl_usd=Decimal(str(row["realized_pnl_usd"])),
                floating_pnl_usd=Decimal(0),
                commission_usd=Decimal(str(row["commission_usd"])),
                swap_usd=Decimal(str(row["swap_usd"])),
            ),
        )

    # -- Orders --------------------------------------------------------------

    def save_order(self, record: OrderRecord) -> None:
        """Upsert an order. Raises StaleOrderStateError on invalid transition.

        The WHERE clause encodes the full transition matrix — if the
        existing row's state does not allow the new state, the UPDATE is
        skipped and RETURNING yields no row, which we detect and raise on.
        Migration 002's trigger is defense-in-depth for non-application
        UPDATE paths.
        """
        req = record.request
        res = record.result
        row = self._get_conn().execute(
            """
            INSERT INTO orders (
                idempotency_key, canonical_pair, broker_symbol, side,
                volume_lots, stop_loss_price, take_profit_price,
                signal_timestamp_ms, fresh_quote_bid, fresh_quote_ask,
                fresh_quote_time_ms, state, broker_ticket, fill_price,
                fill_volume, fill_time_ms, reject_reason, broker_retcode,
                raw_comment
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            )
            ON CONFLICT (idempotency_key) DO UPDATE SET
                state          = EXCLUDED.state,
                broker_ticket  = COALESCE(EXCLUDED.broker_ticket, orders.broker_ticket),
                fill_price     = COALESCE(EXCLUDED.fill_price, orders.fill_price),
                fill_volume    = COALESCE(EXCLUDED.fill_volume, orders.fill_volume),
                fill_time_ms   = COALESCE(EXCLUDED.fill_time_ms, orders.fill_time_ms),
                reject_reason  = COALESCE(EXCLUDED.reject_reason, orders.reject_reason),
                broker_retcode = COALESCE(EXCLUDED.broker_retcode, orders.broker_retcode),
                raw_comment    = COALESCE(EXCLUDED.raw_comment, orders.raw_comment),
                updated_at     = now()
            WHERE (
                orders.state = EXCLUDED.state
                OR (orders.state = 'PENDING_SUBMIT' AND EXCLUDED.state IN
                    ('SUBMITTED','FILLED','REJECTED','EXPIRED','FAILED',
                     'UNKNOWN','OPERATOR_OVERRIDE'))
                OR (orders.state = 'SUBMITTED' AND EXCLUDED.state IN
                    ('FILLED','REJECTED','EXPIRED','UNKNOWN'))
                OR (orders.state = 'UNKNOWN' AND EXCLUDED.state IN
                    ('SUBMITTED','FILLED','REJECTED','EXPIRED'))
                OR (orders.state = 'OPERATOR_OVERRIDE' AND EXCLUDED.state IN
                    ('FILLED','REJECTED','EXPIRED'))
            )
            RETURNING state
            """,
            (
                req.idempotency_key, req.canonical_pair, req.broker_symbol,
                req.side.value, req.volume_lots, req.stop_loss_price,
                req.take_profit_price, req.signal_timestamp_ms,
                req.fresh_quote_bid, req.fresh_quote_ask,
                req.fresh_quote_time_ms, res.state.value, res.broker_ticket,
                res.fill_price, res.fill_volume, res.fill_time_ms,
                res.reject_reason, res.broker_retcode, res.raw_comment,
            ),
        ).fetchone()
        if row is None:
            current = self._get_conn().execute(
                "SELECT state FROM orders WHERE idempotency_key = %s",
                (req.idempotency_key,),
            ).fetchone()
            current_state = OrderState(current["state"]) if current else OrderState.UNKNOWN
            raise StaleOrderStateError(req.idempotency_key, res.state, current_state)

    def load_order(self, idempotency_key: str) -> OrderRecord | None:
        row = self._get_conn().execute(
            "SELECT * FROM orders WHERE idempotency_key = %s",
            (idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_order_record(row)

    def load_non_terminal_orders(self) -> list[OrderRecord]:
        rows = self._get_conn().execute(
            "SELECT * FROM orders WHERE state IN "
            "('PENDING_SUBMIT','SUBMITTED','UNKNOWN','OPERATOR_OVERRIDE')",
        ).fetchall()
        return [_row_to_order_record(r) for r in rows]

    # -- Positions -----------------------------------------------------------

    def save_position(self, position: PositionInfo) -> None:
        self._get_conn().execute(
            """
            INSERT INTO positions (
                broker_ticket, canonical_pair, broker_symbol, side,
                volume_lots, open_price, stop_loss, take_profit, open_time_ms
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (broker_ticket) DO UPDATE SET
                stop_loss  = EXCLUDED.stop_loss,
                take_profit = EXCLUDED.take_profit,
                updated_at  = now()
            """,
            (
                position.broker_ticket, position.canonical_pair,
                position.broker_symbol, position.side.value,
                position.volume_lots, position.open_price,
                position.stop_loss, position.take_profit,
                position.open_time_ms,
            ),
        )

    def load_open_positions(self) -> list[PositionInfo]:
        rows = self._get_conn().execute(
            "SELECT * FROM positions WHERE closed_at IS NULL",
        ).fetchall()
        return [_row_to_position(r) for r in rows]

    def mark_position_closed(self, broker_ticket: int) -> None:
        self._get_conn().execute(
            "UPDATE positions SET closed_at = now(), updated_at = now() "
            "WHERE broker_ticket = %s AND closed_at IS NULL",
            (broker_ticket,),
        )

    def verify_account(self, account_id: str) -> None:
        """Bind this database to a single MT5 account, or verify the binding.

        Must be called once on startup before any writes. Raises
        AccountMismatchError if a different account_id is already registered.
        Requires migration 002 (schema_account table).
        """
        row = self._get_conn().execute(
            "SELECT account_id FROM schema_account WHERE id = 1",
        ).fetchone()
        if row is None:
            self._get_conn().execute(
                "INSERT INTO schema_account (account_id) VALUES (%s) "
                "ON CONFLICT (id) DO NOTHING",
                (account_id,),
            )
            row = self._get_conn().execute(
                "SELECT account_id FROM schema_account WHERE id = 1",
            ).fetchone()
        if row is not None and row["account_id"] != account_id:
            raise AccountMismatchError(row["account_id"], account_id)


class PostgresPairReservationProvider(PairReservationProvider):
    """PostgreSQL-backed atomic pair reservation.

    Cross-process safety: INSERT succeeds only if no row exists for the
    pair (unique PK constraint). Concurrent callers for the same pair
    get a conflict — only one succeeds.

    Survives restarts: reservations persist until explicitly released.
    """

    def __init__(
        self,
        conninfo: str | None = None,
        process_id: str | None = None,
    ) -> None:
        self._conninfo = conninfo or _conninfo()
        self._process_id = process_id or f"py-{uuid.uuid4().hex[:8]}"
        self._conn: psycopg.Connection | None = None

    def _get_conn(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(
                self._conninfo, row_factory=dict_row, autocommit=True,
            )
        return self._conn

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
            self._conn = None

    def is_available(self) -> bool:
        try:
            conn = self._get_conn()
            conn.execute("SELECT 1")
            return True
        except Exception:
            self._conn = None
            return False

    def acquire(self, canonical_pair: str) -> bool:
        """Gate 1: atomically reserve a pair, gated on the barrier.

        Runs in an explicit transaction with FOR SHARE on the barrier row.
        Sets admission_status='ACQUIRED'. The shared lock prevents
        begin() from changing the barrier to RECONCILING until this
        transaction commits.
        """
        conn = self._get_conn()
        try:
            conn.execute("BEGIN")
            row = conn.execute(
                "SELECT 1 FROM reconciliation_barrier "
                "WHERE id = 1 AND status = 'READY' FOR SHARE",
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return False
            result = conn.execute(
                "INSERT INTO pair_reservations "
                "(canonical_pair, reserved_by, admission_status) "
                "VALUES (%s, %s, 'ACQUIRED') "
                "ON CONFLICT (canonical_pair) DO NOTHING",
                (canonical_pair, self._process_id),
            )
            conn.execute("COMMIT")
            return result.rowcount == 1
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                self._conn = None
            return False

    def release(self, canonical_pair: str) -> None:
        try:
            self._get_conn().execute(
                "DELETE FROM pair_reservations "
                "WHERE canonical_pair = %s AND reserved_by = %s",
                (canonical_pair, self._process_id),
            )
        except Exception:
            pass

    # -- Reconciliation (startup only) -----------------------------------------

    def load_all_reservations(self) -> list[tuple[str, str]]:
        rows = self._get_conn().execute(
            "SELECT canonical_pair, reserved_by FROM pair_reservations",
        ).fetchall()
        return [(r["canonical_pair"], r["reserved_by"]) for r in rows]

    def adopt(self, canonical_pair: str) -> bool:
        result = self._get_conn().execute(
            """
            UPDATE pair_reservations SET reserved_by = %s
            WHERE canonical_pair = %s AND reserved_by != %s
            AND EXISTS (
                SELECT 1 FROM reconciliation_barrier
                WHERE id = 1 AND status = 'RECONCILING'
            )
            """,
            (self._process_id, canonical_pair, self._process_id),
        )
        return result.rowcount == 1

    def force_release(self, canonical_pair: str) -> None:
        """Remove a reservation regardless of owner.

        RECONCILER ONLY. Gated on barrier status RECONCILING in SQL —
        cannot run outside active reconciliation. Must be called only
        after the broker confirms no unresolved order or open position
        exists for this pair.
        """
        self._get_conn().execute(
            """
            DELETE FROM pair_reservations
            WHERE canonical_pair = %s
            AND EXISTS (
                SELECT 1 FROM reconciliation_barrier
                WHERE id = 1 AND status = 'RECONCILING'
            )
            """,
            (canonical_pair,),
        )

    # -- Admission protocol ----------------------------------------------------

    def gate_submission(
        self, canonical_pair: str, order_request: OrderRequest,
    ) -> bool:
        """Gate 2: re-verify barrier, persist intent, mark SUBMITTING.

        In one transaction (FOR SHARE on the barrier row):
          1. Verify barrier is READY.
          2. INSERT the OrderRequest as PENDING_SUBMIT into orders.
          3. UPDATE admission_status ACQUIRED → SUBMITTING.

        All three commit atomically. After commit, a crash leaves both
        the SUBMITTING status and the PENDING_SUBMIT order row — the
        reconciler can recover the idempotency_key for broker correlation.

        Returns False if barrier not READY, reservation not ACQUIRED/owned,
        or intent INSERT fails (e.g. duplicate idempotency_key).
        """
        conn = self._get_conn()
        req = order_request
        try:
            conn.execute("BEGIN")
            row = conn.execute(
                "SELECT 1 FROM reconciliation_barrier "
                "WHERE id = 1 AND status = 'READY' FOR SHARE",
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return False
            intent = conn.execute(
                """
                INSERT INTO orders (
                    idempotency_key, canonical_pair, broker_symbol, side,
                    volume_lots, stop_loss_price, take_profit_price,
                    signal_timestamp_ms, fresh_quote_bid, fresh_quote_ask,
                    fresh_quote_time_ms, state
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING_SUBMIT')
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                (
                    req.idempotency_key, req.canonical_pair,
                    req.broker_symbol, req.side.value, req.volume_lots,
                    req.stop_loss_price, req.take_profit_price,
                    req.signal_timestamp_ms, req.fresh_quote_bid,
                    req.fresh_quote_ask, req.fresh_quote_time_ms,
                ),
            )
            if intent.rowcount != 1:
                conn.execute("ROLLBACK")
                return False
            status = conn.execute(
                "UPDATE pair_reservations "
                "SET admission_status = 'SUBMITTING' "
                "WHERE canonical_pair = %s AND reserved_by = %s "
                "AND admission_status = 'ACQUIRED'",
                (canonical_pair, self._process_id),
            )
            if status.rowcount != 1:
                conn.execute("ROLLBACK")
                return False
            conn.execute("COMMIT")
            return True
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                self._conn = None
            return False

    def resolve_admission(
        self,
        canonical_pair: str,
        record: OrderRecord,
        position: PositionInfo | None = None,
        override_audit: OverrideAuditRecord | None = None,
    ) -> None:
        """Persist broker outcome and mark admission IDLE — atomically.

        In one transaction:
          1. Upsert OrderRecord (advancing from PENDING_SUBMIT).
          2. If position is provided (FILLED), insert the position row.
          3. If override_audit is provided (OPERATOR_OVERRIDE), insert
             the structured audit record. Failure rolls back everything.
          4. SET admission_status = 'IDLE' on the caller's reservation.

        All steps commit together. If this transaction fails,
        admission_status stays SUBMITTING and the PENDING_SUBMIT row
        survives — the reconciler can correlate.
        """
        req = record.request
        res = record.result
        conn = self._get_conn()
        try:
            conn.execute("BEGIN")
            conn.execute(
                """
                INSERT INTO orders (
                    idempotency_key, canonical_pair, broker_symbol, side,
                    volume_lots, stop_loss_price, take_profit_price,
                    signal_timestamp_ms, fresh_quote_bid, fresh_quote_ask,
                    fresh_quote_time_ms, state, broker_ticket, fill_price,
                    fill_volume, fill_time_ms, reject_reason, broker_retcode,
                    raw_comment
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                )
                ON CONFLICT (idempotency_key) DO UPDATE SET
                    state          = EXCLUDED.state,
                    broker_ticket  = COALESCE(EXCLUDED.broker_ticket, orders.broker_ticket),
                    fill_price     = COALESCE(EXCLUDED.fill_price, orders.fill_price),
                    fill_volume    = COALESCE(EXCLUDED.fill_volume, orders.fill_volume),
                    fill_time_ms   = COALESCE(EXCLUDED.fill_time_ms, orders.fill_time_ms),
                    reject_reason  = COALESCE(EXCLUDED.reject_reason, orders.reject_reason),
                    broker_retcode = COALESCE(EXCLUDED.broker_retcode, orders.broker_retcode),
                    raw_comment    = COALESCE(EXCLUDED.raw_comment, orders.raw_comment),
                    updated_at     = now()
                WHERE (
                    orders.state = EXCLUDED.state
                    OR (orders.state = 'PENDING_SUBMIT' AND EXCLUDED.state IN
                        ('SUBMITTED','FILLED','REJECTED','EXPIRED','FAILED',
                         'UNKNOWN','OPERATOR_OVERRIDE'))
                    OR (orders.state = 'SUBMITTED' AND EXCLUDED.state IN
                        ('FILLED','REJECTED','EXPIRED','UNKNOWN'))
                    OR (orders.state = 'UNKNOWN' AND EXCLUDED.state IN
                        ('SUBMITTED','FILLED','REJECTED','EXPIRED'))
                    OR (orders.state = 'OPERATOR_OVERRIDE' AND EXCLUDED.state IN
                        ('FILLED','REJECTED','EXPIRED'))
                )
                RETURNING state
                """,
                (
                    req.idempotency_key, req.canonical_pair,
                    req.broker_symbol, req.side.value, req.volume_lots,
                    req.stop_loss_price, req.take_profit_price,
                    req.signal_timestamp_ms, req.fresh_quote_bid,
                    req.fresh_quote_ask, req.fresh_quote_time_ms,
                    res.state.value, res.broker_ticket, res.fill_price,
                    res.fill_volume, res.fill_time_ms, res.reject_reason,
                    res.broker_retcode, res.raw_comment,
                ),
            ).fetchone()
            if position is not None:
                conn.execute(
                    """
                    INSERT INTO positions (
                        broker_ticket, canonical_pair, broker_symbol, side,
                        volume_lots, open_price, stop_loss, take_profit,
                        open_time_ms
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (broker_ticket) DO UPDATE SET
                        stop_loss   = EXCLUDED.stop_loss,
                        take_profit = EXCLUDED.take_profit,
                        updated_at  = now()
                    """,
                    (
                        position.broker_ticket, position.canonical_pair,
                        position.broker_symbol, position.side.value,
                        position.volume_lots, position.open_price,
                        position.stop_loss, position.take_profit,
                        position.open_time_ms,
                    ),
                )
            if override_audit is not None:
                conn.execute(
                    """
                    INSERT INTO operator_override_audit
                        (idempotency_key, operator_id, reason,
                         broker_inspection_summary, override_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        override_audit.idempotency_key,
                        override_audit.operator_id,
                        override_audit.reason,
                        override_audit.broker_inspection_summary,
                        override_audit.timestamp_utc,
                    ),
                )
            conn.execute(
                "UPDATE pair_reservations "
                "SET admission_status = 'IDLE' "
                "WHERE canonical_pair = %s AND reserved_by = %s "
                "AND admission_status = 'SUBMITTING'",
                (canonical_pair, self._process_id),
            )
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                self._conn = None

    def load_in_flight_submissions(self) -> list[str]:
        """Return canonical_pairs with admission_status='SUBMITTING'."""
        rows = self._get_conn().execute(
            "SELECT canonical_pair FROM pair_reservations "
            "WHERE admission_status = 'SUBMITTING'",
        ).fetchall()
        return [r["canonical_pair"] for r in rows]


_RECONCILIATION_LOCK_ID = 799_215_217


class PostgresStartupReconciler(StartupReconciler):
    """PostgreSQL-enforced startup reconciliation barrier.

    Uses pg_advisory_lock for exclusive reconciliation and a singleton
    reconciliation_barrier row to gate all acquire() calls system-wide.

    The advisory lock is session-level: if this process crashes, the
    connection drops, the lock is released, and the next process can
    safely acquire it and re-reconcile from scratch.
    """

    def __init__(
        self,
        conninfo: str | None = None,
        process_id: str | None = None,
    ) -> None:
        self._conninfo = conninfo or _conninfo()
        self._process_id = process_id or f"py-{uuid.uuid4().hex[:8]}"
        self._conn: psycopg.Connection | None = None
        self._ready_cached = False

    @property
    def process_id(self) -> str:
        return self._process_id

    def _get_conn(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(
                self._conninfo, row_factory=dict_row, autocommit=True,
            )
        return self._conn

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
            self._conn = None

    def begin(self) -> bool:
        """Acquire exclusive reconciliation lock, set barrier to RECONCILING.

        Uses an explicit transaction with FOR UPDATE on the barrier row.
        The exclusive row lock blocks until every in-flight acquire()
        (which holds FOR SHARE) commits, so load_all_reservations()
        afterward is guaranteed to see every reservation that was
        acquired while the barrier was READY.
        """
        conn = self._get_conn()
        acquired = conn.execute(
            "SELECT pg_try_advisory_lock(%s) AS ok",
            (_RECONCILIATION_LOCK_ID,),
        ).fetchone()
        if not acquired or not acquired["ok"]:
            return False
        try:
            conn.execute("BEGIN")
            # FOR UPDATE blocks until all FOR SHARE holders (in-flight
            # acquires) commit. After this returns, every reservation
            # written by an acquire that saw READY is committed and
            # visible to subsequent reads.
            conn.execute(
                "SELECT 1 FROM reconciliation_barrier WHERE id = 1 FOR UPDATE",
            )
            conn.execute(
                """
                INSERT INTO reconciliation_barrier
                    (id, status, reconciler_id, started_at, completed_at)
                VALUES (1, 'RECONCILING', %s, now(), NULL)
                ON CONFLICT (id) DO UPDATE SET
                    status        = 'RECONCILING',
                    reconciler_id = EXCLUDED.reconciler_id,
                    started_at    = now(),
                    completed_at  = NULL
                """,
                (self._process_id,),
            )
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            try:
                conn.execute(
                    "SELECT pg_advisory_unlock(%s)", (_RECONCILIATION_LOCK_ID,),
                )
            except Exception:
                pass
            return False
        self._ready_cached = False
        return True

    def complete(self) -> None:
        conn = self._get_conn()
        row = conn.execute(
            """
            UPDATE reconciliation_barrier
            SET status = 'READY', completed_at = now()
            WHERE id = 1 AND reconciler_id = %s AND status = 'RECONCILING'
            RETURNING status
            """,
            (self._process_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError(
                "complete() called but this process is not the active reconciler"
            )
        conn.execute(
            "SELECT pg_advisory_unlock(%s)", (_RECONCILIATION_LOCK_ID,),
        )
        self._ready_cached = True

    def is_reconciled(self) -> bool:
        if self._ready_cached:
            return True
        row = self._get_conn().execute(
            "SELECT status FROM reconciliation_barrier WHERE id = 1",
        ).fetchone()
        if row and row["status"] == "READY":
            self._ready_cached = True
            return True
        return False

    def halt_entry_barrier(self) -> bool:
        """Set barrier to a non-READY state after an unresolved fill.

        Uses an independent connection (not the instance's long-lived
        one) so a failed caller transaction cannot roll this back.

        Each attempt runs in a single ``conn.transaction()`` block:
        ``SELECT … FOR UPDATE`` acquires the exclusive row lock, the
        ``UPDATE`` runs under that same lock, and ``COMMIT`` releases
        both atomically. The ``transaction()`` context manager
        guarantees rollback on any exception — no partial state.

        Tries HALTED first (requires migration 006). If the database
        rejects it (CHECK constraint from pre-006 schema), the
        transaction is rolled back completely, and a second attempt
        sets RECONCILING — always in the constraint set, and has the
        same effect: acquire() and gate_submission() both check
        ``status = 'READY'`` and reject anything else.

        The RECONCILING fallback without the advisory lock is equivalent
        to the crash-recovery state: no reconciler is active, the lock
        is free, and the next process that calls begin() acquires it
        and reconciles normally.

        Only transitions from READY. If the barrier is already non-READY,
        entries are already blocked — the UPDATE is a no-op and the
        method returns True (the safety property holds).

        Returns False only when the database is unreachable — in that
        case other processes' DB-backed admission gates also fail.
        """
        for target_status in ('HALTED', 'RECONCILING'):
            conn = None
            try:
                conn = psycopg.connect(self._conninfo, row_factory=dict_row)
                with conn.transaction():
                    conn.execute(
                        "SELECT 1 FROM reconciliation_barrier "
                        "WHERE id = 1 FOR UPDATE",
                    )
                    conn.execute(
                        "UPDATE reconciliation_barrier SET status = %s "
                        "WHERE id = 1 AND status = 'READY'",
                        (target_status,),
                    )
                self._ready_cached = False
                return True
            except Exception:
                continue
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
        self._ready_cached = False
        return False


# ---------------------------------------------------------------------------
# Row → dataclass helpers
# ---------------------------------------------------------------------------

def _row_to_order_record(row: dict) -> OrderRecord:
    return OrderRecord(
        request=OrderRequest(
            canonical_pair=row["canonical_pair"],
            broker_symbol=row["broker_symbol"],
            side=OrderSide(row["side"]),
            volume_lots=Decimal(str(row["volume_lots"])),
            stop_loss_price=Decimal(str(row["stop_loss_price"])),
            take_profit_price=(
                Decimal(str(row["take_profit_price"]))
                if row["take_profit_price"] is not None else None
            ),
            idempotency_key=row["idempotency_key"],
            signal_timestamp_ms=row["signal_timestamp_ms"],
            fresh_quote_bid=Decimal(str(row["fresh_quote_bid"])),
            fresh_quote_ask=Decimal(str(row["fresh_quote_ask"])),
            fresh_quote_time_ms=row["fresh_quote_time_ms"],
        ),
        result=OrderResult(
            state=OrderState(row["state"]),
            broker_ticket=row["broker_ticket"],
            fill_price=(
                Decimal(str(row["fill_price"]))
                if row["fill_price"] is not None else None
            ),
            fill_volume=(
                Decimal(str(row["fill_volume"]))
                if row["fill_volume"] is not None else None
            ),
            fill_time_ms=row["fill_time_ms"],
            reject_reason=row["reject_reason"],
            broker_retcode=row["broker_retcode"],
            raw_comment=row["raw_comment"],
        ),
        created_mono=0.0,
        updated_mono=0.0,
    )


def _row_to_position(row: dict) -> PositionInfo:
    return PositionInfo(
        broker_ticket=row["broker_ticket"],
        canonical_pair=row["canonical_pair"],
        broker_symbol=row["broker_symbol"],
        side=OrderSide(row["side"]),
        volume_lots=Decimal(str(row["volume_lots"])),
        open_price=Decimal(str(row["open_price"])),
        current_price=Decimal(str(row["open_price"])),
        stop_loss=Decimal(str(row["stop_loss"])),
        take_profit=(
            Decimal(str(row["take_profit"]))
            if row["take_profit"] is not None else None
        ),
        floating_pnl_usd=Decimal(0),
        open_time_ms=row["open_time_ms"],
        swap_usd=Decimal(0),
        commission_usd=Decimal(0),
    )
