"""Tests for operator resolution of PENDING_SUBMIT orders.

PREPARED — NOT YET RUN. Deferred until market open per owner decision.
"""
import time
from decimal import Decimal
from unittest.mock import patch

from scalping_core.execution_engine import PairReservationProvider
from scalping_core.operator_resolution import (
    OverrideEvidence,
    OverrideResult,
    ResolutionEvidence,
    ResolutionVerdict,
    _OVERRIDE_DISABLED,
    force_override_unresolved,
    list_pending_submit_orders,
    resolve_pending_submit,
)
from scalping_core.order_types import (
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


# ---------------------------------------------------------------------------
# Minimal test doubles
# ---------------------------------------------------------------------------

def _request(pair="EURUSD", key="test:1700000000000:abc"):
    return OrderRequest(
        canonical_pair=pair, broker_symbol=pair,
        side=OrderSide.BUY, volume_lots=Decimal("0.01"),
        stop_loss_price=Decimal("1.09"), take_profit_price=None,
        idempotency_key=key, signal_timestamp_ms=1700000000000,
        fresh_quote_bid=Decimal("1.10"), fresh_quote_ask=Decimal("1.1002"),
        fresh_quote_time_ms=1700000000000,
    )


def _pending_record(key="test:1700000000000:abc"):
    return OrderRecord(
        request=_request(key=key),
        result=OrderResult(state=OrderState.PENDING_SUBMIT),
        created_mono=0.0, updated_mono=0.0,
    )


class _MemStore:
    def __init__(self):
        self._orders = {}
        self._positions = {}

    def is_available(self):
        return True

    def load_order(self, key):
        return self._orders.get(key)

    def save_order(self, record):
        existing = self._orders.get(record.request.idempotency_key)
        if existing is not None:
            if not is_valid_transition(existing.result.state, record.result.state):
                raise StaleOrderStateError(
                    record.request.idempotency_key,
                    record.result.state, existing.result.state,
                )
        self._orders[record.request.idempotency_key] = record

    def load_non_terminal_orders(self):
        return [r for r in self._orders.values() if not is_terminal(r.result.state)]

    def save_risk_snapshot(self, *a): pass
    def load_risk_snapshot(self, *a): return None
    def save_position(self, pos): self._positions[pos.broker_ticket] = pos
    def load_open_positions(self): return list(self._positions.values())
    def mark_position_closed(self, *a): pass
    def verify_account(self, *a): pass


class _MemReservation:
    def __init__(self):
        self._held = {}
        self._admission = {}
        self._override_audits = []
        self._store = None

    def is_available(self):
        return True

    def acquire(self, pair):
        if pair in self._held:
            return False
        self._held[pair] = "test"
        self._admission[pair] = "ACQUIRED"
        return True

    def release(self, pair):
        self._held.pop(pair, None)
        self._admission.pop(pair, None)

    def gate_submission(self, pair, order_request=None):
        if self._admission.get(pair) != "ACQUIRED":
            return False
        self._admission[pair] = "SUBMITTING"
        return True

    def resolve_admission(self, pair, record=None, position=None, override_audit=None):
        if record is not None and self._store is not None:
            self._store._orders[record.request.idempotency_key] = record
        if position is not None and self._store is not None:
            self._store._positions[position.broker_ticket] = position
        if override_audit is not None:
            self._override_audits.append(override_audit)
        if self._admission.get(pair) == "SUBMITTING":
            self._admission[pair] = "IDLE"

    def load_all_reservations(self):
        return [(p, o) for p, o in self._held.items()]

    def adopt(self, pair): return True
    def force_release(self, pair): self._held.pop(pair, None)
    def load_in_flight_submissions(self):
        return [p for p, s in self._admission.items() if s == "SUBMITTING"]


def _linked_fixtures():
    store = _MemStore()
    reservation = _MemReservation()
    reservation._store = store
    return store, reservation


# ---------------------------------------------------------------------------
# Tests: resolve_pending_submit
# ---------------------------------------------------------------------------

def test_resolve_filled():
    store, reservation = _linked_fixtures()
    key = "test:1700000000000:abc"
    store._orders[key] = _pending_record(key)
    reservation._held["EURUSD"] = "test"
    reservation._admission["EURUSD"] = "SUBMITTING"

    evidence = ResolutionEvidence(
        verdict=ResolutionVerdict.FILLED,
        operator_id="ops_admin",
        broker_ticket=5001,
        fill_price=Decimal("1.10015"),
        fill_volume=Decimal("0.01"),
        operator_notes="confirmed in MT5 journal",
    )
    result = resolve_pending_submit(key, evidence, store, reservation)

    assert result.success
    assert result.new_state == OrderState.FILLED
    assert store._orders[key].result.state == OrderState.FILLED
    assert store._orders[key].result.broker_ticket == 5001
    assert reservation._admission.get("EURUSD") == "IDLE"
    assert "EURUSD" in reservation._held


def test_resolve_filled_persists_position_atomically():
    """FILLED resolution persists position in the same resolve_admission call."""
    store, reservation = _linked_fixtures()
    key = "test:fill_pos"
    store._orders[key] = _pending_record(key)
    reservation._held["EURUSD"] = "test"
    reservation._admission["EURUSD"] = "SUBMITTING"

    evidence = ResolutionEvidence(
        verdict=ResolutionVerdict.FILLED,
        operator_id="ops_admin",
        broker_ticket=9001,
        fill_price=Decimal("1.10015"),
        fill_volume=Decimal("0.01"),
    )
    result = resolve_pending_submit(key, evidence, store, reservation)

    assert result.success
    assert 9001 in store._positions
    pos = store._positions[9001]
    assert pos.canonical_pair == "EURUSD"
    assert pos.open_price == Decimal("1.10015")


def test_resolve_rejected():
    store, reservation = _linked_fixtures()
    key = "test:rej"
    store._orders[key] = _pending_record(key)
    reservation._held["EURUSD"] = "test"
    reservation._admission["EURUSD"] = "SUBMITTING"

    evidence = ResolutionEvidence(
        verdict=ResolutionVerdict.REJECTED,
        operator_id="ops_admin",
        operator_notes="broker log shows no_money",
    )
    result = resolve_pending_submit(key, evidence, store, reservation)

    assert result.success
    assert result.new_state == OrderState.REJECTED
    assert "EURUSD" not in reservation._held


def test_not_found_verdict_does_not_exist():
    """NOT_FOUND was removed from ResolutionVerdict — it is not a valid option."""
    assert not hasattr(ResolutionVerdict, "NOT_FOUND")


def test_resolve_requires_operator_id():
    store, reservation = _linked_fixtures()
    key = "test:noid"
    store._orders[key] = _pending_record(key)

    evidence = ResolutionEvidence(
        verdict=ResolutionVerdict.REJECTED,
        operator_id="",
    )
    result = resolve_pending_submit(key, evidence, store, reservation)

    assert not result.success
    assert "operator_id" in result.message


def test_resolve_filled_requires_broker_ticket():
    store, reservation = _linked_fixtures()
    key = "test:noticket"
    store._orders[key] = _pending_record(key)

    evidence = ResolutionEvidence(
        verdict=ResolutionVerdict.FILLED,
        operator_id="ops_admin",
        fill_price=Decimal("1.10"),
        fill_volume=Decimal("0.01"),
    )
    result = resolve_pending_submit(key, evidence, store, reservation)

    assert not result.success
    assert "broker_ticket" in result.message


def test_resolve_order_not_found():
    store, reservation = _linked_fixtures()

    result = resolve_pending_submit("nonexistent", ResolutionEvidence(
        verdict=ResolutionVerdict.REJECTED, operator_id="ops"), store, reservation)

    assert not result.success
    assert "not found" in result.message


def test_resolve_wrong_state():
    """Cannot resolve an order that is already terminal."""
    store, reservation = _linked_fixtures()
    key = "test:filled"
    store._orders[key] = OrderRecord(
        request=_request(key=key),
        result=OrderResult(state=OrderState.FILLED, broker_ticket=1),
        created_mono=0.0, updated_mono=0.0,
    )

    result = resolve_pending_submit(key, ResolutionEvidence(
        verdict=ResolutionVerdict.REJECTED, operator_id="ops"), store, reservation)

    assert not result.success
    assert "not PENDING_SUBMIT" in result.message


def test_list_pending_submit_orders():
    store = _MemStore()
    pending = _pending_record("k1")
    filled = OrderRecord(
        request=_request(key="k2"),
        result=OrderResult(state=OrderState.FILLED, broker_ticket=1),
        created_mono=0.0, updated_mono=0.0,
    )
    store._orders["k1"] = pending
    store._orders["k2"] = filled

    result = list_pending_submit_orders(store)
    assert len(result) == 1
    assert result[0].request.idempotency_key == "k1"


# ---------------------------------------------------------------------------
# Tests: force_override_unresolved
# ---------------------------------------------------------------------------

def test_override_disabled_by_default():
    """Override path is disabled — returns failure without touching state."""
    assert _OVERRIDE_DISABLED is True

    store, reservation = _linked_fixtures()
    key = "test:disabled"
    store._orders[key] = _pending_record(key)
    reservation._held["EURUSD"] = "test"
    reservation._admission["EURUSD"] = "SUBMITTING"

    override = OverrideEvidence(
        operator_id="ops_admin",
        reason="no matching deal",
        broker_inspection_summary="checked history",
    )
    result = force_override_unresolved(key, override, store, reservation)

    assert not result.success
    assert "disabled" in result.message
    assert "authentication" in result.message
    # State unchanged
    assert store._orders[key].result.state == OrderState.PENDING_SUBMIT
    # Reservation unchanged
    assert "EURUSD" in reservation._held
    assert reservation._admission["EURUSD"] == "SUBMITTING"


@patch("scalping_core.operator_resolution._OVERRIDE_DISABLED", False)
def test_override_uses_operator_override_state():
    """When enabled, override transitions to OPERATOR_OVERRIDE."""
    store, reservation = _linked_fixtures()
    key = "test:override"
    store._orders[key] = _pending_record(key)
    reservation._held["EURUSD"] = "test"
    reservation._admission["EURUSD"] = "SUBMITTING"

    override = OverrideEvidence(
        operator_id="ops_admin",
        reason="broker terminal shows no matching deal after 24h",
        broker_inspection_summary="checked order history, deal history",
    )
    result = force_override_unresolved(key, override, store, reservation)

    assert result.success
    assert "OPERATOR_OVERRIDE" in result.message
    assert store._orders[key].result.state == OrderState.OPERATOR_OVERRIDE


@patch("scalping_core.operator_resolution._OVERRIDE_DISABLED", False)
def test_override_does_not_release_reservation():
    """Override keeps reservation held — broker outcome is unknown."""
    store, reservation = _linked_fixtures()
    key = "test:norerelease"
    store._orders[key] = _pending_record(key)
    reservation._held["EURUSD"] = "test"
    reservation._admission["EURUSD"] = "SUBMITTING"

    override = OverrideEvidence(
        operator_id="ops_admin",
        reason="no match",
        broker_inspection_summary="checked",
    )
    force_override_unresolved(key, override, store, reservation)

    # Reservation held, admission resolved to IDLE
    assert "EURUSD" in reservation._held
    assert reservation._admission.get("EURUSD") == "IDLE"


@patch("scalping_core.operator_resolution._OVERRIDE_DISABLED", False)
def test_override_persists_audit_atomically():
    """Audit record is passed to resolve_admission for atomic persistence."""
    store, reservation = _linked_fixtures()
    key = "test:audit"
    store._orders[key] = _pending_record(key)
    reservation._held["EURUSD"] = "test"
    reservation._admission["EURUSD"] = "SUBMITTING"

    override = OverrideEvidence(
        operator_id="ops_admin",
        reason="no matching deal",
        broker_inspection_summary="checked history API",
    )
    result = force_override_unresolved(key, override, store, reservation)

    assert result.success
    assert len(reservation._override_audits) == 1
    audit = reservation._override_audits[0]
    assert isinstance(audit, OverrideAuditRecord)
    assert audit.idempotency_key == key
    assert audit.operator_id == "ops_admin"
    assert audit.reason == "no matching deal"
    assert audit.broker_inspection_summary == "checked history API"


@patch("scalping_core.operator_resolution._OVERRIDE_DISABLED", False)
def test_override_does_not_stuff_raw_comment():
    """Override does not encode evidence into the order's raw_comment."""
    store, reservation = _linked_fixtures()
    key = "test:nocomment"
    store._orders[key] = _pending_record(key)
    reservation._held["EURUSD"] = "test"
    reservation._admission["EURUSD"] = "SUBMITTING"

    override = OverrideEvidence(
        operator_id="ops_admin",
        reason="no match",
        broker_inspection_summary="checked",
    )
    force_override_unresolved(key, override, store, reservation)

    assert store._orders[key].result.raw_comment is None


@patch("scalping_core.operator_resolution._OVERRIDE_DISABLED", False)
def test_override_requires_all_fields():
    store, reservation = _linked_fixtures()
    key = "test:fields"
    store._orders[key] = _pending_record(key)

    r1 = force_override_unresolved(key, OverrideEvidence(
        operator_id="", reason="r", broker_inspection_summary="s"), store, reservation)
    assert not r1.success

    r2 = force_override_unresolved(key, OverrideEvidence(
        operator_id="op", reason="", broker_inspection_summary="s"), store, reservation)
    assert not r2.success

    r3 = force_override_unresolved(key, OverrideEvidence(
        operator_id="op", reason="r", broker_inspection_summary=""), store, reservation)
    assert not r3.success


@patch("scalping_core.operator_resolution._OVERRIDE_DISABLED", False)
def test_override_only_pending_submit():
    """Cannot override an order that is already terminal."""
    store, reservation = _linked_fixtures()
    key = "test:terminal"
    store._orders[key] = OrderRecord(
        request=_request(key=key),
        result=OrderResult(state=OrderState.FILLED, broker_ticket=1),
        created_mono=0.0, updated_mono=0.0,
    )

    result = force_override_unresolved(key, OverrideEvidence(
        operator_id="op", reason="r", broker_inspection_summary="s"), store, reservation)

    assert not result.success
    assert "not PENDING_SUBMIT" in result.message


# ---------------------------------------------------------------------------
# Tests: OPERATOR_OVERRIDE state semantics
# ---------------------------------------------------------------------------

def test_operator_override_is_not_terminal():
    """OPERATOR_OVERRIDE is NOT terminal — broker outcome is unknown."""
    assert not is_terminal(OrderState.OPERATOR_OVERRIDE)


def test_operator_override_visible_to_reconciler():
    """load_non_terminal_orders includes OPERATOR_OVERRIDE orders."""
    store = _MemStore()
    store._orders["k1"] = OrderRecord(
        request=_request(key="k1"),
        result=OrderResult(state=OrderState.OPERATOR_OVERRIDE),
        created_mono=0.0, updated_mono=0.0,
    )
    result = store.load_non_terminal_orders()
    assert len(result) == 1
    assert result[0].result.state == OrderState.OPERATOR_OVERRIDE


def test_operator_override_allows_future_resolution():
    """OPERATOR_OVERRIDE can transition to broker-confirmed terminal states."""
    assert is_valid_transition(
        OrderState.OPERATOR_OVERRIDE, OrderState.FILLED,
    )
    assert is_valid_transition(
        OrderState.OPERATOR_OVERRIDE, OrderState.REJECTED,
    )
    assert is_valid_transition(
        OrderState.OPERATOR_OVERRIDE, OrderState.EXPIRED,
    )


def test_operator_override_blocks_non_terminal_transitions():
    """OPERATOR_OVERRIDE cannot transition back to non-terminal states."""
    assert not is_valid_transition(
        OrderState.OPERATOR_OVERRIDE, OrderState.PENDING_SUBMIT,
    )
    assert not is_valid_transition(
        OrderState.OPERATOR_OVERRIDE, OrderState.SUBMITTED,
    )
    assert not is_valid_transition(
        OrderState.OPERATOR_OVERRIDE, OrderState.UNKNOWN,
    )


def test_pending_submit_can_transition_to_operator_override():
    assert is_valid_transition(
        OrderState.PENDING_SUBMIT, OrderState.OPERATOR_OVERRIDE,
    )
