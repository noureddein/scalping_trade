"""Order lifecycle manager (§8 steps 14–16).

Tracks orders from intent through submission to terminal state.
Enforces idempotency (one order per idempotency_key), detects ambiguous
broker responses, and supports reconciliation queries.

Pure in-memory — no persistence. In-memory idempotency alone is NOT
sufficient across process restarts: a restart loses all order state,
making duplicate submissions possible. A future phase adds durable
backing (decision #8). Until a DurableStateStore is injected into
ExecutionEngine, the engine remains inactive.

An order remains PENDING or UNKNOWN until a confirmed broker deal/fill
is reconciled. Request acceptance (SUBMITTED) does not mean FILLED.
"""
from __future__ import annotations

import time

from .order_types import OrderRecord, OrderRequest, OrderResult, OrderState, is_terminal
from .execution_adapter import ExecutionAdapter


class OrderManager:
    """Manages order lifecycle with idempotency and reconciliation."""

    def __init__(self) -> None:
        self._by_key: dict[str, OrderRecord] = {}
        self._by_ticket: dict[int, str] = {}

    @property
    def pending_count(self) -> int:
        return sum(1 for r in self._by_key.values() if not is_terminal(r.result.state))

    @property
    def records(self) -> dict[str, OrderRecord]:
        return dict(self._by_key)

    def has_pending_for_pair(self, canonical_pair: str) -> bool:
        return any(
            r.request.canonical_pair == canonical_pair
            and not is_terminal(r.result.state)
            for r in self._by_key.values()
        )

    def submit(self, request: OrderRequest, adapter: ExecutionAdapter) -> OrderRecord:
        """Submit an order. Returns existing record if idempotency_key seen before."""
        existing = self._by_key.get(request.idempotency_key)
        if existing is not None:
            return existing

        now = time.monotonic()
        pending = OrderRecord(
            request=request,
            result=OrderResult(state=OrderState.PENDING_SUBMIT),
            created_mono=now,
            updated_mono=now,
        )
        self._by_key[request.idempotency_key] = pending

        result = adapter.submit_order(request)
        record = OrderRecord(
            request=request,
            result=result,
            created_mono=now,
            updated_mono=time.monotonic(),
        )
        self._by_key[request.idempotency_key] = record
        if result.broker_ticket is not None:
            self._by_ticket[result.broker_ticket] = request.idempotency_key
        return record

    def reconcile(self, idempotency_key: str, adapter: ExecutionAdapter) -> OrderRecord | None:
        """Re-query broker for an order's current state. Returns None if key unknown."""
        record = self._by_key.get(idempotency_key)
        if record is None:
            return None
        if is_terminal(record.result.state):
            return record
        ticket = record.result.broker_ticket
        if ticket is None:
            updated = OrderRecord(
                request=record.request,
                result=OrderResult(state=OrderState.UNKNOWN,
                                   reject_reason="no_broker_ticket_for_reconciliation"),
                created_mono=record.created_mono,
                updated_mono=time.monotonic(),
            )
            self._by_key[idempotency_key] = updated
            return updated

        result = adapter.query_order(ticket)
        updated = OrderRecord(
            request=record.request,
            result=result,
            created_mono=record.created_mono,
            updated_mono=time.monotonic(),
        )
        self._by_key[idempotency_key] = updated
        return updated

    def get_by_key(self, idempotency_key: str) -> OrderRecord | None:
        return self._by_key.get(idempotency_key)

    def get_by_ticket(self, broker_ticket: int) -> OrderRecord | None:
        key = self._by_ticket.get(broker_ticket)
        if key is None:
            return None
        return self._by_key.get(key)
