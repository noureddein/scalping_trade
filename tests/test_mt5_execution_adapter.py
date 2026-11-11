"""Tests for mt5_execution_adapter — hard-disabled execution + enabled-path contract.

PREPARED — NOT YET RUN. Deferred until market open per owner decision.

Tests the disabled path (FAILED without transmitting) and the enabled
path's FAILED-vs-UNKNOWN contract using monkeypatching to bypass the
module-level _EXECUTION_DISABLED flag. No real TCP connection is made.
"""
import json
import struct
from decimal import Decimal
from unittest.mock import MagicMock

import scalping_core.mt5_execution_adapter as mt5_mod
from scalping_core.mt5_execution_adapter import Mt5ExecutionAdapter
from scalping_core.order_types import OrderRequest, OrderSide, OrderState


def _request() -> OrderRequest:
    return OrderRequest(
        canonical_pair="EURUSD",
        broker_symbol="EURUSD",
        side=OrderSide.BUY,
        volume_lots=Decimal("0.01"),
        stop_loss_price=Decimal("1.09"),
        take_profit_price=None,
        idempotency_key="test:1700000000000:abc12345",
        signal_timestamp_ms=1700000000000,
        fresh_quote_bid=Decimal("1.10000"),
        fresh_quote_ask=Decimal("1.10020"),
        fresh_quote_time_ms=1700000000000,
    )


def test_not_simulation():
    adapter = Mt5ExecutionAdapter(port=9999)
    assert not adapter.is_simulation


def test_execution_disabled_by_default():
    """Hard-disabled adapter reports is_execution_enabled=False."""
    adapter = Mt5ExecutionAdapter(port=9999)
    assert not adapter.is_execution_enabled


def test_submit_order_returns_failed():
    adapter = Mt5ExecutionAdapter(port=9999)
    result = adapter.submit_order(_request())
    assert result.state == OrderState.FAILED
    assert result.reject_reason == "execution_hard_disabled"


def test_close_position_returns_failed():
    adapter = Mt5ExecutionAdapter(port=9999)
    result = adapter.close_position(broker_ticket=1001, volume_lots=Decimal("0.01"))
    assert result.state == OrderState.FAILED
    assert result.reject_reason == "execution_hard_disabled"


def test_get_fresh_quote_none_without_data():
    adapter = Mt5ExecutionAdapter(port=9999)
    assert adapter.get_fresh_quote("EURUSD") is None


def test_update_quote_and_retrieve():
    from scalping_core.broker_types import Tick
    import time

    adapter = Mt5ExecutionAdapter(port=9999)
    tick = Tick(
        broker_symbol="EURUSD",
        bid=Decimal("1.10000"),
        ask=Decimal("1.10020"),
        server_time_ms=1700000000000,
        recv_time_mono=time.monotonic(),
    )
    adapter.update_quote(tick)
    result = adapter.get_fresh_quote("EURUSD")
    assert result is not None
    assert result.bid == Decimal("1.10000")


def test_stale_quote_returns_none():
    from scalping_core.broker_types import Tick

    adapter = Mt5ExecutionAdapter(port=9999)
    tick = Tick(
        broker_symbol="EURUSD",
        bid=Decimal("1.10000"),
        ask=Decimal("1.10020"),
        server_time_ms=1700000000000,
        recv_time_mono=0.0,  # ancient monotonic time
    )
    adapter.update_quote(tick)
    adapter._quotes_time["EURUSD"] = 0.0  # force stale
    assert adapter.get_fresh_quote("EURUSD") is None


def test_connect_fails_gracefully_no_server():
    adapter = Mt5ExecutionAdapter(port=19999, connect_timeout_s=0.1)
    assert not adapter.connect()


def test_disconnect_idempotent():
    adapter = Mt5ExecutionAdapter(port=9999)
    adapter.disconnect()  # no error when not connected
    adapter.disconnect()  # still no error


# ---------------------------------------------------------------------------
# Enabled-path tests: FAILED vs UNKNOWN contract
# Uses monkeypatching to bypass _EXECUTION_DISABLED. No real TCP.
# ---------------------------------------------------------------------------

def _enable_execution(monkeypatch):
    """Bypass _EXECUTION_DISABLED for testing the real code path."""
    monkeypatch.setattr(mt5_mod, "_EXECUTION_DISABLED", False)


def _fake_ea_response(state: str, ticket: int = 1001, **extra) -> bytes:
    """Build a length-prefixed JSON EA response."""
    data = {"state": state, "broker_ticket": ticket, **extra}
    payload = json.dumps(data).encode("utf-8")
    return struct.pack("!I", len(payload)) + payload


def test_submit_no_socket_returns_failed(monkeypatch):
    """Enabled path, no socket connected → FAILED (no bytes possible)."""
    _enable_execution(monkeypatch)
    adapter = Mt5ExecutionAdapter(port=9999)
    result = adapter.submit_order(_request())
    assert result.state == OrderState.FAILED
    assert result.reject_reason == "not_connected"


def test_close_no_socket_returns_failed(monkeypatch):
    """Enabled path, no socket connected → FAILED."""
    _enable_execution(monkeypatch)
    adapter = Mt5ExecutionAdapter(port=9999)
    result = adapter.close_position(broker_ticket=1001, volume_lots=Decimal("0.01"))
    assert result.state == OrderState.FAILED
    assert result.reject_reason == "not_connected"


def test_submit_send_failure_returns_unknown(monkeypatch):
    """Enabled path, socket exists but sendall fails → UNKNOWN.

    Once a socket is present, bytes may have left the process even if
    sendall raises. The adapter must return UNKNOWN, never FAILED.
    """
    _enable_execution(monkeypatch)
    adapter = Mt5ExecutionAdapter(port=9999)

    mock_sock = MagicMock()
    mock_sock.sendall.side_effect = OSError("broken pipe")
    adapter._sock = mock_sock

    result = adapter.submit_order(_request())
    assert result.state == OrderState.UNKNOWN
    assert result.reject_reason == "ea_communication_failed"


def test_close_send_failure_returns_unknown(monkeypatch):
    """Enabled path, socket exists but send fails → UNKNOWN."""
    _enable_execution(monkeypatch)
    adapter = Mt5ExecutionAdapter(port=9999)

    mock_sock = MagicMock()
    mock_sock.sendall.side_effect = OSError("broken pipe")
    adapter._sock = mock_sock

    result = adapter.close_position(broker_ticket=1001, volume_lots=Decimal("0.01"))
    assert result.state == OrderState.UNKNOWN
    assert result.reject_reason == "ea_communication_failed"


def test_submit_successful_response_parsed(monkeypatch):
    """Enabled path, EA returns a valid FILLED response."""
    _enable_execution(monkeypatch)
    adapter = Mt5ExecutionAdapter(port=9999)

    response_bytes = _fake_ea_response(
        "FILLED", ticket=2001, fill_price="1.10015", fill_volume="0.01",
    )
    mock_sock = MagicMock()
    mock_sock.sendall.return_value = None
    mock_sock.recv.side_effect = [response_bytes[:4], response_bytes[4:]]
    adapter._sock = mock_sock

    result = adapter.submit_order(_request())
    assert result.state == OrderState.FILLED
    assert result.broker_ticket == 2001
    assert result.fill_price == Decimal("1.10015")


def test_submit_rejected_response_parsed(monkeypatch):
    """Enabled path, EA returns REJECTED."""
    _enable_execution(monkeypatch)
    adapter = Mt5ExecutionAdapter(port=9999)

    response_bytes = _fake_ea_response(
        "REJECTED", ticket=0, reject_reason="no_money",
    )
    mock_sock = MagicMock()
    mock_sock.sendall.return_value = None
    mock_sock.recv.side_effect = [response_bytes[:4], response_bytes[4:]]
    adapter._sock = mock_sock

    result = adapter.submit_order(_request())
    assert result.state == OrderState.REJECTED
    assert result.reject_reason == "no_money"


def test_submit_sends_correct_payload(monkeypatch):
    """Verify the request message shape sent to the EA."""
    _enable_execution(monkeypatch)
    adapter = Mt5ExecutionAdapter(port=9999)

    response_bytes = _fake_ea_response("FILLED", ticket=3001)
    mock_sock = MagicMock()
    mock_sock.sendall.return_value = None
    mock_sock.recv.side_effect = [response_bytes[:4], response_bytes[4:]]
    adapter._sock = mock_sock

    req = _request()
    adapter.submit_order(req)

    # Extract what was sent
    sent_frame = mock_sock.sendall.call_args[0][0]
    msg_len = struct.unpack("!I", sent_frame[:4])[0]
    sent_data = json.loads(sent_frame[4:4 + msg_len].decode("utf-8"))

    assert sent_data["type"] == "request"
    assert sent_data["data"]["request"] == "order_send"
    assert sent_data["data"]["symbol"] == "EURUSD"
    assert sent_data["data"]["action"] == "ORDER_TYPE_BUY"
    assert sent_data["data"]["volume"] == "0.01"
    assert sent_data["data"]["sl"] == "1.09"
    # Comment is idempotency_key truncated to 31 chars
    assert sent_data["data"]["comment"] == req.idempotency_key[:31]


def test_submit_sell_order_action(monkeypatch):
    """SELL order sends ORDER_TYPE_SELL."""
    _enable_execution(monkeypatch)
    adapter = Mt5ExecutionAdapter(port=9999)

    response_bytes = _fake_ea_response("FILLED", ticket=4001)
    mock_sock = MagicMock()
    mock_sock.sendall.return_value = None
    mock_sock.recv.side_effect = [response_bytes[:4], response_bytes[4:]]
    adapter._sock = mock_sock

    req = OrderRequest(
        canonical_pair="EURUSD", broker_symbol="EURUSD",
        side=OrderSide.SELL, volume_lots=Decimal("0.01"),
        stop_loss_price=Decimal("1.11"), take_profit_price=None,
        idempotency_key="test:sell:key", signal_timestamp_ms=1700000000000,
        fresh_quote_bid=Decimal("1.10000"), fresh_quote_ask=Decimal("1.10020"),
        fresh_quote_time_ms=1700000000000,
    )
    adapter.submit_order(req)

    sent_frame = mock_sock.sendall.call_args[0][0]
    sent_data = json.loads(sent_frame[4:].decode("utf-8"))
    assert sent_data["data"]["action"] == "ORDER_TYPE_SELL"


def test_close_successful_response_parsed(monkeypatch):
    """Enabled path, close_position returns parsed result."""
    _enable_execution(monkeypatch)
    adapter = Mt5ExecutionAdapter(port=9999)

    response_bytes = _fake_ea_response("FILLED", ticket=5001)
    mock_sock = MagicMock()
    mock_sock.sendall.return_value = None
    mock_sock.recv.side_effect = [response_bytes[:4], response_bytes[4:]]
    adapter._sock = mock_sock

    result = adapter.close_position(broker_ticket=5001, volume_lots=Decimal("0.01"))
    assert result.state == OrderState.FILLED
    assert result.broker_ticket == 5001
