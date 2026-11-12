"""Tests for startup_supervisor — reconciliation orchestration.

PREPARED — NOT YET RUN. Deferred until market open per owner decision.
"""
import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

from scalping_core.broker_types import Tick
from scalping_core.daily_risk import DailyPnL, ZERO_PNL
from scalping_core.execution_engine import (
    DurableStateStore,
    PairReservationProvider,
    StartupReconciler,
)
from scalping_core.fake_execution_adapter import FakeExecutionAdapter
from scalping_core.order_types import (
    OrderRecord,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderState,
    PositionInfo,
)
from scalping_core.risk_gate import RiskState
from scalping_core.startup_supervisor import StartupSupervisor, SupervisorOutcome


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _MemStore(DurableStateStore):
    def __init__(self, available=True):
        self._available = available
        self._risk = {}
        self._orders = {}
        self._positions = {}
        self._closed = set()
        self._account = None

    def is_available(self):
        return self._available

    def save_risk_snapshot(self, trading_day, state, pnl):
        self._risk[trading_day] = (state, pnl)

    def load_risk_snapshot(self, trading_day):
        return self._risk.get(trading_day)

    def save_order(self, record):
        self._orders[record.request.idempotency_key] = record

    def load_order(self, key):
        return self._orders.get(key)

    def load_non_terminal_orders(self):
        from scalping_core.order_types import is_terminal
        return [r for r in self._orders.values() if not is_terminal(r.result.state)]

    def save_position(self, pos):
        self._positions[pos.broker_ticket] = pos

    def load_open_positions(self):
        return [p for t, p in self._positions.items() if t not in self._closed]

    def mark_position_closed(self, ticket):
        self._closed.add(ticket)

    def verify_account(self, account_id):
        if self._account is None:
            self._account = account_id
        elif self._account != account_id:
            from scalping_core.order_types import AccountMismatchError
            raise AccountMismatchError(self._account, account_id)


class _MemReservation(PairReservationProvider):
    def __init__(self, available=True):
        self._available = available
        self._held = {}
        self._admission = {}

    def is_available(self):
        return self._available

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
        if pair in self._held:
            self._held[pair] = "reconciler"
            return True
        return False

    def force_release(self, pair):
        self._held.pop(pair, None)
        self._admission.pop(pair, None)

    def gate_submission(self, pair, order_request=None):
        if pair in self._held and self._admission.get(pair) == "ACQUIRED":
            self._admission[pair] = "SUBMITTING"
            return True
        return False

    def resolve_admission(self, pair, record=None, position=None, override_audit=None):
        if pair in self._held and self._admission.get(pair) == "SUBMITTING":
            self._admission[pair] = "IDLE"

    def load_in_flight_submissions(self):
        return [p for p, s in self._admission.items() if s == "SUBMITTING"]


class _MemReconciler(StartupReconciler):
    def __init__(self, can_begin=True):
        self._can_begin = can_begin
        self._reconciled = False
        self._begun = False

    def begin(self):
        if self._can_begin:
            self._begun = True
            return True
        return False

    def complete(self):
        self._reconciled = True

    def is_reconciled(self):
        return self._reconciled

    def halt_entry_barrier(self):
        self._reconciled = False
        return True


class _TestAdapter(FakeExecutionAdapter):
    @property
    def is_simulation(self):
        return False

    @property
    def is_execution_enabled(self):
        return True


# ---------------------------------------------------------------------------
# Tests: happy path
# ---------------------------------------------------------------------------

def test_clean_startup_reaches_ready():
    store = _MemStore()
    reservation = _MemReservation()
    reconciler = _MemReconciler()
    adapter = _TestAdapter()

    supervisor = StartupSupervisor(
        store, reservation, reconciler, adapter,
        drain_timeout_s=1.0,
    )
    outcome = supervisor.run(account_id="12345")

    assert outcome == SupervisorOutcome.READY
    assert reconciler._reconciled


def test_not_reconciler_when_lock_held():
    reconciler = _MemReconciler(can_begin=False)
    supervisor = StartupSupervisor(
        _MemStore(), _MemReservation(), reconciler, _TestAdapter(),
    )
    outcome = supervisor.run(account_id="12345")
    assert outcome == SupervisorOutcome.NOT_RECONCILER


def test_account_mismatch():
    store = _MemStore()
    store._account = "99999"
    supervisor = StartupSupervisor(
        store, _MemReservation(), _MemReconciler(), _TestAdapter(),
    )
    outcome = supervisor.run(account_id="12345")
    assert outcome == SupervisorOutcome.ACCOUNT_MISMATCH


def test_store_unavailable():
    store = _MemStore(available=False)
    supervisor = StartupSupervisor(
        store, _MemReservation(), _MemReconciler(), _TestAdapter(),
    )
    outcome = supervisor.run(account_id="12345")
    assert outcome == SupervisorOutcome.ERROR


def test_reservation_unavailable():
    supervisor = StartupSupervisor(
        _MemStore(), _MemReservation(available=False),
        _MemReconciler(), _TestAdapter(),
    )
    outcome = supervisor.run(account_id="12345")
    assert outcome == SupervisorOutcome.ERROR


# ---------------------------------------------------------------------------
# Tests: drain
# ---------------------------------------------------------------------------

def test_drain_timeout_blocks_ready():
    reservation = _MemReservation()
    reservation._held["EURUSD"] = "other-process"
    reservation._admission["EURUSD"] = "SUBMITTING"

    supervisor = StartupSupervisor(
        _MemStore(), reservation, _MemReconciler(), _TestAdapter(),
        drain_timeout_s=0.1,
        drain_poll_interval_s=0.05,
    )
    outcome = supervisor.run(account_id="12345")

    assert outcome == SupervisorOutcome.UNRESOLVED_SUBMISSIONS
    # Reservation NOT released
    assert "EURUSD" in reservation._held


def test_drain_resolves_before_timeout():
    reservation = _MemReservation()
    reservation._held["EURUSD"] = "other-process"
    reservation._admission["EURUSD"] = "SUBMITTING"

    # Simulate the other process resolving after a brief delay
    original_load = reservation.load_in_flight_submissions
    call_count = [0]

    def resolving_load():
        call_count[0] += 1
        if call_count[0] >= 2:
            reservation._admission["EURUSD"] = "IDLE"
        return original_load()

    reservation.load_in_flight_submissions = resolving_load

    supervisor = StartupSupervisor(
        _MemStore(), reservation, _MemReconciler(), _TestAdapter(),
        drain_timeout_s=5.0,
        drain_poll_interval_s=0.01,
    )
    outcome = supervisor.run(account_id="12345")
    assert outcome == SupervisorOutcome.READY


# ---------------------------------------------------------------------------
# Tests: reservation reconciliation
# ---------------------------------------------------------------------------

def test_reservation_with_open_position_adopted():
    store = _MemStore()
    reservation = _MemReservation()
    reservation._held["EURUSD"] = "old-process"
    reservation._admission["EURUSD"] = "IDLE"

    adapter = _TestAdapter()
    adapter.set_positions("EURUSD", [
        PositionInfo(
            broker_ticket=1001, canonical_pair="EURUSD",
            broker_symbol="EURUSD", side=OrderSide.BUY,
            volume_lots=Decimal("0.01"), open_price=Decimal("1.1"),
            current_price=Decimal("1.1"), stop_loss=Decimal("1.09"),
            take_profit=None, floating_pnl_usd=Decimal("0"),
            open_time_ms=1700000000000, swap_usd=Decimal("0"),
            commission_usd=Decimal("0"),
        ),
    ])

    supervisor = StartupSupervisor(
        store, reservation, _MemReconciler(), adapter,
        drain_timeout_s=0.1,
    )
    outcome = supervisor.run(account_id="12345")

    assert outcome == SupervisorOutcome.READY
    assert "EURUSD" in reservation._held
    assert reservation._held["EURUSD"] == "reconciler"


def test_reservation_clear_at_broker_released():
    reservation = _MemReservation()
    reservation._held["EURUSD"] = "old-process"
    reservation._admission["EURUSD"] = "IDLE"

    supervisor = StartupSupervisor(
        _MemStore(), reservation, _MemReconciler(), _TestAdapter(),
        drain_timeout_s=0.1,
    )
    outcome = supervisor.run(account_id="12345")

    assert outcome == SupervisorOutcome.READY
    assert "EURUSD" not in reservation._held


# ---------------------------------------------------------------------------
# Tests: order reconciliation
# ---------------------------------------------------------------------------

def _pending_submit_order(pair="EURUSD", key="test-key"):
    return OrderRecord(
        request=OrderRequest(
            canonical_pair=pair, broker_symbol=pair,
            side=OrderSide.BUY, volume_lots=Decimal("0.01"),
            stop_loss_price=Decimal("1.09"), take_profit_price=None,
            idempotency_key=key, signal_timestamp_ms=1700000000000,
            fresh_quote_bid=Decimal("1.1"), fresh_quote_ask=Decimal("1.1002"),
            fresh_quote_time_ms=1700000000000,
        ),
        result=OrderResult(state=OrderState.PENDING_SUBMIT),
        created_mono=0.0,
        updated_mono=0.0,
    )


def _unknown_order_with_ticket(pair="EURUSD", key="test-key", ticket=1001):
    return OrderRecord(
        request=OrderRequest(
            canonical_pair=pair, broker_symbol=pair,
            side=OrderSide.BUY, volume_lots=Decimal("0.01"),
            stop_loss_price=Decimal("1.09"), take_profit_price=None,
            idempotency_key=key, signal_timestamp_ms=1700000000000,
            fresh_quote_bid=Decimal("1.1"), fresh_quote_ask=Decimal("1.1002"),
            fresh_quote_time_ms=1700000000000,
        ),
        result=OrderResult(state=OrderState.UNKNOWN, broker_ticket=ticket),
        created_mono=0.0,
        updated_mono=0.0,
    )


def test_pending_submit_order_blocks_ready():
    """PENDING_SUBMIT orders cannot be correlated — blocks reconciliation."""
    store = _MemStore()
    store._orders["test-key"] = _pending_submit_order()

    supervisor = StartupSupervisor(
        store, _MemReservation(), _MemReconciler(), _TestAdapter(),
        drain_timeout_s=0.1,
    )
    outcome = supervisor.run(account_id="12345")
    assert outcome == SupervisorOutcome.UNRESOLVED_ORDERS


def test_unknown_order_resolved_by_broker():
    """Broker reports terminal state — order reconciled."""
    store = _MemStore()
    store._orders["test-key"] = _unknown_order_with_ticket()

    adapter = _TestAdapter()
    adapter.set_next_query(OrderResult(state=OrderState.REJECTED, reject_reason="no_money"))

    supervisor = StartupSupervisor(
        store, _MemReservation(), _MemReconciler(), adapter,
        drain_timeout_s=0.1,
    )
    outcome = supervisor.run(account_id="12345")
    assert outcome == SupervisorOutcome.READY
    assert store._orders["test-key"].result.state == OrderState.REJECTED


def test_unknown_order_still_nonterminal_blocks():
    """Broker reports non-terminal state — blocks reconciliation."""
    store = _MemStore()
    store._orders["test-key"] = _unknown_order_with_ticket()

    adapter = _TestAdapter()
    adapter.set_next_query(OrderResult(state=OrderState.SUBMITTED, broker_ticket=1001))

    supervisor = StartupSupervisor(
        store, _MemReservation(), _MemReconciler(), adapter,
        drain_timeout_s=0.1,
    )
    outcome = supervisor.run(account_id="12345")
    assert outcome == SupervisorOutcome.UNRESOLVED_ORDERS


# ---------------------------------------------------------------------------
# Tests: risk state
# ---------------------------------------------------------------------------

def test_risk_state_initialized_on_clean_start():
    store = _MemStore()
    supervisor = StartupSupervisor(
        store, _MemReservation(), _MemReconciler(), _TestAdapter(),
        drain_timeout_s=0.1,
    )
    outcome = supervisor.run(account_id="12345")
    assert outcome == SupervisorOutcome.READY
    from scalping_core.daily_risk import trading_day
    from datetime import datetime, timezone
    today = trading_day(datetime.now(timezone.utc))
    assert today in store._risk


def test_existing_risk_state_preserved():
    store = _MemStore()
    from scalping_core.daily_risk import trading_day
    from datetime import datetime, timezone
    today = trading_day(datetime.now(timezone.utc))
    pnl = DailyPnL(Decimal("5"), Decimal("0"), Decimal("-0.5"), Decimal("0"))
    store._risk[today] = (RiskState.ACTIVE, pnl)

    supervisor = StartupSupervisor(
        store, _MemReservation(), _MemReconciler(), _TestAdapter(),
        drain_timeout_s=0.1,
    )
    outcome = supervisor.run(account_id="12345")
    assert outcome == SupervisorOutcome.READY
    state, loaded_pnl = store._risk[today]
    assert loaded_pnl.realized_pnl_usd == Decimal("5")


# ---------------------------------------------------------------------------
# Tests: fail-closed behavior
# ---------------------------------------------------------------------------

def test_reconciliation_exception_returns_error():
    """If reconciliation raises, barrier stays RECONCILING."""
    store = _MemStore()
    reservation = _MemReservation()
    reconciler = _MemReconciler()

    # Make load_in_flight_submissions raise
    def explode():
        raise RuntimeError("db gone")

    reservation.load_in_flight_submissions = explode

    supervisor = StartupSupervisor(
        store, reservation, reconciler, _TestAdapter(),
    )
    outcome = supervisor.run(account_id="12345")
    assert outcome == SupervisorOutcome.ERROR
    assert not reconciler._reconciled
