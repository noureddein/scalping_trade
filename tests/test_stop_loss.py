"""Tests for stop_loss calculator (§10.2).

PREPARED — NOT YET RUN. Market-dependent tests deferred until market open.
"""
from decimal import Decimal

from scalping_core.order_types import OrderSide
from scalping_core.stop_loss import calculate_stop_loss
from scalping_core.fake_broker import make_contract


def _std_contract():
    return make_contract("EURUSD", tick_value="1.0", tick_size="0.00001",
                         volume_min="0.01", min_stop_distance="0")


def test_buy_stop_below_entry():
    r = calculate_stop_loss(
        side=OrderSide.BUY,
        entry_price=Decimal("1.10000"),
        atr_points=Decimal("0.00050"),
        contract=_std_contract(),
    )
    assert r.approved
    assert r.stop_price < Decimal("1.10000")
    assert r.stop_price == Decimal("1.10000") - r.stop_distance_points


def test_sell_stop_above_entry():
    r = calculate_stop_loss(
        side=OrderSide.SELL,
        entry_price=Decimal("1.10000"),
        atr_points=Decimal("0.00050"),
        contract=_std_contract(),
    )
    assert r.approved
    assert r.stop_price > Decimal("1.10000")


def test_cash_ceiling_caps_stop():
    """ATR suggests wide stop but $0.50 ceiling caps it."""
    r = calculate_stop_loss(
        side=OrderSide.BUY,
        entry_price=Decimal("1.10000"),
        atr_points=Decimal("0.01000"),  # very wide ATR
        contract=_std_contract(),
    )
    assert r.approved
    assert r.estimated_loss_usd <= Decimal("0.50")


def test_broker_min_stop_exceeds_ceiling():
    """Broker requires wider stop than $0.50 allows — must reject."""
    contract = make_contract("EURUSD", tick_value="1.0", tick_size="0.00001",
                             volume_min="0.01", min_stop_distance="0.01000")
    r = calculate_stop_loss(
        side=OrderSide.BUY,
        entry_price=Decimal("1.10000"),
        atr_points=Decimal("0.00050"),
        contract=contract,
    )
    assert not r.approved
    assert r.reject_reason == "broker_min_stop_exceeds_cash_ceiling"


def test_non_finite_entry_rejected():
    r = calculate_stop_loss(
        side=OrderSide.BUY,
        entry_price=Decimal("NaN"),
        atr_points=Decimal("0.00050"),
        contract=_std_contract(),
    )
    assert not r.approved


def test_zero_atr_rejected():
    r = calculate_stop_loss(
        side=OrderSide.BUY,
        entry_price=Decimal("1.10000"),
        atr_points=Decimal("0"),
        contract=_std_contract(),
    )
    assert not r.approved
    assert r.reject_reason == "atr_non_positive"
