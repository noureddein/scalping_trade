"""Tests for Demo evidence recording (Phase 8)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from scalping_core.demo.evidence import (
    EventType,
    EvidenceRecorder,
    ForwardTestEvent,
)

_SESSION = uuid.uuid4()
_NOW = datetime(2026, 11, 12, 10, 0, 0, tzinfo=timezone.utc)
_PAIR = "EURUSD"


def _make_recorder():
    return EvidenceRecorder(_SESSION)


class TestEventRecording:
    def test_every_signal_recorded_regardless_of_outcome(self):
        rec = _make_recorder()
        rec.record_event(EventType.SIGNAL_GENERATED, _PAIR, {"strength": 0.8}, timestamp=_NOW)
        rec.record_event(EventType.SIGNAL_REJECTED, _PAIR, {"reason": "spread_too_wide"}, timestamp=_NOW)
        assert len(rec.events) == 2
        assert rec.events[0].event_type == EventType.SIGNAL_GENERATED
        assert rec.events[1].event_type == EventType.SIGNAL_REJECTED

    def test_rejected_entry_includes_reason_code(self):
        rec = _make_recorder()
        rec.record_event(
            EventType.ENTRY_REJECTED, _PAIR,
            {"reason": "spread_gate", "spread_pips": "2.5"},
            timestamp=_NOW,
        )
        assert rec.events[0].detail["reason"] == "spread_gate"

    def test_completed_trade_records_all_cost_components(self):
        rec = _make_recorder()
        rec.record_event(
            EventType.COST_RECORDED, _PAIR,
            {"spread": "1.2", "commission": "0.07", "swap": "0.0", "slippage": "0.3"},
            timestamp=_NOW,
        )
        detail = rec.events[0].detail
        assert "spread" in detail
        assert "commission" in detail
        assert "swap" in detail
        assert "slippage" in detail

    def test_fill_discrepancy_recorded_with_both_values(self):
        rec = _make_recorder()
        intent_id = uuid.uuid4()
        disc = rec.record_discrepancy(
            intent_id=intent_id,
            expected_price=Decimal("1.10000"),
            actual_price=Decimal("1.10005"),
            contract_point=Decimal("0.00001"),
            submission_time=_NOW,
            fill_time=_NOW + timedelta(milliseconds=120),
            direction="BUY",
        )
        assert disc.expected_price == Decimal("1.10000")
        assert disc.actual_price == Decimal("1.10005")
        assert disc.slippage_pips == Decimal("5")
        assert disc.latency_ms == 120

    def test_no_event_silently_dropped(self):
        rec = _make_recorder()
        for et in [EventType.SIGNAL_GENERATED, EventType.ENTRY_APPROVED,
                    EventType.ORDER_SUBMITTED, EventType.ORDER_FILLED]:
            rec.record_event(et, _PAIR, {}, timestamp=_NOW)
        assert len(rec.events) == 4

    def test_session_counters_updated_correctly(self):
        rec = _make_recorder()
        rec.record_event(EventType.SIGNAL_GENERATED, _PAIR, {}, timestamp=_NOW)
        rec.record_event(EventType.SIGNAL_GENERATED, _PAIR, {}, timestamp=_NOW)
        rec.record_event(EventType.ENTRY_APPROVED, _PAIR, {}, timestamp=_NOW)
        rec.record_event(EventType.ENTRY_REJECTED, _PAIR, {"reason": "spread"}, timestamp=_NOW)
        rec.record_event(EventType.ORDER_FILLED, _PAIR, {}, timestamp=_NOW)
        rec.record_event(EventType.ORDER_REJECTED, _PAIR, {}, timestamp=_NOW)
        c = rec.counters
        assert c.total_signals == 2
        assert c.total_entries_attempted == 2
        assert c.total_entries_rejected == 1
        assert c.total_fills == 1
        assert c.total_rejections == 1

    def test_db_write_failure_logged_and_recovered(self):
        rec = _make_recorder()
        call_count = 0

        def failing_store(event):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                raise ConnectionError("DB unavailable")

        rec.record_event(
            EventType.SIGNAL_GENERATED, _PAIR, {},
            timestamp=_NOW, store_fn=failing_store,
        )
        assert len(rec.pending_recovery) == 1
        assert len(rec.events) == 1

        recovered = rec.retry_pending(lambda e: None)
        assert recovered == 1
        assert len(rec.pending_recovery) == 0
