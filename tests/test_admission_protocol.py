"""Tests for the two-gate admission protocol — state transitions, ownership, crash points.

PREPARED — NOT YET RUN. Deferred until market open per owner decision.

These tests exercise the in-memory test doubles. Integration tests against
PostgreSQL are in test_postgres_store.py (require a live database).
"""
import time
from decimal import Decimal

from scalping_core.broker_types import ContractSpec, SymbolMapping, Tick
from scalping_core.daily_risk import ZERO_PNL
from scalping_core.execution_engine import (
    ExecutionAttempt,
    ExecutionConfig,
    ExecutionEngine,
    PairReservationProvider,
    StartupReconciler,
)
from scalping_core.fake_execution_adapter import FakeExecutionAdapter
from scalping_core.order_types import OrderRecord, OrderRequest, OrderResult, OrderSide, OrderState
from scalping_core.risk_gate import RiskState
from scalping_core.spread_engine import SpreadConfig, SpreadTracker
from scalping_core.strategy_types import MarketRegime, Signal, SignalDirection, StrategyType
from scalping_core.market_data import PairFeed
from scalping_core.fake_broker import make_contract, make_tick


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _TestAdapter(FakeExecutionAdapter):
    @property
    def is_simulation(self):
        return False

    @property
    def is_execution_enabled(self):
        return True


class _TestDurableStore:
    """Minimal stub for DurableStateStore."""
    def is_available(self):
        return True
    def save_risk_snapshot(self, *a):
        pass
    def load_risk_snapshot(self, *a):
        return None
    def save_order(self, *a):
        pass
    def load_order(self, *a):
        return None
    def load_non_terminal_orders(self):
        return []
    def save_position(self, *a):
        pass
    def load_open_positions(self):
        return []
    def mark_position_closed(self, *a):
        pass
    def verify_account(self, *a):
        pass


class _AdmissionReservation(PairReservationProvider):
    """Reservation provider that tracks full admission state machine."""

    def __init__(self):
        self._held = {}  # pair -> owner
        self._admission = {}  # pair -> status
        self._intents = {}  # pair -> OrderRequest (from gate_submission)
        self._outcomes = {}  # pair -> OrderRecord (from resolve_admission)

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

    def load_all_reservations(self):
        return [(p, o) for p, o in self._held.items()]

    def adopt(self, pair):
        self._held[pair] = "reconciler"
        return True

    def force_release(self, pair):
        self._held.pop(pair, None)

    def gate_submission(self, pair, order_request=None):
        if pair not in self._held:
            return False
        if self._admission.get(pair) != "ACQUIRED":
            return False
        self._admission[pair] = "SUBMITTING"
        if order_request is not None:
            self._intents[pair] = order_request
        return True

    def resolve_admission(self, pair, record=None, position=None, override_audit=None):
        if self._admission.get(pair) != "SUBMITTING":
            return
        self._admission[pair] = "IDLE"
        if record is not None:
            self._outcomes[pair] = record

    def load_in_flight_submissions(self):
        return [p for p, s in self._admission.items() if s == "SUBMITTING"]


class _TestReconciler(StartupReconciler):
    def __init__(self):
        self._reconciled = True
    def begin(self):
        return True
    def complete(self):
        self._reconciled = True
    def is_reconciled(self):
        return self._reconciled
    def halt_entry_barrier(self):
        self._reconciled = False
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _contract():
    return make_contract("EURUSD", tick_value="1.0", tick_size="0.00001",
                         volume_min="0.01", min_stop_distance="0")


def _mapping():
    return SymbolMapping(canonical_pair="EURUSD", broker_symbol="EURUSD",
                         contract=_contract())


def _signal():
    return Signal(
        direction=SignalDirection.BUY,
        strategy=StrategyType.MOMENTUM,
        regime=MarketRegime.TRENDING,
        strength=Decimal("0.8"),
        canonical_pair="EURUSD",
        reference_price=Decimal("1.10020"),
        timestamp_ms=1700000000000,
    )


def _fresh_tick():
    return Tick(
        broker_symbol="EURUSD",
        bid=Decimal("1.10000"),
        ask=Decimal("1.10020"),
        server_time_ms=1700000000000,
        recv_time_mono=time.monotonic(),
    )


def _engine(adapter=None, reservation=None):
    return ExecutionEngine(
        config=ExecutionConfig(
            live_trading_enabled=True,
            max_concurrent_positions=5,
            atr_stop_multiplier=Decimal("1"),
        ),
        adapter=adapter or _TestAdapter(),
        durable_store=_TestDurableStore(),
        reservation_provider=reservation or _AdmissionReservation(),
        reconciler=_TestReconciler(),
    )


def _spread_tracker(tick):
    st = SpreadTracker(SpreadConfig(manual_max_spread=Decimal("3.0"),
        adaptive_threshold=Decimal("3.0"), rolling_window_size=100,
        trend_lookback=2, anomaly_multiplier=Decimal("3.0"),
                                     stability_period_s=0.0))
    st.update(Decimal("2.0"), tick.recv_time_mono - 70)
    st.update(Decimal("2.0"), tick.recv_time_mono)
    return st


def _attempt(engine, adapter, reservation, tick):
    return engine.attempt_entry(
        signal=_signal(),
        mapping=_mapping(),
        feed=_feed(tick),
        spread_tracker=_spread_tracker(tick),
        risk_state=RiskState.ACTIVE,
        risk_state_age_seconds=Decimal("1"),
        daily_pnl=ZERO_PNL,
        broker_connected=True,
        atr_points=Decimal("0.00050"),
    )


# Helper: PairFeed doesn't have tap, use process_tick
def _feed(tick):
    f = PairFeed(_contract(), staleness_threshold_ms=5000, max_tick_age_s=10.0)
    f.process_tick(tick)
    return f


# ---------------------------------------------------------------------------
# Tests: gate_submission state transitions
# ---------------------------------------------------------------------------

def test_gate_submission_requires_acquired_state():
    """gate_submission rejects if not in ACQUIRED state."""
    reservation = _AdmissionReservation()
    reservation._held["EURUSD"] = "test"
    reservation._admission["EURUSD"] = "IDLE"  # wrong state
    assert not reservation.gate_submission("EURUSD")


def test_gate_submission_acquired_to_submitting():
    reservation = _AdmissionReservation()
    reservation._held["EURUSD"] = "test"
    reservation._admission["EURUSD"] = "ACQUIRED"
    assert reservation.gate_submission("EURUSD")
    assert reservation._admission["EURUSD"] == "SUBMITTING"


def test_resolve_admission_submitting_to_idle():
    reservation = _AdmissionReservation()
    reservation._held["EURUSD"] = "test"
    reservation._admission["EURUSD"] = "SUBMITTING"
    reservation.resolve_admission("EURUSD")
    assert reservation._admission["EURUSD"] == "IDLE"


def test_resolve_admission_rejects_wrong_state():
    reservation = _AdmissionReservation()
    reservation._held["EURUSD"] = "test"
    reservation._admission["EURUSD"] = "ACQUIRED"
    reservation.resolve_admission("EURUSD")
    # Should NOT change
    assert reservation._admission["EURUSD"] == "ACQUIRED"


def test_gate_submission_rejects_no_reservation():
    reservation = _AdmissionReservation()
    assert not reservation.gate_submission("EURUSD")


def test_double_gate_submission_rejected():
    """Cannot go SUBMITTING → SUBMITTING."""
    reservation = _AdmissionReservation()
    reservation._held["EURUSD"] = "test"
    reservation._admission["EURUSD"] = "ACQUIRED"
    assert reservation.gate_submission("EURUSD")
    assert not reservation.gate_submission("EURUSD")


# ---------------------------------------------------------------------------
# Tests: in-flight submission tracking
# ---------------------------------------------------------------------------

def test_load_in_flight_empty():
    reservation = _AdmissionReservation()
    assert reservation.load_in_flight_submissions() == []


def test_load_in_flight_finds_submitting():
    reservation = _AdmissionReservation()
    reservation._held["EURUSD"] = "test"
    reservation._admission["EURUSD"] = "SUBMITTING"
    assert reservation.load_in_flight_submissions() == ["EURUSD"]


def test_load_in_flight_ignores_idle():
    reservation = _AdmissionReservation()
    reservation._held["EURUSD"] = "test"
    reservation._admission["EURUSD"] = "IDLE"
    assert reservation.load_in_flight_submissions() == []


# ---------------------------------------------------------------------------
# Tests: crash point scenarios (simulated via state inspection)
# ---------------------------------------------------------------------------

def test_cp1_crash_before_gate_submission():
    """CP1: crash after acquire, before gate_submission.
    Reservation is ACQUIRED, no order row. Reconciler can force_release."""
    reservation = _AdmissionReservation()
    reservation.acquire("EURUSD")
    assert reservation._admission["EURUSD"] == "ACQUIRED"
    assert reservation.load_in_flight_submissions() == []
    # Reconciler sees reservation, no order, no SUBMITTING → safe to release
    reservation.force_release("EURUSD")
    assert "EURUSD" not in reservation._held


def test_cp2_crash_after_gate_submission():
    """CP2: crash after gate_submission, before broker call.
    SUBMITTING + intent persisted. Reconciler must NOT release."""
    reservation = _AdmissionReservation()
    reservation.acquire("EURUSD")
    req = OrderRequest(
        canonical_pair="EURUSD", broker_symbol="EURUSD",
        side=OrderSide.BUY, volume_lots=Decimal("0.01"),
        stop_loss_price=Decimal("1.09"), take_profit_price=None,
        idempotency_key="test-key", signal_timestamp_ms=1700000000000,
        fresh_quote_bid=Decimal("1.1"), fresh_quote_ask=Decimal("1.1002"),
        fresh_quote_time_ms=1700000000000,
    )
    reservation.gate_submission("EURUSD", req)
    assert reservation._admission["EURUSD"] == "SUBMITTING"
    assert reservation._intents.get("EURUSD") is req
    # Must appear in drain
    assert "EURUSD" in reservation.load_in_flight_submissions()


def test_cp5_after_resolve():
    """CP5: after resolve_admission. IDLE + order record. Normal path."""
    reservation = _AdmissionReservation()
    reservation.acquire("EURUSD")
    reservation.gate_submission("EURUSD")
    record = OrderRecord(
        request=OrderRequest(
            canonical_pair="EURUSD", broker_symbol="EURUSD",
            side=OrderSide.BUY, volume_lots=Decimal("0.01"),
            stop_loss_price=Decimal("1.09"), take_profit_price=None,
            idempotency_key="test-key", signal_timestamp_ms=1700000000000,
            fresh_quote_bid=Decimal("1.1"), fresh_quote_ask=Decimal("1.1002"),
            fresh_quote_time_ms=1700000000000,
        ),
        result=OrderResult(state=OrderState.FILLED, broker_ticket=1001),
        created_mono=0.0,
        updated_mono=0.0,
    )
    reservation.resolve_admission("EURUSD", record)
    assert reservation._admission["EURUSD"] == "IDLE"
    assert reservation._outcomes.get("EURUSD") is record
    assert reservation.load_in_flight_submissions() == []


# ---------------------------------------------------------------------------
# Tests: engine integration — barrier closed during admission
# ---------------------------------------------------------------------------

def test_barrier_closed_after_acquire():
    """If gate_submission fails (barrier closed), entry is rejected and
    reservation is held for reconciler."""
    reservation = _AdmissionReservation()

    # Override gate_submission to always fail (simulates RECONCILING barrier)
    reservation.gate_submission = lambda pair, req=None: False

    adapter = _TestAdapter()
    tick = _fresh_tick()
    adapter.set_quote("EURUSD", tick)

    engine = _engine(adapter=adapter, reservation=reservation)

    result = engine.attempt_entry(
        signal=_signal(),
        mapping=_mapping(),
        feed=_feed(tick),
        spread_tracker=_spread_tracker(tick),
        risk_state=RiskState.ACTIVE,
        risk_state_age_seconds=Decimal("1"),
        daily_pnl=ZERO_PNL,
        broker_connected=True,
        atr_points=Decimal("0.00050"),
    )
    assert not result.executed
    assert "barrier_closed_during_admission" in result.reject_reasons


# ---------------------------------------------------------------------------
# Tests: engine integration — submit exception holds SUBMITTING
# ---------------------------------------------------------------------------

def test_submit_exception_holds_submitting():
    """On submit exception, admission stays SUBMITTING for reconciler."""
    reservation = _AdmissionReservation()
    adapter = _TestAdapter()
    tick = _fresh_tick()
    adapter.set_quote("EURUSD", tick)

    # Make submit raise
    def exploding_submit(request):
        raise RuntimeError("connection lost")

    adapter.submit_order = exploding_submit

    engine = _engine(adapter=adapter, reservation=reservation)

    result = engine.attempt_entry(
        signal=_signal(),
        mapping=_mapping(),
        feed=_feed(tick),
        spread_tracker=_spread_tracker(tick),
        risk_state=RiskState.ACTIVE,
        risk_state_age_seconds=Decimal("1"),
        daily_pnl=ZERO_PNL,
        broker_connected=True,
        atr_points=Decimal("0.00050"),
    )
    assert not result.executed
    assert "submit_exception_needs_reconciliation" in result.reject_reasons
    # Reservation held
    assert "EURUSD" in reservation._held
    # Admission stays SUBMITTING
    assert reservation._admission.get("EURUSD") == "SUBMITTING"


# ---------------------------------------------------------------------------
# Tests: successful entry persists intent and resolves
# ---------------------------------------------------------------------------

def test_successful_entry_full_lifecycle():
    """Full lifecycle: acquire → gate_submission → submit → resolve."""
    reservation = _AdmissionReservation()
    adapter = _TestAdapter()
    tick = _fresh_tick()
    adapter.set_quote("EURUSD", tick)

    engine = _engine(adapter=adapter, reservation=reservation)

    result = engine.attempt_entry(
        signal=_signal(),
        mapping=_mapping(),
        feed=_feed(tick),
        spread_tracker=_spread_tracker(tick),
        risk_state=RiskState.ACTIVE,
        risk_state_age_seconds=Decimal("1"),
        daily_pnl=ZERO_PNL,
        broker_connected=True,
        atr_points=Decimal("0.00050"),
    )
    assert result.executed
    # Admission resolved to IDLE
    assert reservation._admission.get("EURUSD") == "IDLE"
    # Intent was persisted via gate_submission
    assert "EURUSD" in reservation._intents
    # Outcome was persisted via resolve_admission
    assert "EURUSD" in reservation._outcomes
