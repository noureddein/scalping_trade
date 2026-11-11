"""Startup supervisor — orchestrates account verification and reconciliation.

Implements the full StartupReconciler lifecycle documented in
execution_engine.py: account binding, barrier acquisition, in-flight
drain, reservation/order/position/risk reconciliation, and barrier
release.

Fail-closed: any error or ambiguity leaves the barrier at RECONCILING
and entries blocked. The supervisor never proceeds to READY with
unresolved state.

NON-TRADING: does not submit orders. Queries the broker (via
ExecutionAdapter) only for read-only reconciliation — open positions,
order history, deal lookup. Live execution is not enabled by this
module.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from .broker_types import AccountInfo
from .daily_risk import DailyPnL, DailyRiskConfig, ZERO_PNL, trading_day
from .execution_adapter import ExecutionAdapter
from .execution_engine import (
    DurableStateStore,
    PairReservationProvider,
    StartupReconciler,
)
from .order_types import OrderState, is_terminal
from .risk_gate import RiskState

log = logging.getLogger(__name__)


class SupervisorOutcome(str, Enum):
    READY = "READY"
    NOT_RECONCILER = "NOT_RECONCILER"
    UNRESOLVED_SUBMISSIONS = "UNRESOLVED_SUBMISSIONS"
    UNRESOLVED_ORDERS = "UNRESOLVED_ORDERS"
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    ERROR = "ERROR"


class StartupSupervisor:
    """Orchestrates the full startup reconciliation sequence.

    Usage::

        supervisor = StartupSupervisor(store, reservation, reconciler, adapter)
        outcome = supervisor.run(account_id="12345")

    The engine should only activate after outcome == READY.
    """

    def __init__(
        self,
        store: DurableStateStore,
        reservation: PairReservationProvider,
        reconciler: StartupReconciler,
        adapter: ExecutionAdapter,
        *,
        drain_poll_interval_s: float = 0.5,
        drain_timeout_s: float = 30.0,
        risk_config: DailyRiskConfig | None = None,
    ) -> None:
        self._store = store
        self._reservation = reservation
        self._reconciler = reconciler
        self._adapter = adapter
        self._drain_poll_interval_s = drain_poll_interval_s
        self._drain_timeout_s = drain_timeout_s
        self._risk_config = risk_config or DailyRiskConfig()

    def run(self, account_id: str) -> SupervisorOutcome:
        """Execute the full startup sequence. Returns outcome."""
        # Step 0: verify database health
        if not self._store.is_available():
            log.error("durable store unavailable")
            return SupervisorOutcome.ERROR
        if not self._reservation.is_available():
            log.error("reservation provider unavailable")
            return SupervisorOutcome.ERROR

        # Step 1: account binding
        try:
            self._store.verify_account(account_id)
        except Exception as e:
            log.error("account verification failed: %s", e)
            return SupervisorOutcome.ACCOUNT_MISMATCH

        # Step 2: acquire reconciliation barrier
        if not self._reconciler.begin():
            log.info("another process holds the reconciliation lock")
            return SupervisorOutcome.NOT_RECONCILER

        log.info("reconciliation barrier acquired, starting reconciliation")

        try:
            return self._reconcile()
        except Exception:
            log.exception("reconciliation failed — barrier stays RECONCILING")
            return SupervisorOutcome.ERROR

    def _reconcile(self) -> SupervisorOutcome:
        # Step 2a: drain in-flight SUBMITTING entries
        outcome = self._drain_in_flight()
        if outcome is not None:
            return outcome

        # Step 2b: reconcile reservations
        self._reconcile_reservations()

        # Step 2c: reconcile orders
        unresolved = self._reconcile_orders()
        if unresolved:
            log.error(
                "unresolved non-terminal orders after reconciliation: %s",
                [r.request.idempotency_key for r in unresolved],
            )
            return SupervisorOutcome.UNRESOLVED_ORDERS

        # Step 2d: reconcile positions
        self._reconcile_positions()

        # Step 2e: reconcile daily risk state
        self._reconcile_risk()

        # Step 2f: all clear — mark READY
        self._reconciler.complete()
        log.info("reconciliation complete, barrier set to READY")
        return SupervisorOutcome.READY

    def _drain_in_flight(self) -> SupervisorOutcome | None:
        """Poll SUBMITTING entries until drained or timeout.

        Returns None if drained successfully. Returns UNRESOLVED_SUBMISSIONS
        if entries survive the timeout — barrier stays RECONCILING.
        """
        deadline = time.monotonic() + self._drain_timeout_s
        while True:
            in_flight = self._reservation.load_in_flight_submissions()
            if not in_flight:
                return None
            if time.monotonic() >= deadline:
                log.error(
                    "in-flight submissions not resolved after %.1fs: %s — "
                    "barrier stays RECONCILING, manual intervention required",
                    self._drain_timeout_s,
                    in_flight,
                )
                return SupervisorOutcome.UNRESOLVED_SUBMISSIONS
            time.sleep(self._drain_poll_interval_s)

    def _reconcile_reservations(self) -> None:
        """Reconcile each reservation against broker state."""
        reservations = self._reservation.load_all_reservations()
        for pair, owner in reservations:
            # Check if there's an open position for this pair
            positions = self._adapter.get_open_positions(pair)
            if positions:
                log.info("pair %s has open position(s) — adopting reservation", pair)
                self._reservation.adopt(pair)
                continue

            # Check if there's a non-terminal order for this pair
            orders = self._store.load_non_terminal_orders()
            has_pending = any(
                o.request.canonical_pair == pair for o in orders
            )
            if has_pending:
                log.info("pair %s has non-terminal order — adopting reservation", pair)
                self._reservation.adopt(pair)
                continue

            # Broker confirms pair is clear
            log.info("pair %s clear at broker — releasing reservation", pair)
            self._reservation.force_release(pair)

    def _reconcile_orders(self) -> list:
        """Reconcile non-terminal orders against broker. Returns unresolved."""
        orders = self._store.load_non_terminal_orders()
        unresolved = []
        for record in orders:
            state = record.result.state
            ticket = record.result.broker_ticket

            if state == OrderState.PENDING_SUBMIT:
                # Intent was persisted but broker may not have received it.
                # Cannot determine outcome without authoritative correlation.
                # MT5 comment field is not authoritative — fail closed.
                log.warning(
                    "order %s stuck at PENDING_SUBMIT — unresolved, "
                    "requires manual broker inspection",
                    record.request.idempotency_key,
                )
                unresolved.append(record)
                continue

            if ticket is not None:
                try:
                    result = self._adapter.query_order(ticket)
                except Exception:
                    log.warning(
                        "broker query failed for ticket %d — unresolved",
                        ticket,
                    )
                    unresolved.append(record)
                    continue

                if is_terminal(result.state):
                    from .order_types import OrderRecord
                    updated = OrderRecord(
                        request=record.request,
                        result=result,
                        created_mono=record.created_mono,
                        updated_mono=time.monotonic(),
                    )
                    try:
                        self._store.save_order(updated)
                    except Exception:
                        log.warning(
                            "failed to persist reconciled order %s",
                            record.request.idempotency_key,
                        )
                        unresolved.append(record)
                        continue
                    log.info(
                        "order %s reconciled: %s → %s",
                        record.request.idempotency_key,
                        state.value,
                        result.state.value,
                    )
                else:
                    log.warning(
                        "order %s still non-terminal at broker: %s",
                        record.request.idempotency_key,
                        result.state.value,
                    )
                    unresolved.append(record)
            else:
                # No broker ticket — UNKNOWN without correlation
                log.warning(
                    "order %s has no broker ticket — unresolved",
                    record.request.idempotency_key,
                )
                unresolved.append(record)

        return unresolved

    def _reconcile_positions(self) -> None:
        """Persist broker-reported open positions to durable store."""
        reservations = self._reservation.load_all_reservations()
        for pair, _owner in reservations:
            positions = self._adapter.get_open_positions(pair)
            for pos in positions:
                self._store.save_position(pos)
                log.info(
                    "position ticket=%d pair=%s persisted from broker",
                    pos.broker_ticket,
                    pair,
                )

    def _reconcile_risk(self) -> None:
        """Ensure today's risk state exists in durable store."""
        today = trading_day(datetime.now(timezone.utc))
        snapshot = self._store.load_risk_snapshot(today)
        if snapshot is None:
            self._store.save_risk_snapshot(today, RiskState.ACTIVE, ZERO_PNL)
            log.info("initialized risk state for trading day %s", today)
        else:
            state, pnl = snapshot
            log.info(
                "existing risk state for %s: %s (net %.2f)",
                today,
                state.value,
                pnl.net_pnl_usd,
            )
