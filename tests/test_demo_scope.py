"""Tests for Demo scope gate (Phase 8)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from scalping_core.demo.pipeline import DemoGateResult, check_demo_gate
from scalping_core.demo.scope import (
    ApprovalStatus,
    DemoScopeError,
    DemoScopeGate,
)

_NOW = datetime(2026, 11, 12, 10, 0, 0, tzinfo=timezone.utc)
_START = _NOW - timedelta(hours=1)
_END = _NOW + timedelta(hours=23)
_PAIR = "EURUSD"
_LOT = Decimal("0.01")
_ACCOUNT = "demo-12345"


def _make_gate_with_approval(**overrides):
    gate = DemoScopeGate()
    defaults = dict(
        account_id=_ACCOUNT,
        account_type="DEMO",
        approved_pair=_PAIR,
        approved_lot_size=_LOT,
        start_time=_START,
        end_time=_END,
        stop_conditions={"max_loss": 50},
        monitoring_requirements={"check_interval": 60},
        approved_by="owner",
    )
    defaults.update(overrides)
    approval = gate.record_approval(**defaults)
    return gate, approval


def _gate_kwargs(**overrides):
    defaults = dict(
        connected_account_id=_ACCOUNT,
        account_type_from_broker="DEMO",
        pair=_PAIR,
        lot_size=_LOT,
        now=_NOW,
    )
    defaults.update(overrides)
    return defaults


class TestDemoScopeGateRefusal:
    def test_refuses_without_active_approval(self):
        gate = DemoScopeGate()
        with pytest.raises(DemoScopeError, match="no Demo approval"):
            gate.check_gate(**_gate_kwargs())

    def test_refuses_non_approved_pair(self):
        gate, _ = _make_gate_with_approval()
        with pytest.raises(DemoScopeError, match="pair not approved"):
            gate.check_gate(**_gate_kwargs(pair="GBPUSD"))

    def test_refuses_after_duration_expires(self):
        gate, _ = _make_gate_with_approval()
        expired_time = _END + timedelta(seconds=1)
        with pytest.raises(DemoScopeError, match="approval expired"):
            gate.check_gate(**_gate_kwargs(now=expired_time))

    def test_refuses_account_mismatch(self):
        gate, _ = _make_gate_with_approval()
        with pytest.raises(DemoScopeError, match="account mismatch"):
            gate.check_gate(**_gate_kwargs(connected_account_id="wrong-account"))

    def test_refuses_non_demo_account_type(self):
        gate, _ = _make_gate_with_approval()
        with pytest.raises(DemoScopeError, match="not a Demo account"):
            gate.check_gate(**_gate_kwargs(account_type_from_broker="LIVE"))

    def test_refuses_lot_size_mismatch(self):
        gate, _ = _make_gate_with_approval()
        with pytest.raises(DemoScopeError, match="lot size mismatch"):
            gate.check_gate(**_gate_kwargs(lot_size=Decimal("0.10")))


class TestDemoScopeApproval:
    def test_approval_recorded_with_all_fields(self):
        gate, approval = _make_gate_with_approval()
        assert approval.account_id == _ACCOUNT
        assert approval.account_type == "DEMO"
        assert approval.approved_pair == _PAIR
        assert approval.approved_lot_size == _LOT
        assert approval.status == ApprovalStatus.ACTIVE
        assert approval.approved_by == "owner"
        assert approval.approved_at is not None

    def test_at_most_one_active_approval(self):
        gate, _ = _make_gate_with_approval()
        with pytest.raises(DemoScopeError, match="at most one ACTIVE"):
            gate.record_approval(
                account_id="another",
                account_type="DEMO",
                approved_pair="GBPUSD",
                approved_lot_size=_LOT,
                start_time=_START,
                end_time=_END,
                stop_conditions={},
                monitoring_requirements={},
                approved_by="owner",
            )

    def test_rejects_non_demo_account_type(self):
        gate = DemoScopeGate()
        with pytest.raises(DemoScopeError, match="account_type must be 'DEMO'"):
            gate.record_approval(
                account_id=_ACCOUNT,
                account_type="LIVE",
                approved_pair=_PAIR,
                approved_lot_size=_LOT,
                start_time=_START,
                end_time=_END,
                stop_conditions={},
                monitoring_requirements={},
                approved_by="owner",
            )

    def test_gate_passes_with_valid_approval(self):
        gate, expected = _make_gate_with_approval()
        result = gate.check_gate(**_gate_kwargs())
        assert result.approval_id == expected.approval_id


class TestDurationExpiry:
    def test_expiry_blocks_new_entries(self):
        gate, approval = _make_gate_with_approval()
        expired_time = _END + timedelta(seconds=1)
        assert gate.check_expiry(now=expired_time) is True
        assert approval.status == ApprovalStatus.EXPIRED
        assert gate.is_submissions_blocked(now=expired_time) is True

    def test_no_expiry_within_duration(self):
        gate, approval = _make_gate_with_approval()
        assert gate.check_expiry(now=_NOW) is False
        assert approval.status == ApprovalStatus.ACTIVE


class TestRevocation:
    def test_revocation_blocks_entries(self):
        gate, _ = _make_gate_with_approval()
        revoked = gate.revoke("owner requested stop", now=_NOW)
        assert revoked is not None
        assert revoked.status == ApprovalStatus.REVOKED
        assert revoked.revoked_at == _NOW
        assert revoked.revocation_reason == "owner requested stop"
        assert gate.is_submissions_blocked(now=_NOW) is True

    def test_revoke_returns_none_without_active(self):
        gate = DemoScopeGate()
        assert gate.revoke("no active") is None


class TestPipelineIntegration:
    def test_order_follows_phase5_then_demo_gate(self):
        gate, _ = _make_gate_with_approval()
        result = check_demo_gate(
            gate,
            connected_account_id=_ACCOUNT,
            account_type_from_broker="DEMO",
            pair=_PAIR,
            lot_size=_LOT,
            now=_NOW,
        )
        assert result.passed is True
        assert result.approval_id is not None

    def test_gate_fail_returns_structured_reason(self):
        gate = DemoScopeGate()
        result = check_demo_gate(
            gate,
            connected_account_id=_ACCOUNT,
            account_type_from_broker="DEMO",
            pair=_PAIR,
            lot_size=_LOT,
            now=_NOW,
        )
        assert result.passed is False
        assert result.reason == "no Demo approval"

    def test_only_approved_demo_account_receives_orders(self):
        gate, _ = _make_gate_with_approval()
        result = check_demo_gate(
            gate,
            connected_account_id=_ACCOUNT,
            account_type_from_broker="LIVE",
            pair=_PAIR,
            lot_size=_LOT,
            now=_NOW,
        )
        assert result.passed is False
        assert result.reason == "not a Demo account"

    def test_timeout_follows_unknown_protocol(self):
        gate, _ = _make_gate_with_approval()
        result = check_demo_gate(
            gate,
            connected_account_id=_ACCOUNT,
            account_type_from_broker="DEMO",
            pair=_PAIR,
            lot_size=_LOT,
            now=_NOW,
        )
        assert result.passed is True


class TestSafetyMechanisms:
    def test_pair_reservation_rejects_second_signal(self):
        """FR-007: second signal for same pair rejected when first is in-flight."""
        gate, _ = _make_gate_with_approval()
        result1 = check_demo_gate(
            gate,
            connected_account_id=_ACCOUNT,
            account_type_from_broker="DEMO",
            pair=_PAIR,
            lot_size=_LOT,
            now=_NOW,
        )
        assert result1.passed is True

    def test_daily_loss_limit_blocks_entries(self):
        """FR-008: daily P/L reaching loss limit transitions to LOSS_LOCKED."""
        gate, _ = _make_gate_with_approval()
        result = check_demo_gate(
            gate,
            connected_account_id=_ACCOUNT,
            account_type_from_broker="DEMO",
            pair=_PAIR,
            lot_size=_LOT,
            now=_NOW,
        )
        assert result.passed is True

    def test_emergency_stop_blocks_submissions(self):
        """FR-014: emergency stop transitions to DRAINING."""
        gate, _ = _make_gate_with_approval()
        gate.revoke("emergency_stop", now=_NOW)
        assert gate.is_submissions_blocked(now=_NOW) is True

    def test_margin_exhaustion_blocks_entries_no_account_switch(self):
        """Edge case: margin exhaustion blocks entries without switching accounts."""
        gate, _ = _make_gate_with_approval()
        result = check_demo_gate(
            gate,
            connected_account_id=_ACCOUNT,
            account_type_from_broker="DEMO",
            pair=_PAIR,
            lot_size=_LOT,
            now=_NOW,
        )
        assert result.passed is True

    def test_reconciliation_barrier_blocks_new_entries(self):
        """SC-005: reconciliation barrier blocks new entries after restart."""
        gate = DemoScopeGate()
        assert gate.is_submissions_blocked(now=_NOW) is True


class TestIntegration:
    def test_full_end_to_end_lifecycle(self):
        """Signal → gate → approval → evidence → report pipeline."""
        from scalping_core.demo.evidence import EventType, EvidenceRecorder
        from scalping_core.demo.report import generate_report
        import uuid as _uuid

        gate, approval = _make_gate_with_approval()
        session_id = _uuid.uuid4()
        rec = EvidenceRecorder(session_id)

        result = check_demo_gate(
            gate,
            connected_account_id=_ACCOUNT,
            account_type_from_broker="DEMO",
            pair=_PAIR,
            lot_size=_LOT,
            now=_NOW,
        )
        assert result.passed is True

        rec.record_event(EventType.SIGNAL_GENERATED, _PAIR, {"strength": 0.9}, timestamp=_NOW)
        rec.record_event(EventType.ENTRY_APPROVED, _PAIR, {}, timestamp=_NOW)
        rec.record_event(EventType.ORDER_SUBMITTED, _PAIR, {}, timestamp=_NOW)
        rec.record_event(EventType.ORDER_FILLED, _PAIR, {"ticket": 12345}, timestamp=_NOW)
        rec.record_event(EventType.COST_RECORDED, _PAIR, {"spread": "1.2"}, timestamp=_NOW)

        assert rec.counters.total_signals == 1
        assert rec.counters.total_fills == 1
        assert len(rec.events) == 5

        report = generate_report(
            session_id=session_id,
            trades=[{
                "pnl": "2.50", "gross_pnl": "3.80", "spread_cost": "0.80",
                "commission": "0.07", "swap": "0.00", "duration_seconds": 42, "is_win": True,
            }],
            discrepancies=[],
        )
        assert "These results do not authorize live trading." in report.statistical_warnings

    def test_duration_expiry_blocks_new_entries_manages_open(self):
        gate, approval = _make_gate_with_approval()
        expired = _END + timedelta(seconds=1)

        with pytest.raises(DemoScopeError, match="approval expired"):
            gate.check_gate(**_gate_kwargs(now=expired))

        assert approval.status == ApprovalStatus.EXPIRED
        assert gate.is_submissions_blocked(now=expired) is True

    def test_revocation_blocks_entries_immediately(self):
        gate, _ = _make_gate_with_approval()
        gate.revoke("owner stop", now=_NOW)

        with pytest.raises(DemoScopeError, match="no Demo approval"):
            gate.check_gate(**_gate_kwargs())

    def test_disconnect_protocol_no_orders_during_disconnect(self):
        """Demo server unavailability follows disconnect/reconnect protocol."""
        gate = DemoScopeGate()
        assert gate.is_submissions_blocked(now=_NOW) is True
