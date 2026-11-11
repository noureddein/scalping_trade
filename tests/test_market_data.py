"""Tests for market_data module — tick validation, normalization, feed health."""
from decimal import Decimal

from scalping_core.broker_types import Tick
from scalping_core.fake_broker import make_contract, make_tick
from scalping_core.market_data import (
    PairFeed,
    TickRejectReason,
    pip_size,
    spread_in_pips,
)


def _feed() -> PairFeed:
    return PairFeed(make_contract("EURUSD"))


def test_pip_size_5_digit():
    c = make_contract("EURUSD", digits=5, point="0.00001")
    assert pip_size(c) == Decimal("0.0001")


def test_pip_size_3_digit():
    c = make_contract("USDJPY", digits=3, point="0.001")
    assert pip_size(c) == Decimal("0.01")


def test_pip_size_4_digit():
    c = make_contract("EURUSD", digits=4, point="0.0001")
    assert pip_size(c) == Decimal("0.0001")


def test_spread_in_pips_basic():
    c = make_contract("EURUSD", digits=5, point="0.00001")
    t = make_tick(bid="1.10000", ask="1.10020")
    assert spread_in_pips(t, c) == Decimal("2.0")


def test_spread_in_pips_jpy():
    c = make_contract("USDJPY", digits=3, point="0.001")
    t = make_tick(broker_symbol="USDJPY", bid="150.100", ask="150.120")
    assert spread_in_pips(t, c) == Decimal("2.0")


def test_accept_valid_tick():
    feed = _feed()
    result = feed.process_tick(make_tick(recv_time_mono=1.0))
    assert result.accepted
    assert result.spread_pips is not None
    assert feed.accept_count == 1


def test_reject_zero_bid():
    feed = _feed()
    result = feed.process_tick(make_tick(bid="0", recv_time_mono=1.0))
    assert not result.accepted
    assert result.reject_reason == TickRejectReason.INVALID_BID


def test_reject_negative_ask():
    feed = _feed()
    result = feed.process_tick(make_tick(ask="-1.0", recv_time_mono=1.0))
    assert not result.accepted
    assert result.reject_reason == TickRejectReason.INVALID_ASK


def test_reject_inverted_spread():
    feed = _feed()
    result = feed.process_tick(make_tick(bid="1.10020", ask="1.10000", recv_time_mono=1.0))
    assert not result.accepted
    assert result.reject_reason == TickRejectReason.INVERTED_SPREAD


def test_reject_duplicate():
    feed = _feed()
    t = make_tick(recv_time_mono=1.0)
    feed.process_tick(t)
    result = feed.process_tick(make_tick(recv_time_mono=2.0))
    assert not result.accepted
    assert result.reject_reason == TickRejectReason.DUPLICATE


def test_reject_out_of_order():
    feed = _feed()
    feed.process_tick(make_tick(server_time_ms=2000, recv_time_mono=1.0))
    result = feed.process_tick(make_tick(server_time_ms=1000, recv_time_mono=2.0))
    assert not result.accepted
    assert result.reject_reason == TickRejectReason.OUT_OF_ORDER


def test_is_fresh():
    feed = _feed()
    assert not feed.is_fresh(now_mono=0.0)
    feed.process_tick(make_tick(recv_time_mono=1.0))
    assert feed.is_fresh(now_mono=2.0)
    assert not feed.is_fresh(now_mono=100.0)
