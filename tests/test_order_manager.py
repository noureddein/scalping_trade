"""Tests for order_manager — lifecycle, idempotency, reconciliation.

PREPARED — NOT YET RUN. Market-dependent tests deferred until market open.
"""
from decimal import Decimal

from scalping_core.order_types import OrderRequest, OrderResult, OrderSide, OrderState
from scalping_core.order_manager import OrderManager
from scalping_core.fake_execution_adapter import FakeExecutionAdapter


def _make_request(pair: str = "EURUSD", key: str = "test-key-1") -> OrderRequest:
    return OrderRequest(
        canonical_pair=pair,
        broker_symbol="EURUSD",
        side=OrderSide.BUY,
        volume_lots=Decimal("0.01"),
        stop_loss_price=Decimal("1.09950"),
        take_profit_price=None,
        idempotency_key=key,
        signal_timestamp_ms=1700000000000,
        fresh_quote_bid=Decimal("1.10000"),
        fresh_quote_ask=Decimal("1.10020"),
        fresh_quote_time_ms=1700000000000,
    )


def test_submit_fills_by_default():
    mgr = OrderManager()
    adapter = FakeExecutionAdapter()
    record = mgr.submit(_make_request(), adapter)
    assert record.result.state == OrderState.FILLED
    assert record.result.broker_ticket is not None


def test_idempotency_returns_same_record():
    mgr = OrderManager()
    adapter = FakeExecutionAdapter()
    req = _make_request()
    r1 = mgr.submit(req, adapter)
    r2 = mgr.submit(req, adapter)
    assert r1 is r2
    assert len(adapter.submit_calls) == 1


def test_has_pending_for_pair():
    mgr = OrderManager()
    adapter = FakeExecutionAdapter()
    adapter.set_next_fill(OrderResult(state=OrderState.SUBMITTED, broker_ticket=1))
    mgr.submit(_make_request(), adapter)
    assert mgr.has_pending_for_pair("EURUSD")
    assert not mgr.has_pending_for_pair("GBPUSD")


def test_reconcile_unknown_key():
    mgr = OrderManager()
    adapter = FakeExecutionAdapter()
    assert mgr.reconcile("nonexistent", adapter) is None


def test_reconcile_queries_broker():
    mgr = OrderManager()
    adapter = FakeExecutionAdapter()
    adapter.set_next_fill(OrderResult(state=OrderState.SUBMITTED, broker_ticket=42))
    mgr.submit(_make_request(), adapter)

    adapter.set_next_query(OrderResult(state=OrderState.FILLED, broker_ticket=42,
                                        fill_price=Decimal("1.10020")))
    record = mgr.reconcile("test-key-1", adapter)
    assert record.result.state == OrderState.FILLED


def test_rejection_is_terminal():
    mgr = OrderManager()
    adapter = FakeExecutionAdapter()
    adapter.set_next_fill(OrderResult(state=OrderState.REJECTED, reject_reason="no_money"))
    record = mgr.submit(_make_request(), adapter)
    assert record.result.state == OrderState.REJECTED
    assert not mgr.has_pending_for_pair("EURUSD")
