"""Demo scope approval gate (Phase 8).

Enforces Constitution Principle III: no order submission without explicit
owner-recorded DemoScopeApproval. Checks run on startup and before every
order. Any gate failure blocks the order and releases the Phase 5 reservation.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any


class ApprovalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


@dataclass
class DemoScopeApproval:
    approval_id: uuid.UUID
    account_id: str
    account_type: str
    approved_pair: str
    approved_lot_size: Decimal
    start_time: datetime
    end_time: datetime
    stop_conditions: dict[str, Any]
    monitoring_requirements: dict[str, Any]
    status: ApprovalStatus
    approved_by: str
    approved_at: datetime
    revoked_at: datetime | None = None
    revocation_reason: str | None = None


class DemoScopeError(Exception):
    """Raised when a Demo scope gate check fails."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class DemoScopeGate:
    """In-memory Demo scope gate. Enforces all checks per demo-scope.md."""

    def __init__(self) -> None:
        self._approvals: dict[uuid.UUID, DemoScopeApproval] = {}

    def record_approval(
        self,
        *,
        account_id: str,
        account_type: str,
        approved_pair: str,
        approved_lot_size: Decimal,
        start_time: datetime,
        end_time: datetime,
        stop_conditions: dict[str, Any],
        monitoring_requirements: dict[str, Any],
        approved_by: str,
    ) -> DemoScopeApproval:
        if account_type != "DEMO":
            raise DemoScopeError("account_type must be 'DEMO'")
        if end_time <= start_time:
            raise DemoScopeError("end_time must be after start_time")
        if not account_id or not approved_pair or not approved_by:
            raise DemoScopeError("account_id, approved_pair, and approved_by are required")

        active = self._get_active()
        if active is not None:
            raise DemoScopeError("at most one ACTIVE approval at a time")

        approval = DemoScopeApproval(
            approval_id=uuid.uuid4(),
            account_id=account_id,
            account_type=account_type,
            approved_pair=approved_pair,
            approved_lot_size=approved_lot_size,
            start_time=start_time,
            end_time=end_time,
            stop_conditions=stop_conditions,
            monitoring_requirements=monitoring_requirements,
            status=ApprovalStatus.ACTIVE,
            approved_by=approved_by,
            approved_at=datetime.now(timezone.utc),
        )
        self._approvals[approval.approval_id] = approval
        return approval

    def _get_active(self) -> DemoScopeApproval | None:
        for a in self._approvals.values():
            if a.status == ApprovalStatus.ACTIVE:
                return a
        return None

    def get_active_approval(self) -> DemoScopeApproval | None:
        return self._get_active()

    def check_gate(
        self,
        *,
        connected_account_id: str,
        account_type_from_broker: str,
        pair: str,
        lot_size: Decimal,
        now: datetime | None = None,
    ) -> DemoScopeApproval:
        """Run all gate checks. Returns the approval on success, raises DemoScopeError on failure."""
        now = now or datetime.now(timezone.utc)

        active = self._get_active()
        if active is None:
            raise DemoScopeError("no Demo approval")

        if now > active.end_time:
            self._expire(active, now)
            raise DemoScopeError("approval expired")

        if now < active.start_time:
            raise DemoScopeError("approval not yet active")

        if account_type_from_broker != "DEMO":
            raise DemoScopeError("not a Demo account")

        if connected_account_id != active.account_id:
            raise DemoScopeError("account mismatch")

        if pair != active.approved_pair:
            raise DemoScopeError("pair not approved")

        if lot_size != active.approved_lot_size:
            raise DemoScopeError("lot size mismatch")

        return active

    def check_expiry(self, now: datetime | None = None) -> bool:
        """Check and handle duration expiry. Returns True if expired."""
        now = now or datetime.now(timezone.utc)
        active = self._get_active()
        if active is None:
            return False
        if now > active.end_time:
            self._expire(active, now)
            return True
        return False

    def _expire(self, approval: DemoScopeApproval, now: datetime) -> None:
        approval.status = ApprovalStatus.EXPIRED

    def revoke(self, reason: str, now: datetime | None = None) -> DemoScopeApproval | None:
        """Owner revokes the active approval. Returns the revoked approval or None."""
        now = now or datetime.now(timezone.utc)
        active = self._get_active()
        if active is None:
            return None
        active.status = ApprovalStatus.REVOKED
        active.revoked_at = now
        active.revocation_reason = reason
        return active

    def is_submissions_blocked(self, now: datetime | None = None) -> bool:
        """True when new order submissions should be blocked."""
        now = now or datetime.now(timezone.utc)
        active = self._get_active()
        if active is None:
            return True
        if now > active.end_time:
            self._expire(active, now)
            return True
        return False
