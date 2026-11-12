"""Tests for position_manager — tracking, one-per-pair, reconciliation.

PREPARED — NOT YET RUN. Market-dependent tests deferred until market open.
"""
from decimal import Decimal

from scalping_core.broker_types import ContractSpec
from scalping_core.order_types import OrderSide, PositionInfo
from scalping_core.position_manager import PositionManager
from scalping_core.fake_execution_adapter import FakeExecutionAdapter
from scalping_core.daily_risk import DailyPnL, DailyRiskController
from scalping_core.risk_gate import RiskState
from datetime import date, datetime, timezone


def _make_pos(pair: str = "EURUSD", ticket: int = 100000) -> PositionInfo:
    return PositionInfo(
        broker_ticket=ticket,
        canonical_pair=pair,
        broker_symbol=pair,
        side=OrderSide.BUY,
        volume_lots=Decimal("0.01"),
        open_price=Decimal("1.10020"),
        current_price=Decimal("1.10030"),
        stop_loss=Decimal("1.09950"),
        take_profit=None,
        floating_pnl_usd=Decimal("0.10"),
        open_time_ms=1700000000000,
        swap_usd=Decimal(0),
        commission_usd=Decimal("-0.07"),
    )


def test_register_and_query():
    pm = PositionManager()
    assert not pm.has_open_position("EURUSD")
    assert pm.register_fill(_make_pos())
    assert pm.has_open_position("EURUSD")
    assert pm.count == 1


def test_one_per_pair():
    pm = PositionManager()
    pm.register_fill(_make_pos())
    assert not pm.register_fill(_make_pos(ticket=200000))
    assert pm.count == 1


def test_different_pairs():
    pm = PositionManager()
    pm.register_fill(_make_pos("EURUSD"))
    pm.register_fill(_make_pos("GBPUSD", ticket=200000))
    assert pm.count == 2


def test_mark_closed():
    pm = PositionManager()
    pm.register_fill(_make_pos())
    pm.mark_closed("EURUSD")
    assert not pm.has_open_position("EURUSD")
    assert pm.count == 0


def test_floating_pnl():
    pm = PositionManager()
    pm.register_fill(_make_pos())
    assert pm.floating_pnl_usd() == Decimal("0.10")


def test_sync_removes_closed():
    pm = PositionManager()
    pm.register_fill(_make_pos())
    adapter = FakeExecutionAdapter()
    # Broker reports no positions for EURUSD
    pm.update_from_broker("EURUSD", adapter)
    assert not pm.has_open_position("EURUSD")


def test_update_floating_from_current_bid_uses_current_quote():
    pm = PositionManager()
    pm.register_fill(_make_pos())
    contract = ContractSpec(
        broker_symbol="EURUSD", digits=5, point=Decimal("0.00001"),
        tick_size=Decimal("0.00001"), tick_value=Decimal("1"),
        contract_size=Decimal("100000"), volume_min=Decimal("0.01"),
        volume_max=Decimal("100"), volume_step=Decimal("0.01"),
        min_stop_distance=Decimal("0.0001"), trade_allowed=True,
        margin_initial=None, commission_per_lot=None, swap_long=None, swap_short=None,
    )
    updated = pm.update_floating_from_quote(
        "EURUSD", bid=Decimal("1.10040"), ask=Decimal("1.10050"),
        contract=contract, account_to_usd_rate=Decimal("1"),
    )
    assert updated is not None
    assert updated.current_price == Decimal("1.10040")
    assert updated.floating_pnl_usd == Decimal("0.20")
    assert pm.floating_pnl_usd() == Decimal("0.20")


def test_floating_tick_updates_and_persists_daily_threshold():
    class Store:
        def __init__(self):
            self.snapshot = None
            self.transition = None

        def save_risk_snapshot(self, day, state, pnl):
            self.snapshot = (state, pnl)

        def save_risk_transition(self, day, state, pnl, event):
            self.transition = (state, pnl, event)

    pm = PositionManager()
    pm.register_fill(_make_pos())
    store = Store()
    controller = DailyRiskController(store)
    contract = ContractSpec(
        "EURUSD", 5, Decimal("0.00001"), Decimal("0.00001"), Decimal("1"),
        Decimal("100000"), Decimal("0.01"), Decimal("100"), Decimal("0.01"),
        Decimal("0.0001"), True, None, None, None, None,
    )
    state, pnl = pm.update_floating_and_persist_risk(
        "EURUSD", bid=Decimal("1.10040"), ask=Decimal("1.10050"),
        contract=contract, account_to_usd_rate=Decimal("1"),
        controller=controller, account_id="acct", trading_day=date(2026, 11, 11),
        current_state=RiskState.ACTIVE,
        pnl=DailyPnL(Decimal("14.9"), Decimal(0), Decimal(0), Decimal(0)),
        at=datetime(2026, 11, 11, 12, tzinfo=timezone.utc),
    )
    assert pnl.floating_pnl_usd == Decimal("0.20")
    assert state is RiskState.PROFIT_LOCKED
    assert store.transition[2].event_type.value == "LIMIT_TRIGGERED"

    pm.mark_closed("EURUSD")
    state, pnl = pm.update_floating_and_persist_risk(
        "EURUSD", bid=Decimal("1.10040"), ask=Decimal("1.10050"),
        contract=contract, account_to_usd_rate=Decimal("1"),
        controller=controller, account_id="acct", trading_day=date(2026, 11, 11),
        current_state=state, pnl=pnl,
        at=datetime(2026, 11, 11, 12, 1, tzinfo=timezone.utc),
    )
    assert pnl.floating_pnl_usd == Decimal(0)
    assert store.snapshot[1].floating_pnl_usd == Decimal(0)


def test_settle_position():
    pm = PositionManager()
    pm.register_fill(_make_pos())
    settled = pm.settle_position(
        "EURUSD", exit_price=Decimal("1.10070"),
        exit_time_ms=1700000060000, realized_pnl=Decimal("0.50"),
        commission=Decimal("-0.07"), swap=Decimal("0"),
    )
    assert settled is not None
    assert settled.current_price == Decimal("1.10070")
    assert settled.floating_pnl_usd == Decimal("0.50")
    assert not pm.has_open_position("EURUSD")


def test_settle_nonexistent_pair():
    pm = PositionManager()
    assert pm.settle_position(
        "EURUSD", exit_price=Decimal("1.10070"),
        exit_time_ms=0, realized_pnl=Decimal(0),
        commission=Decimal(0), swap=Decimal(0),
    ) is None
