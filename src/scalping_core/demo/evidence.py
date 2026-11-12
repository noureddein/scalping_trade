"""Evidence recording for Demo forward test (Phase 8).

Records every pipeline event to ForwardTestEvent. No silent drops:
if a DB write fails, the failure is logged and queued for recovery.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    SIGNAL_REJECTED = "SIGNAL_REJECTED"
    ENTRY_APPROVED = "ENTRY_APPROVED"
    ENTRY_REJECTED = "ENTRY_REJECTED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_TIMEOUT = "ORDER_TIMEOUT"
    FILL_DISCREPANCY = "FILL_DISCREPANCY"
    COST_RECORDED = "COST_RECORDED"
    SPREAD_AT_DECISION = "SPREAD_AT_DECISION"
    LATENCY_RECORDED = "LATENCY_RECORDED"
    DURATION_EXPIRED = "DURATION_EXPIRED"
    APPROVAL_REVOKED = "APPROVAL_REVOKED"


@dataclass(frozen=True)
class ForwardTestEvent:
    event_id: uuid.UUID
    session_id: uuid.UUID
    event_type: EventType
    timestamp: datetime
    pair: str
    detail: dict[str, Any]
    related_intent_id: uuid.UUID | None = None
    related_signal_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ExecutionDiscrepancy:
    discrepancy_id: uuid.UUID
    session_id: uuid.UUID
    intent_id: uuid.UUID
    expected_price: Decimal
    actual_price: Decimal
    slippage_pips: Decimal
    submission_time: datetime
    fill_time: datetime
    latency_ms: int
    direction: str


class SessionCounters:
    """Mutable counters for an active ForwardTestSession."""

    def __init__(self) -> None:
        self.total_signals: int = 0
        self.total_entries_attempted: int = 0
        self.total_entries_rejected: int = 0
        self.total_fills: int = 0
        self.total_rejections: int = 0


class EvidenceRecorder:
    """Records every pipeline event for a forward test session.

    In-memory event store with no-silent-drop guarantee: failed writes
    are queued in _pending_recovery for retry when the store recovers.
    """

    def __init__(self, session_id: uuid.UUID) -> None:
        self._session_id = session_id
        self._events: list[ForwardTestEvent] = []
        self._discrepancies: list[ExecutionDiscrepancy] = []
        self._pending_recovery: list[ForwardTestEvent] = []
        self._counters = SessionCounters()

    @property
    def session_id(self) -> uuid.UUID:
        return self._session_id

    @property
    def events(self) -> list[ForwardTestEvent]:
        return list(self._events)

    @property
    def discrepancies(self) -> list[ExecutionDiscrepancy]:
        return list(self._discrepancies)

    @property
    def counters(self) -> SessionCounters:
        return self._counters

    @property
    def pending_recovery(self) -> list[ForwardTestEvent]:
        return list(self._pending_recovery)

    def record_event(
        self,
        event_type: EventType,
        pair: str,
        detail: dict[str, Any],
        *,
        related_intent_id: uuid.UUID | None = None,
        related_signal_id: uuid.UUID | None = None,
        timestamp: datetime | None = None,
        store_fn: Any | None = None,
    ) -> ForwardTestEvent:
        """Record a pipeline event. Never silently drops."""
        ts = timestamp or datetime.now(timezone.utc)
        event = ForwardTestEvent(
            event_id=uuid.uuid4(),
            session_id=self._session_id,
            event_type=event_type,
            timestamp=ts,
            pair=pair,
            detail=detail,
            related_intent_id=related_intent_id,
            related_signal_id=related_signal_id,
        )

        self._update_counters(event_type)

        if store_fn is not None:
            try:
                store_fn(event)
            except Exception:
                logger.exception("DB write failed for event %s, queuing for recovery", event.event_id)
                self._pending_recovery.append(event)

        self._events.append(event)
        return event

    def record_discrepancy(
        self,
        *,
        intent_id: uuid.UUID,
        expected_price: Decimal,
        actual_price: Decimal,
        contract_point: Decimal,
        submission_time: datetime,
        fill_time: datetime,
        direction: str,
    ) -> ExecutionDiscrepancy:
        """Record an execution discrepancy (expected vs actual fill price)."""
        slippage_pips = abs(actual_price - expected_price) / contract_point
        latency_ms = int((fill_time - submission_time).total_seconds() * 1000)

        disc = ExecutionDiscrepancy(
            discrepancy_id=uuid.uuid4(),
            session_id=self._session_id,
            intent_id=intent_id,
            expected_price=expected_price,
            actual_price=actual_price,
            slippage_pips=slippage_pips,
            submission_time=submission_time,
            fill_time=fill_time,
            latency_ms=latency_ms,
            direction=direction,
        )
        self._discrepancies.append(disc)

        self.record_event(
            EventType.FILL_DISCREPANCY,
            pair="",
            detail={
                "expected_price": str(expected_price),
                "actual_price": str(actual_price),
                "slippage_pips": str(slippage_pips),
            },
            related_intent_id=intent_id,
        )

        self.record_event(
            EventType.LATENCY_RECORDED,
            pair="",
            detail={"latency_ms": latency_ms},
            related_intent_id=intent_id,
        )

        return disc

    def retry_pending(self, store_fn: Any) -> int:
        """Retry queued events. Returns count of successfully recovered events."""
        recovered = 0
        still_pending: list[ForwardTestEvent] = []
        for event in self._pending_recovery:
            try:
                store_fn(event)
                recovered += 1
            except Exception:
                still_pending.append(event)
        self._pending_recovery = still_pending
        return recovered

    def _update_counters(self, event_type: EventType) -> None:
        if event_type == EventType.SIGNAL_GENERATED:
            self._counters.total_signals += 1
        elif event_type in (EventType.ENTRY_APPROVED, EventType.ENTRY_REJECTED):
            self._counters.total_entries_attempted += 1
            if event_type == EventType.ENTRY_REJECTED:
                self._counters.total_entries_rejected += 1
        elif event_type == EventType.ORDER_FILLED:
            self._counters.total_fills += 1
        elif event_type in (EventType.ORDER_REJECTED, EventType.ORDER_TIMEOUT):
            self._counters.total_rejections += 1
