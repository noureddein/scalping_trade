"""Demo scope gate integration with Phase 5 execution pipeline.

Inserts Demo scope gate check after Phase 5 admission sequence and
before the broker adapter call. On gate fail, blocks order and releases
Phase 5 reservation with structured reason.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .scope import DemoScopeError, DemoScopeGate


class DemoGateResult:
    """Result of a Demo scope gate check in the pipeline."""

    __slots__ = ("passed", "reason", "approval_id")

    def __init__(self, passed: bool, reason: str | None = None, approval_id: Any = None) -> None:
        self.passed = passed
        self.reason = reason
        self.approval_id = approval_id


def check_demo_gate(
    gate: DemoScopeGate,
    *,
    connected_account_id: str,
    account_type_from_broker: str,
    pair: str,
    lot_size: Decimal,
    now: datetime | None = None,
) -> DemoGateResult:
    """Run Demo scope gate check. Returns DemoGateResult (never raises)."""
    try:
        approval = gate.check_gate(
            connected_account_id=connected_account_id,
            account_type_from_broker=account_type_from_broker,
            pair=pair,
            lot_size=lot_size,
            now=now,
        )
        return DemoGateResult(passed=True, approval_id=approval.approval_id)
    except DemoScopeError as e:
        return DemoGateResult(passed=False, reason=e.reason)
