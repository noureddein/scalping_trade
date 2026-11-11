"""Tests for execution_engine — the §8 orchestrator.

PREPARED — NOT YET RUN. Market-dependent tests deferred until market open.
"""
import time
from decimal import Decimal

from scalping_core.broker_types import ContractSpec, Tick
from scalping_core.daily_risk import DailyPnL, DailyRiskConfig, ZERO_PNL
from scalping_core.execution_engine import (
    DurableStateStore,
    ExecutionAttempt,
    ExecutionConfig,
    ExecutionEngine,
    PairReservationProvider,
    StartupReconciler,
)
from scalping_core.fake_broker import make_contract, make_tick
from scalping_core.fake_execution_adapter import FakeExecutionAdapter
from scalping_core.market_data import PairFeed
from scalping_core.order_types import OrderResult, OrderState
from scalping_core.risk_gate import RiskState
from scalping_core.spread_engine import SpreadConfig, SpreadTracker
from scalping_core.strategy_types import (
    MarketRegime,
    Signal,
    SignalDirection,
    StrategyType,
)
from scalping_core.broker_types import SymbolMapping


# ---------------------------------------------------------------------------
# Test doubles for injected infrastructure dependencies
# ---------------------------------------------------------------------------

class _TestAdapter(FakeExecutionAdapter):
    """Non-simulation adapter for tests only. Allows engine activation."""

    @property
    def is_simulation(self) -> bool:
        return False

    @property
    def is_execution_enabled(self) -> bool:
        return True


class _TestDurableStore(DurableStateStore):
    """In-memory test double implementing all DurableStateStore methods."""

    def __init__(self, available: bool = True) -> None:
        self._available = available
        self._risk: dict = {}
        self._orders: dict[str, "OrderRecord"] = {}
        self._positions: dict[int, "PositionInfo"] = {}
        self._closed_tickets: set[int] = set()

    def is_available(self) -> bool:
        return self._available

    def save_risk_snapshot(self, trading_day, state, pnl):
        self._risk[trading_day] = (state, pnl)

    def load_risk_snapshot(self, trading_day):
        return self._risk.get(trading_day)

    def save_order(self, record):
        self._orders[record.request.idempotency_key] = record

    def load_order(self, idempotency_key):
        return self._orders.get(idempotency_key)

    def load_non_terminal_orders(self):
        from scalping_core.order_types import is_terminal
        return [r for r in self._orders.values() if not is_terminal(r.result.state)]

    def save_position(self, position):
        self._positions[position.broker_ticket] = position

    def load_open_positions(self):
        return [p for t, p in self._positions.items() if t not in self._closed_tickets]

    def mark_position_closed(self, broker_ticket):
        self._closed_tickets.add(broker_ticket)

    def verify_account(self, account_id):
        pass


class _TestReservation(PairReservationProvider):
    def __init__(self) -> None:
        self._held: set[str] = set()
        self._available: bool = True
        self.acquire_calls: list[str] = []
        self.release_calls: list[str] = []

    def is_available(self) -> bool:
        return self._available

    def acquire(self, canonical_pair: str) -> bool:
        self.acquire_calls.append(canonical_pair)
        if canonical_pair in self._held:
            return False
        self._held.add(canonical_pair)
        return True

    def release(self, canonical_pair: str) -> None:
        self.release_calls.append(canonical_pair)
        self._held.discard(canonical_pair)

    def load_all_reservations(self) -> list[tuple[str, str]]:
        return [(p, "test") for p in self._held]

    def adopt(self, canonical_pair: str) -> bool:
        self._held.add(canonical_pair)
        return True

    def force_release(self, canonical_pair: str) -> None:
        self._held.discard(canonical_pair)

    def gate_submission(self, canonical_pair, order_request=None) -> bool:
        return canonical_pair in self._held

    def resolve_admission(self, canonical_pair, record=None, position=None, override_audit=None) -> None:
        pass

    def load_in_flight_submissions(self) -> list[str]:
        return []


class _TestReconciler(StartupReconciler):
    def __init__(self, reconciled: bool = True) -> None:
        self._reconciled = reconciled
        self.halt_calls: int = 0

    def begin(self) -> bool:
        return True

    def complete(self) -> None:
        self._reconciled = True

    def is_reconciled(self) -> bool:
        return self._reconciled

    def halt_entry_barrier(self) -> bool:
        self.halt_calls += 1
        self._reconciled = False
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _contract() -> ContractSpec:
    return make_contract("EURUSD", tick_value="1.0", tick_size="0.00001",
                         volume_min="0.01", min_stop_distance="0")


def _mapping() -> SymbolMapping:
    return SymbolMapping(canonical_pair="EURUSD", broker_symbol="EURUSD",
                         contract=_contract())


def _signal(direction=SignalDirection.BUY) -> Signal:
    return Signal(
        direction=direction,
        strategy=StrategyType.MOMENTUM,
        regime=MarketRegime.TRENDING,
        strength=Decimal("0.8"),
        canonical_pair="EURUSD",
        reference_price=Decimal("1.10020"),
        timestamp_ms=1700000000000,
    )


def _fresh_tick(mono: float | None = None) -> Tick:
    return Tick(
        broker_symbol="EURUSD",
        bid=Decimal("1.10000"),
        ask=Decimal("1.10020"),
        server_time_ms=1700000000000,
        recv_time_mono=mono if mono is not None else time.monotonic(),
    )


def _active_engine(
    adapter: _TestAdapter | None = None,
    reservation: _TestReservation | None = None,
) -> ExecutionEngine:
    return ExecutionEngine(
        config=ExecutionConfig(
            live_trading_enabled=True,
            max_concurrent_positions=5,
            atr_stop_multiplier=Decimal("1.5"),
        ),
        adapter=adapter or _TestAdapter(),
        durable_store=_TestDurableStore(),
        reservation_provider=reservation or _TestReservation(),
        reconciler=_TestReconciler(),
    )


def _feed(tick: Tick | None = None) -> PairFeed:
    f = PairFeed(_contract(), staleness_threshold_ms=5000, max_tick_age_s=10.0)
    t = tick or _fresh_tick()
    f.process_tick(t)
    return f


def _spread_tracker() -> SpreadTracker:
    return SpreadTracker(SpreadConfig(manual_max_spread=Decimal("3.0"),
        adaptive_threshold=Decimal("3.0"), rolling_window_size=100,
        trend_lookback=2, anomaly_multiplier=Decimal("3.0"),
                                       stability_period_s=0.0))


# ---------------------------------------------------------------------------
# Activation gate tests
# ---------------------------------------------------------------------------

def test_inactive_by_default():
    engine = ExecutionEngine()
    assert not engine.is_active()


def test_inactive_with_fake_adapter():
    engine = ExecutionEngine(
        config=ExecutionConfig(
            live_trading_enabled=True,
            max_concurrent_positions=5,
            atr_stop_multiplier=Decimal("1.5"),
        ),
        adapter=FakeExecutionAdapter(),
        durable_store=_TestDurableStore(),
        reservation_provider=_TestReservation(),
        reconciler=_TestReconciler(),
    )
    assert not engine.is_active()


def test_inactive_without_durable_store():
    engine = ExecutionEngine(
        config=ExecutionConfig(
            live_trading_enabled=True,
            max_concurrent_positions=5,
            atr_stop_multiplier=Decimal("1.5"),
        ),
        adapter=_TestAdapter(),
        reservation_provider=_TestReservation(),
        reconciler=_TestReconciler(),
    )
    assert not engine.is_active()


def test_inactive_with_disabled_execution():
    """Engine must not report active when adapter execution is disabled."""

    class _DisabledAdapter(_TestAdapter):
        @property
        def is_execution_enabled(self) -> bool:
            return False

    engine = ExecutionEngine(
        config=ExecutionConfig(
            live_trading_enabled=True,
            max_concurrent_positions=5,
            atr_stop_multiplier=Decimal("1.5"),
        ),
        adapter=_DisabledAdapter(),
        durable_store=_TestDurableStore(),
        reservation_provider=_TestReservation(),
        reconciler=_TestReconciler(),
    )
    assert not engine.is_active()


def test_inactive_without_reservation_provider():
    engine = ExecutionEngine(
        config=ExecutionConfig(
            live_trading_enabled=True,
            max_concurrent_positions=5,
            atr_stop_multiplier=Decimal("1.5"),
        ),
        adapter=_TestAdapter(),
        durable_store=_TestDurableStore(),
        reconciler=_TestReconciler(),
    )
    assert not engine.is_active()


def test_inactive_with_unavailable_reservation_provider():
    reservation = _TestReservation()
    reservation._available = False
    engine = ExecutionEngine(
        config=ExecutionConfig(
            live_trading_enabled=True,
            max_concurrent_positions=5,
            atr_stop_multiplier=Decimal("1.5"),
        ),
        adapter=_TestAdapter(),
        durable_store=_TestDurableStore(),
        reservation_provider=reservation,
        reconciler=_TestReconciler(),
    )
    assert not engine.is_active()


def test_inactive_without_reconciliation():
    engine = ExecutionEngine(
        config=ExecutionConfig(
            live_trading_enabled=True,
            max_concurrent_positions=5,
            atr_stop_multiplier=Decimal("1.5"),
        ),
        adapter=_TestAdapter(),
        durable_store=_TestDurableStore(),
        reservation_provider=_TestReservation(),
        reconciler=_TestReconciler(reconciled=False),
    )
    assert not engine.is_active()


def test_inactive_rejects():
    engine = ExecutionEngine()
    result = engine.attempt_entry(
        signal=_signal(),
        mapping=_mapping(),
        feed=_feed(),
        spread_tracker=_spread_tracker(),
        risk_state=RiskState.ACTIVE,
        risk_state_age_seconds=Decimal("1"),
        daily_pnl=ZERO_PNL,
        broker_connected=True,
        atr_points=Decimal("0.00050"),
    )
    assert not result.executed
    assert "execution_engine_inactive" in result.reject_reasons


# ---------------------------------------------------------------------------
# Entry sequence tests
# ---------------------------------------------------------------------------

def test_no_trade_signal_rejected():
    adapter = _TestAdapter()
    adapter.set_quote("EURUSD", _fresh_tick())
    engine = _active_engine(adapter=adapter)
    result = engine.attempt_entry(
        signal=_signal(SignalDirection.NO_TRADE),
        mapping=_mapping(),
        feed=_feed(),
        spread_tracker=_spread_tracker(),
        risk_state=RiskState.ACTIVE,
        risk_state_age_seconds=Decimal("1"),
        daily_pnl=ZERO_PNL,
        broker_connected=True,
        atr_points=Decimal("0.00050"),
    )
    assert not result.executed
    assert "signal_is_no_trade" in result.reject_reasons


def test_missing_fresh_quote_rejected():
    engine = _active_engine()
    result = engine.attempt_entry(
        signal=_signal(),
        mapping=_mapping(),
        feed=_feed(),
        spread_tracker=_spread_tracker(),
        risk_state=RiskState.ACTIVE,
        risk_state_age_seconds=Decimal("1"),
        daily_pnl=ZERO_PNL,
        broker_connected=True,
        atr_points=Decimal("0.00050"),
    )
    assert not result.executed
    assert "fresh_quote_unavailable" in result.reject_reasons


def test_successful_entry():
    adapter = _TestAdapter()
    tick = _fresh_tick()
    adapter.set_quote("EURUSD", tick)
    reservation = _TestReservation()
    engine = _active_engine(adapter=adapter, reservation=reservation)

    spread_tracker = SpreadTracker(SpreadConfig(
        manual_max_spread=Decimal("3.0"),
        adaptive_threshold=Decimal("3.0"), rolling_window_size=100,
        trend_lookback=2, anomaly_multiplier=Decimal("3.0"),
        stability_period_s=0.0,
    ))
    spread_tracker.update(Decimal("2.0"), tick.recv_time_mono - 70)
    spread_tracker.update(Decimal("2.0"), tick.recv_time_mono)

    result = engine.attempt_entry(
        signal=_signal(),
        mapping=_mapping(),
        feed=_feed(tick),
        spread_tracker=spread_tracker,
        risk_state=RiskState.ACTIVE,
        risk_state_age_seconds=Decimal("1"),
        daily_pnl=ZERO_PNL,
        broker_connected=True,
        atr_points=Decimal("0.00050"),
    )
    assert result.executed
    assert result.order_record is not None
    assert result.order_record.result.state == OrderState.FILLED
    assert engine.position_manager.has_open_position("EURUSD")
    assert "EURUSD" in reservation.acquire_calls


def test_risk_locked_rejects():
    adapter = _TestAdapter()
    adapter.set_quote("EURUSD", _fresh_tick())
    engine = _active_engine(adapter=adapter)

    result = engine.attempt_entry(
        signal=_signal(),
        mapping=_mapping(),
        feed=_feed(),
        spread_tracker=_spread_tracker(),
        risk_state=RiskState.LOSS_LOCKED,
        risk_state_age_seconds=Decimal("1"),
        daily_pnl=ZERO_PNL,
        broker_connected=True,
        atr_points=Decimal("0.00050"),
    )
    assert not result.executed
    assert any("risk_state" in r for r in result.reject_reasons)


def test_broker_rejection_handled():
    adapter = _TestAdapter()
    tick = _fresh_tick()
    adapter.set_quote("EURUSD", tick)
    adapter.set_next_fill(OrderResult(state=OrderState.REJECTED,
                                       reject_reason="no_money"))
    reservation = _TestReservation()
    engine = _active_engine(adapter=adapter, reservation=reservation)

    spread_tracker = SpreadTracker(SpreadConfig(
        manual_max_spread=Decimal("3.0"),
        adaptive_threshold=Decimal("3.0"), rolling_window_size=100,
        trend_lookback=2, anomaly_multiplier=Decimal("3.0"), stability_period_s=0.0))
    spread_tracker.update(Decimal("2.0"), tick.recv_time_mono - 70)
    spread_tracker.update(Decimal("2.0"), tick.recv_time_mono)

    result = engine.attempt_entry(
        signal=_signal(),
        mapping=_mapping(),
        feed=_feed(tick),
        spread_tracker=spread_tracker,
        risk_state=RiskState.ACTIVE,
        risk_state_age_seconds=Decimal("1"),
        daily_pnl=ZERO_PNL,
        broker_connected=True,
        atr_points=Decimal("0.00050"),
    )
    assert not result.executed
    assert "order_rejected" in result.reject_reasons
    assert not engine.position_manager.has_open_position("EURUSD")
    assert "EURUSD" in reservation.release_calls


def test_ambiguous_order_not_assumed_filled():
    adapter = _TestAdapter()
    tick = _fresh_tick()
    adapter.set_quote("EURUSD", tick)
    adapter.set_next_fill(OrderResult(state=OrderState.UNKNOWN))
    reservation = _TestReservation()
    engine = _active_engine(adapter=adapter, reservation=reservation)

    spread_tracker = SpreadTracker(SpreadConfig(
        manual_max_spread=Decimal("3.0"),
        adaptive_threshold=Decimal("3.0"), rolling_window_size=100,
        trend_lookback=2, anomaly_multiplier=Decimal("3.0"), stability_period_s=0.0))
    spread_tracker.update(Decimal("2.0"), tick.recv_time_mono - 70)
    spread_tracker.update(Decimal("2.0"), tick.recv_time_mono)

    result = engine.attempt_entry(
        signal=_signal(),
        mapping=_mapping(),
        feed=_feed(tick),
        spread_tracker=spread_tracker,
        risk_state=RiskState.ACTIVE,
        risk_state_age_seconds=Decimal("1"),
        daily_pnl=ZERO_PNL,
        broker_connected=True,
        atr_points=Decimal("0.00050"),
    )
    assert not result.executed
    assert "order_state_ambiguous_needs_reconciliation" in result.reject_reasons
    assert not engine.position_manager.has_open_position("EURUSD")
    # Reservation held through ambiguity — NOT released
    assert "EURUSD" not in reservation.release_calls


# ---------------------------------------------------------------------------
# Admission protocol safety tests
# ---------------------------------------------------------------------------

def test_gate_submission_failure_blocks_adapter_and_holds_reservation():
    """If gate_submission fails to persist intent, the broker adapter must
    never be called and the reservation must NOT be released — it stays
    for the reconciler."""

    class _FailGateReservation(_TestReservation):
        def gate_submission(self, canonical_pair, order_request=None) -> bool:
            return False

    adapter = _TestAdapter()
    tick = _fresh_tick()
    adapter.set_quote("EURUSD", tick)
    reservation = _FailGateReservation()
    engine = _active_engine(adapter=adapter, reservation=reservation)

    spread_tracker = SpreadTracker(SpreadConfig(
        manual_max_spread=Decimal("3.0"),
        adaptive_threshold=Decimal("3.0"), rolling_window_size=100,
        trend_lookback=2, anomaly_multiplier=Decimal("3.0"), stability_period_s=0.0))
    spread_tracker.update(Decimal("2.0"), tick.recv_time_mono - 70)
    spread_tracker.update(Decimal("2.0"), tick.recv_time_mono)

    result = engine.attempt_entry(
        signal=_signal(),
        mapping=_mapping(),
        feed=_feed(tick),
        spread_tracker=spread_tracker,
        risk_state=RiskState.ACTIVE,
        risk_state_age_seconds=Decimal("1"),
        daily_pnl=ZERO_PNL,
        broker_connected=True,
        atr_points=Decimal("0.00050"),
    )

    assert not result.executed
    assert "barrier_closed_during_admission" in result.reject_reasons
    # Adapter must never have been called
    assert adapter.submit_calls == []
    # Reservation must NOT be released — reconciler owns it now
    assert "EURUSD" not in reservation.release_calls
    # No position registered
    assert not engine.position_manager.has_open_position("EURUSD")


def test_resolve_admission_failure_does_not_assume_completion():
    """If the broker returns a FILLED result but resolve_admission fails to
    persist it, the engine must not register a position, must not release
    the reservation, and must not permit a duplicate entry. The admission
    must remain unresolved (SUBMITTING) for reconciliation. The engine
    must halt all further entries until account-wide reconciliation."""

    class _FailResolveReservation(_TestReservation):
        def resolve_admission(self, canonical_pair, record=None,
                              position=None, override_audit=None) -> None:
            raise RuntimeError("DB persistence failed")

    adapter = _TestAdapter()
    tick = _fresh_tick()
    adapter.set_quote("EURUSD", tick)
    reservation = _FailResolveReservation()
    engine = _active_engine(adapter=adapter, reservation=reservation)

    spread_tracker = SpreadTracker(SpreadConfig(
        manual_max_spread=Decimal("3.0"),
        adaptive_threshold=Decimal("3.0"), rolling_window_size=100,
        trend_lookback=2, anomaly_multiplier=Decimal("3.0"), stability_period_s=0.0))
    spread_tracker.update(Decimal("2.0"), tick.recv_time_mono - 70)
    spread_tracker.update(Decimal("2.0"), tick.recv_time_mono)

    result = engine.attempt_entry(
        signal=_signal(),
        mapping=_mapping(),
        feed=_feed(tick),
        spread_tracker=spread_tracker,
        risk_state=RiskState.ACTIVE,
        risk_state_age_seconds=Decimal("1"),
        daily_pnl=ZERO_PNL,
        broker_connected=True,
        atr_points=Decimal("0.00050"),
    )

    # Returns structured result, not a raw exception
    assert isinstance(result, ExecutionAttempt)
    # Engine must NOT assume completion
    assert not result.executed
    # Distinguishes unresolved fill from ordinary rejection
    assert result.unresolved_fill is True
    assert "resolve_admission_failed_needs_reconciliation" in result.reject_reasons
    # No position registered despite broker returning FILLED
    assert not engine.position_manager.has_open_position("EURUSD")
    # Reservation must NOT be released — admission stays SUBMITTING
    assert "EURUSD" not in reservation.release_calls

    # Engine halts ALL further entries (even different pairs) until reconciled
    adapter.set_quote("EURUSD", _fresh_tick())
    r2 = engine.attempt_entry(
        signal=_signal(),
        mapping=_mapping(),
        feed=_feed(),
        spread_tracker=spread_tracker,
        risk_state=RiskState.ACTIVE,
        risk_state_age_seconds=Decimal("1"),
        daily_pnl=ZERO_PNL,
        broker_connected=True,
        atr_points=Decimal("0.00050"),
    )
    assert not r2.executed
    assert "halted_unresolved_fill_needs_reconciliation" in r2.reject_reasons


def test_resolve_admission_failure_surfaces_failed_shared_halt():
    """When halt_entry_barrier returns False (DB unreachable), the engine
    must surface this in the result — not silently ignore it."""

    class _FailResolveReservation(_TestReservation):
        def resolve_admission(self, canonical_pair, record=None,
                              position=None, override_audit=None) -> None:
            raise RuntimeError("DB persistence failed")

    class _UnreachableReconciler(_TestReconciler):
        def halt_entry_barrier(self) -> bool:
            return False

    adapter = _TestAdapter()
    tick = _fresh_tick()
    adapter.set_quote("EURUSD", tick)
    reservation = _FailResolveReservation()
    reconciler = _UnreachableReconciler(reconciled=True)
    engine = ExecutionEngine(
        config=ExecutionConfig(
            live_trading_enabled=True,
            max_concurrent_positions=5,
            atr_stop_multiplier=Decimal("1.5"),
        ),
        adapter=adapter,
        durable_store=_TestDurableStore(),
        reservation_provider=reservation,
        reconciler=reconciler,
    )

    spread_tracker = SpreadTracker(SpreadConfig(
        manual_max_spread=Decimal("3.0"),
        adaptive_threshold=Decimal("3.0"), rolling_window_size=100,
        trend_lookback=2, anomaly_multiplier=Decimal("3.0"), stability_period_s=0.0))
    spread_tracker.update(Decimal("2.0"), tick.recv_time_mono - 70)
    spread_tracker.update(Decimal("2.0"), tick.recv_time_mono)

    result = engine.attempt_entry(
        signal=_signal(),
        mapping=_mapping(),
        feed=_feed(tick),
        spread_tracker=spread_tracker,
        risk_state=RiskState.ACTIVE,
        risk_state_age_seconds=Decimal("1"),
        daily_pnl=ZERO_PNL,
        broker_connected=True,
        atr_points=Decimal("0.00050"),
    )

    assert not result.executed
    assert result.unresolved_fill is True
    assert "resolve_admission_failed_needs_reconciliation" in result.reject_reasons
    assert "shared_halt_not_persisted_db_unreachable" in result.reject_reasons
    # Process-local halt still protects this instance
    assert engine._halted_unresolved_fill is True


def test_unresolved_fill_halts_independent_engine_via_shared_barrier():
    """UNIT TEST (in-memory doubles). Two independent engine/provider
    instances share a test barrier (reconciler). When engine 1 gets a
    broker FILLED but resolve_admission fails, the shared barrier must
    close so engine 2 — a separate process with its own reservation
    provider — cannot admit any entry.

    PostgreSQL integration coverage: test_halt_blocks_independent_provider,
    test_halt_blocks_gate_submission, test_submitting_survives_halt in
    test_postgres_store.py.

    Defence-in-depth: even if is_active were somehow bypassed, the
    barrier-aware provider's acquire and gate_submission would also block."""

    class _BarrierAwareReservation(_TestReservation):
        """Mirrors production SQL: acquire and gate_submission check the
        barrier row before proceeding."""
        def __init__(self, reconciler: _TestReconciler) -> None:
            super().__init__()
            self._reconciler = reconciler

        def acquire(self, canonical_pair: str) -> bool:
            if not self._reconciler.is_reconciled():
                return False
            return super().acquire(canonical_pair)

        def gate_submission(self, canonical_pair, order_request=None) -> bool:
            if not self._reconciler.is_reconciled():
                return False
            return super().gate_submission(canonical_pair, order_request)

    class _FailResolveReservation(_TestReservation):
        def resolve_admission(self, canonical_pair, record=None,
                              position=None, override_audit=None) -> None:
            raise RuntimeError("DB persistence failed")

    shared_reconciler = _TestReconciler(reconciled=True)
    assert shared_reconciler.is_reconciled()

    # Engine 1: will fail at resolve_admission
    adapter1 = _TestAdapter()
    tick1 = _fresh_tick()
    adapter1.set_quote("EURUSD", tick1)
    reservation1 = _FailResolveReservation()
    engine1 = ExecutionEngine(
        config=ExecutionConfig(
            live_trading_enabled=True,
            max_concurrent_positions=5,
            atr_stop_multiplier=Decimal("1.5"),
        ),
        adapter=adapter1,
        durable_store=_TestDurableStore(),
        reservation_provider=reservation1,
        reconciler=shared_reconciler,
    )

    spread1 = SpreadTracker(SpreadConfig(
        manual_max_spread=Decimal("3.0"),
        adaptive_threshold=Decimal("3.0"), rolling_window_size=100,
        trend_lookback=2, anomaly_multiplier=Decimal("3.0"), stability_period_s=0.0))
    spread1.update(Decimal("2.0"), tick1.recv_time_mono - 70)
    spread1.update(Decimal("2.0"), tick1.recv_time_mono)

    r1 = engine1.attempt_entry(
        signal=_signal(),
        mapping=_mapping(),
        feed=_feed(tick1),
        spread_tracker=spread1,
        risk_state=RiskState.ACTIVE,
        risk_state_age_seconds=Decimal("1"),
        daily_pnl=ZERO_PNL,
        broker_connected=True,
        atr_points=Decimal("0.00050"),
    )

    # Engine 1 failed to persist the fill
    assert not r1.executed
    assert r1.unresolved_fill is True
    # Shared barrier was closed by halt_entry_barrier
    assert shared_reconciler.halt_calls == 1
    assert not shared_reconciler.is_reconciled()

    # Engine 2: independent instance, different pair, barrier-aware provider
    adapter2 = _TestAdapter()
    tick2 = _fresh_tick()
    adapter2.set_quote("GBPUSD", tick2)
    reservation2 = _BarrierAwareReservation(shared_reconciler)
    engine2 = ExecutionEngine(
        config=ExecutionConfig(
            live_trading_enabled=True,
            max_concurrent_positions=5,
            atr_stop_multiplier=Decimal("1.5"),
        ),
        adapter=adapter2,
        durable_store=_TestDurableStore(),
        reservation_provider=reservation2,
        reconciler=shared_reconciler,
    )

    gbp_signal = Signal(
        direction=SignalDirection.BUY,
        strategy=StrategyType.MOMENTUM,
        regime=MarketRegime.TRENDING,
        strength=Decimal("0.8"),
        canonical_pair="GBPUSD",
        reference_price=Decimal("1.26500"),
        timestamp_ms=1700000000000,
    )
    gbp_mapping = SymbolMapping(
        canonical_pair="GBPUSD",
        broker_symbol="GBPUSD",
        contract=make_contract("GBPUSD", tick_value="1.0", tick_size="0.00001",
                               volume_min="0.01", min_stop_distance="0"),
    )
    gbp_feed = PairFeed(gbp_mapping.contract, staleness_threshold_ms=5000, max_tick_age_s=10.0)
    gbp_feed.process_tick(Tick(
        broker_symbol="GBPUSD",
        bid=Decimal("1.26500"),
        ask=Decimal("1.26520"),
        server_time_ms=1700000000000,
        recv_time_mono=tick2.recv_time_mono,
    ))

    spread2 = SpreadTracker(SpreadConfig(
        manual_max_spread=Decimal("3.0"),
        adaptive_threshold=Decimal("3.0"), rolling_window_size=100,
        trend_lookback=2, anomaly_multiplier=Decimal("3.0"), stability_period_s=0.0))
    spread2.update(Decimal("2.0"), tick2.recv_time_mono - 70)
    spread2.update(Decimal("2.0"), tick2.recv_time_mono)

    r2 = engine2.attempt_entry(
        signal=gbp_signal,
        mapping=gbp_mapping,
        feed=gbp_feed,
        spread_tracker=spread2,
        risk_state=RiskState.ACTIVE,
        risk_state_age_seconds=Decimal("1"),
        daily_pnl=ZERO_PNL,
        broker_connected=True,
        atr_points=Decimal("0.00050"),
    )

    # Engine 2 is blocked — barrier is not READY, is_active returns False
    assert not r2.executed
    assert "execution_engine_inactive" in r2.reject_reasons
    # Adapter 2 never called — blocked before admission gates
    assert adapter2.submit_calls == []
    # Defence-in-depth: provider gates would also block independently
    assert not reservation2.acquire("GBPUSD")
    assert not reservation2.gate_submission("GBPUSD")


def test_duplicate_pair_position_blocked():
    adapter = _TestAdapter()
    tick = _fresh_tick()
    adapter.set_quote("EURUSD", tick)
    engine = _active_engine(adapter=adapter)

    spread_tracker = SpreadTracker(SpreadConfig(
        manual_max_spread=Decimal("3.0"),
        adaptive_threshold=Decimal("3.0"), rolling_window_size=100,
        trend_lookback=2, anomaly_multiplier=Decimal("3.0"), stability_period_s=0.0))
    spread_tracker.update(Decimal("2.0"), tick.recv_time_mono - 70)
    spread_tracker.update(Decimal("2.0"), tick.recv_time_mono)

    # First entry succeeds
    r1 = engine.attempt_entry(
        signal=_signal(),
        mapping=_mapping(),
        feed=_feed(tick),
        spread_tracker=spread_tracker,
        risk_state=RiskState.ACTIVE,
        risk_state_age_seconds=Decimal("1"),
        daily_pnl=ZERO_PNL,
        broker_connected=True,
        atr_points=Decimal("0.00050"),
    )
    assert r1.executed

    # Second entry on same pair blocked
    adapter.set_quote("EURUSD", _fresh_tick())
    r2 = engine.attempt_entry(
        signal=_signal(),
        mapping=_mapping(),
        feed=_feed(),
        spread_tracker=spread_tracker,
        risk_state=RiskState.ACTIVE,
        risk_state_age_seconds=Decimal("1"),
        daily_pnl=ZERO_PNL,
        broker_connected=True,
        atr_points=Decimal("0.00050"),
    )
    assert not r2.executed
    assert any("position" in r or "pending" in r for r in r2.reject_reasons)
