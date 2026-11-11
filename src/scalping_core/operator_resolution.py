"""Operator resolution for unresolved PENDING_SUBMIT orders.

This module provides a safe, auditable procedure for resolving orders
that are stuck in PENDING_SUBMIT state after a crash or timeout.

PENDING_SUBMIT means: the order intent was persisted and the submission
gate was committed, but the broker outcome was never recorded. The
broker may or may not have received and executed the request.

NEVER resolve automatically. The operator must:
  1. Inspect the broker terminal's order/deal history.
  2. Search for the idempotency_key in the deal comment field.
     The MT5 comment is a BEST-EFFORT search hint only — it may be
     truncated (max 31 chars), modified, or absent. A comment match
     alone does not authorize resolution. The operator must verify
     the deal via authoritative broker fields (ticket, symbol, volume,
     time) before providing evidence.
  3. Determine the authoritative outcome from exact-request terminal
     evidence (broker ticket, order history API with matching request
     identifiers).
  4. Call resolve_pending_submit() with the evidence.

NOT_FOUND is not a valid resolution verdict. Absence from a comment-
based history search does not prove the request cannot still execute.
If the operator cannot find authoritative evidence of a terminal
outcome, the order stays unresolved until either:
  - Authoritative broker evidence surfaces, or
  - The operator uses force_override_unresolved() to explicitly
    override with full audit identity, reason, and evidence.
    NOTE: the override path is currently DISABLED because no operator
    authentication mechanism exists. This is an architecture blocker.

For FILLED resolutions:
  - broker_ticket is required (authoritative deal identifier).
  - The broker outcome and corresponding open position are persisted
    durably BEFORE marking admission IDLE (one transaction).
  - The pair reservation is held until broker-confirmed position closure.

OPERATOR_OVERRIDE semantics:
  - Does NOT imply the broker order reached a terminal outcome.
  - The broker exposure remains unresolved.
  - The reservation is NOT released — the pair stays reserved.
  - Startup reconciliation sees it (not in _TERMINAL_STATES).
  - Allows future transition to FILLED/REJECTED/EXPIRED when broker
    evidence arrives.
  - The audit record is persisted atomically with the state change.
    If the audit insert fails, the override does not take effect.

This module does NOT:
  - Connect to the broker directly
  - Auto-resolve based on timeouts or empty broker queries
  - Modify the database schema
  - Release reservations without persisting the outcome first
  - Treat a comment match as authoritative evidence
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from .execution_engine import DurableStateStore, PairReservationProvider
from .order_types import (
    OrderRecord,
    OrderResult,
    OrderSide,
    OrderState,
    OverrideAuditRecord,
    PositionInfo,
)

log = logging.getLogger(__name__)


class ResolutionVerdict(str, Enum):
    """What the operator determined after broker inspection.

    NOT_FOUND is deliberately excluded. Absence from a comment-based
    history query is not authoritative evidence — the request may still
    be in flight or executed under a different/truncated comment. Use
    force_override_unresolved() if manual override is truly needed.
    """
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class ResolutionEvidence:
    """Operator-provided evidence from broker inspection.

    operator_id is a label identifying who performed the resolution.
    It is NOT an authentication claim — the caller is responsible for
    authenticating the operator via an external mechanism before
    invoking the resolution.

    For FILLED verdicts:
      - broker_ticket is required (authoritative deal identifier).
      - fill_price is required.
      - fill_volume is required.

    raw_comment is informational only. If it does not exactly match
    the idempotency_key, a warning is logged — see
    check_comment_correlation().
    """
    verdict: ResolutionVerdict
    operator_id: str
    broker_ticket: int | None = None
    fill_price: Decimal | None = None
    fill_volume: Decimal | None = None
    fill_time_ms: int | None = None
    broker_retcode: int | None = None
    raw_comment: str | None = None
    operator_notes: str = ""


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    """Outcome of attempting to resolve a PENDING_SUBMIT order."""
    success: bool
    message: str
    idempotency_key: str
    previous_state: OrderState | None = None
    new_state: OrderState | None = None


@dataclass(frozen=True, slots=True)
class CommentCorrelation:
    """Result of checking MT5 comment against idempotency_key."""
    exact_match: bool
    truncated: bool
    prefix_match: bool
    warning: str | None = None


def check_comment_correlation(
    idempotency_key: str,
    raw_comment: str | None,
) -> CommentCorrelation:
    """Check whether an MT5 raw_comment correlates with the idempotency_key.

    The MT5 comment field is max 31 chars and may be truncated or
    modified by the broker. This function detects:
      - Exact match (reliable correlation).
      - Prefix match with truncation (possible but not authoritative).
      - No match (comment was modified or belongs to another order).

    A prefix match means the comment could collide with other keys
    sharing the same prefix. Never use a prefix match alone to
    authorize resolution.
    """
    if raw_comment is None or raw_comment == "":
        return CommentCorrelation(
            exact_match=False, truncated=False, prefix_match=False,
            warning="no comment returned from broker",
        )
    if raw_comment == idempotency_key:
        return CommentCorrelation(
            exact_match=True, truncated=False, prefix_match=True,
        )
    if idempotency_key.startswith(raw_comment) and len(raw_comment) < len(idempotency_key):
        return CommentCorrelation(
            exact_match=False, truncated=True, prefix_match=True,
            warning=(
                f"comment truncated: got {len(raw_comment)} chars, "
                f"key is {len(idempotency_key)} chars — "
                f"possible collision with other keys sharing this prefix"
            ),
        )
    return CommentCorrelation(
        exact_match=False, truncated=False, prefix_match=False,
        warning="comment does not match idempotency_key",
    )


def resolve_pending_submit(
    idempotency_key: str,
    evidence: ResolutionEvidence,
    store: DurableStateStore,
    reservation: PairReservationProvider,
) -> ResolutionResult:
    """Resolve a PENDING_SUBMIT order with operator-provided evidence.

    Steps:
      1. Validate operator identity and evidence completeness.
      2. Load the order and verify it is PENDING_SUBMIT.
      3. Check comment correlation (warning only, not blocking).
      4. Map the verdict to the terminal OrderState.
      5. Persist order result (+ position for FILLED) and mark
         admission IDLE — all via resolve_admission in one transaction.
      6. For non-fill terminal states: release the reservation.
         For FILLED: reservation held until broker-confirmed closure.

    Returns ResolutionResult describing what happened.
    """
    if not evidence.operator_id or not evidence.operator_id.strip():
        return ResolutionResult(
            success=False,
            message="operator_id is required for auditable resolution",
            idempotency_key=idempotency_key,
        )

    if evidence.verdict == ResolutionVerdict.FILLED:
        if evidence.broker_ticket is None:
            return ResolutionResult(
                success=False,
                message="FILLED resolution requires broker_ticket",
                idempotency_key=idempotency_key,
            )
        if evidence.fill_price is None:
            return ResolutionResult(
                success=False,
                message="FILLED resolution requires fill_price",
                idempotency_key=idempotency_key,
            )
        if evidence.fill_volume is None:
            return ResolutionResult(
                success=False,
                message="FILLED resolution requires fill_volume",
                idempotency_key=idempotency_key,
            )

    record = store.load_order(idempotency_key)
    if record is None:
        return ResolutionResult(
            success=False,
            message=f"order {idempotency_key!r} not found in durable store",
            idempotency_key=idempotency_key,
        )

    if record.result.state != OrderState.PENDING_SUBMIT:
        return ResolutionResult(
            success=False,
            message=(
                f"order {idempotency_key!r} is in state "
                f"{record.result.state.value}, not PENDING_SUBMIT"
            ),
            idempotency_key=idempotency_key,
            previous_state=record.result.state,
        )

    # Comment correlation check — warning only, does not block resolution
    correlation = check_comment_correlation(idempotency_key, evidence.raw_comment)
    if correlation.warning:
        log.warning(
            "comment correlation for %s: %s (operator=%s)",
            idempotency_key, correlation.warning, evidence.operator_id,
        )
    if correlation.truncated:
        log.warning(
            "TRUNCATED comment for %s — operator must verify via "
            "authoritative broker fields, not comment alone (operator=%s)",
            idempotency_key, evidence.operator_id,
        )

    new_state = _verdict_to_state(evidence.verdict)
    new_result = OrderResult(
        state=new_state,
        broker_ticket=evidence.broker_ticket,
        fill_price=evidence.fill_price,
        fill_volume=evidence.fill_volume,
        fill_time_ms=evidence.fill_time_ms,
        broker_retcode=evidence.broker_retcode,
        raw_comment=evidence.raw_comment,
    )
    updated = OrderRecord(
        request=record.request,
        result=new_result,
        created_mono=record.created_mono,
        updated_mono=time.monotonic(),
    )

    pair = record.request.canonical_pair

    # Build position for FILLED before resolve_admission so order,
    # position, and IDLE all persist in one transaction.
    position: PositionInfo | None = None
    if new_state == OrderState.FILLED:
        assert evidence.broker_ticket is not None
        assert evidence.fill_price is not None
        assert evidence.fill_volume is not None
        position = PositionInfo(
            broker_ticket=evidence.broker_ticket,
            canonical_pair=pair,
            broker_symbol=record.request.broker_symbol,
            side=record.request.side,
            volume_lots=evidence.fill_volume,
            open_price=evidence.fill_price,
            current_price=evidence.fill_price,
            stop_loss=record.request.stop_loss_price,
            take_profit=record.request.take_profit_price,
            floating_pnl_usd=Decimal(0),
            open_time_ms=evidence.fill_time_ms or record.request.signal_timestamp_ms,
            swap_usd=Decimal(0),
            commission_usd=Decimal(0),
        )

    # Persist order result (+ position for FILLED) and mark admission
    # IDLE — all in one transaction. A crash before commit leaves
    # PENDING_SUBMIT + SUBMITTING for reconciler recovery.
    try:
        reservation.resolve_admission(pair, updated, position=position)
    except Exception as e:
        log.error(
            "resolve_admission failed for %s: %s", idempotency_key, e,
        )
        return ResolutionResult(
            success=False,
            message=f"resolve_admission failed: {e}",
            idempotency_key=idempotency_key,
            previous_state=record.result.state,
        )

    # Release reservation only for terminal non-fill states.
    # FILLED: reservation held until broker-confirmed position closure.
    if new_state != OrderState.FILLED:
        try:
            reservation.release(pair)
        except Exception as e:
            log.warning(
                "reservation release failed for %s: %s",
                pair, e,
            )

    log.info(
        "operator resolved %s: PENDING_SUBMIT → %s "
        "(verdict=%s, operator=%s, notes=%s)",
        idempotency_key, new_state.value,
        evidence.verdict.value, evidence.operator_id, evidence.operator_notes,
    )

    return ResolutionResult(
        success=True,
        message=f"resolved to {new_state.value}",
        idempotency_key=idempotency_key,
        previous_state=OrderState.PENDING_SUBMIT,
        new_state=new_state,
    )


# ---------------------------------------------------------------------------
# Operator override — distinct from evidence-based resolution
# ---------------------------------------------------------------------------

# HARD-DISABLED: no operator authentication mechanism exists.
# The override path accepts an unauthenticated operator_id string.
# Enabling overrides without authentication risks unauditable,
# unattributable state changes on a financial system.
#
# ARCHITECTURE BLOCKER: before setting this to False, implement
# authenticated operator identity (e.g. signed tokens, LDAP bind,
# or equivalent) and bind the override to that identity. Until then,
# force_override_unresolved() refuses all calls.
_OVERRIDE_DISABLED = True


@dataclass(frozen=True, slots=True)
class OverrideEvidence:
    """Required evidence for a force override of an unresolved order.

    This is NOT a "safe" resolution — it is an explicit operator
    decision to unblock admission for an order that lacks authoritative
    terminal evidence. The audit record must be complete: who, why,
    what they checked, and when.

    operator_id is an UNAUTHENTICATED label. The system has no operator
    authentication mechanism. The override path is disabled
    (_OVERRIDE_DISABLED = True) until authenticated operator identity
    is implemented. See the architecture blocker above.

    The order transitions to OPERATOR_OVERRIDE, which:
      - Does NOT imply the broker order reached a terminal outcome.
      - Does NOT release the pair reservation — the broker exposure
        remains unresolved and visible to startup reconciliation.
      - Allows future transition to a broker-confirmed terminal state
        (FILLED, REJECTED, EXPIRED) when evidence arrives.
      - Unblocks admission (SUBMITTING → IDLE) so the admission
        protocol is not permanently stuck.
    """
    operator_id: str
    reason: str
    broker_inspection_summary: str


@dataclass(frozen=True, slots=True)
class OverrideResult:
    """Outcome of a force override attempt."""
    success: bool
    message: str
    idempotency_key: str


def force_override_unresolved(
    idempotency_key: str,
    override: OverrideEvidence,
    store: DurableStateStore,
    reservation: PairReservationProvider,
) -> OverrideResult:
    """Force-override an unresolved PENDING_SUBMIT order.

    DISABLED until operator authentication is implemented. Returns
    failure immediately when _OVERRIDE_DISABLED is True.

    When enabled, this is an auditable escape hatch for orders that
    cannot be resolved via authoritative broker evidence. The operator
    asserts, on their own authority, that the order will never execute.
    If they are wrong, a duplicate entry is possible.

    The order transitions to OPERATOR_OVERRIDE, which:
      - Does NOT claim a broker-confirmed outcome.
      - Does NOT release the reservation — the pair stays reserved
        and the order remains visible to startup reconciliation.
      - Unblocks admission (SUBMITTING → IDLE).
      - Allows future transition to FILLED/REJECTED/EXPIRED when
        broker evidence arrives.

    The state change, audit record, and admission update are persisted
    atomically via resolve_admission. If the audit insert fails, the
    override does not take effect.

    Logs at CRITICAL level for monitoring visibility.
    """
    if _OVERRIDE_DISABLED:
        return OverrideResult(
            success=False,
            message=(
                "operator override is disabled — no operator authentication "
                "mechanism exists. This is an architecture blocker: implement "
                "authenticated operator identity before enabling overrides."
            ),
            idempotency_key=idempotency_key,
        )

    if not override.operator_id or not override.operator_id.strip():
        return OverrideResult(
            success=False,
            message="operator_id is required for override audit trail",
            idempotency_key=idempotency_key,
        )
    if not override.reason or not override.reason.strip():
        return OverrideResult(
            success=False,
            message="reason is required for override audit trail",
            idempotency_key=idempotency_key,
        )
    if not override.broker_inspection_summary or not override.broker_inspection_summary.strip():
        return OverrideResult(
            success=False,
            message="broker_inspection_summary is required for override audit trail",
            idempotency_key=idempotency_key,
        )

    record = store.load_order(idempotency_key)
    if record is None:
        return OverrideResult(
            success=False,
            message=f"order {idempotency_key!r} not found in durable store",
            idempotency_key=idempotency_key,
        )
    if record.result.state != OrderState.PENDING_SUBMIT:
        return OverrideResult(
            success=False,
            message=(
                f"order {idempotency_key!r} is in state "
                f"{record.result.state.value}, not PENDING_SUBMIT"
            ),
            idempotency_key=idempotency_key,
        )

    new_result = OrderResult(state=OrderState.OPERATOR_OVERRIDE)
    updated = OrderRecord(
        request=record.request,
        result=new_result,
        created_mono=record.created_mono,
        updated_mono=time.monotonic(),
    )

    timestamp_utc = _utc_now_iso()
    audit = OverrideAuditRecord(
        idempotency_key=idempotency_key,
        operator_id=override.operator_id,
        reason=override.reason,
        broker_inspection_summary=override.broker_inspection_summary,
        timestamp_utc=timestamp_utc,
    )

    # State change + audit record + admission IDLE — all atomic.
    # If any step fails, the entire transaction rolls back and the
    # order stays PENDING_SUBMIT + SUBMITTING.
    try:
        reservation.resolve_admission(
            record.request.canonical_pair, updated,
            override_audit=audit,
        )
    except Exception as e:
        return OverrideResult(
            success=False,
            message=f"resolve_admission failed (override not applied): {e}",
            idempotency_key=idempotency_key,
        )

    # Reservation is NOT released. The broker outcome is unknown —
    # the pair stays reserved and the OPERATOR_OVERRIDE order remains
    # visible to startup reconciliation via load_non_terminal_orders.

    log.critical(
        "OPERATOR OVERRIDE: %s PENDING_SUBMIT → OPERATOR_OVERRIDE "
        "(broker outcome unknown, reservation held) | "
        "operator=%s | reason=%s | inspection=%s | ts=%s",
        idempotency_key, override.operator_id, override.reason,
        override.broker_inspection_summary, timestamp_utc,
    )

    return OverrideResult(
        success=True,
        message=(
            f"override: OPERATOR_OVERRIDE by {override.operator_id} — "
            f"broker outcome unknown, reservation held for reconciliation"
        ),
        idempotency_key=idempotency_key,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def list_pending_submit_orders(store: DurableStateStore) -> list[OrderRecord]:
    """List all orders stuck in PENDING_SUBMIT for operator review."""
    return [
        r for r in store.load_non_terminal_orders()
        if r.result.state == OrderState.PENDING_SUBMIT
    ]


def _verdict_to_state(verdict: ResolutionVerdict) -> OrderState:
    return {
        ResolutionVerdict.FILLED: OrderState.FILLED,
        ResolutionVerdict.REJECTED: OrderState.REJECTED,
        ResolutionVerdict.EXPIRED: OrderState.EXPIRED,
    }[verdict]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
