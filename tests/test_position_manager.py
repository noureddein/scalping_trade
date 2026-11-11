"""Tests for position_manager — tracking, one-per-pair, reconciliation.

PREPARED — NOT YET RUN. Market-dependent tests deferred until market open.
"""
from decimal import Decimal

from scalping_core.order_types import OrderSide, PositionInfo
from scalping_core.position_manager import PositionManager
from scalping_core.fake_execution_adapter import FakeExecutionAdapter


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
