from decimal import Decimal
import socket
import threading

import pytest

from scalping_core.broker_adapter import BrokerUnavailableError
from scalping_core.broker_types import BrokerSymbol, ConnectionStatus
from scalping_core.fake_broker import FakeBrokerAdapter, make_contract, make_demo_account
from scalping_core.tcp_broker_adapter import (
    _parse_account_info,
    _parse_contract_spec,
    _parse_symbols,
    recv_message,
    send_message,
)


def contract_payload() -> dict:
    return {
        "broker_symbol": "EURUSD_",
        "digits": 5,
        "point": "0.00001",
        "tick_size": "0.00001",
        "tick_value": "1.0",
        "contract_size": "100000",
        "volume_min": "0.01",
        "volume_max": "100",
        "volume_step": "0.01",
        "min_stop_distance": "0",
        "trading_permissions": "FULL",
        "margin_requirement": "1000",
        "commission": "0",
        "swap_long": "-1.5",
        "swap_short": "0.5",
    }


def test_contract_parser_requires_all_fifteen_valid_fields() -> None:
    parsed = _parse_contract_spec(contract_payload())
    assert parsed is not None
    assert parsed.eligible_for_trading
    assert parsed.commission_per_lot == Decimal("0")
    assert parsed.trading_permissions == "FULL"

    for field in ("margin_requirement", "commission", "swap_long", "swap_short"):
        payload = contract_payload()
        payload.pop(field)
        assert _parse_contract_spec(payload) is None

    payload = contract_payload()
    payload["commission"] = None
    assert _parse_contract_spec(payload) is None


def test_contract_parser_rejects_nonfinite_and_invalid_constraints() -> None:
    payload = contract_payload()
    payload["point"] = "NaN"
    assert _parse_contract_spec(payload) is None

    payload = contract_payload()
    payload["digits"] = -1
    assert _parse_contract_spec(payload) is None


def test_account_parser_supports_spec_field_names_and_validates_values() -> None:
    account = _parse_account_info({
        "account_number": 123,
        "broker_name": "Demo Broker",
        "balance": "100.00",
        "equity": "99.50",
        "margin": "1.00",
        "currency": "USD",
    })
    assert account is not None
    assert account.account_number == 123
    assert account.broker_name == "Demo Broker"
    assert account.margin == Decimal("1.00")
    assert _parse_account_info({**{
        "account_number": 123, "broker_name": "Demo", "balance": "0",
        "equity": "0", "margin": "0", "currency": "USD",
    }}) is None


def test_symbol_parser_preserves_permissions_and_rejects_missing_flags() -> None:
    symbols = _parse_symbols({"symbols": [
        {"name": "EURUSD_", "trading_permitted": True},
        {"name": "XAUUSD", "trading_permitted": False},
    ]}, 123)
    assert symbols == [
        BrokerSymbol("EURUSD_", True, 123),
        BrokerSymbol("XAUUSD", False, 123),
    ]
    assert _parse_symbols({"symbols": [{"name": "EURUSD_"}]}, 123) is None


def test_owner_mapping_is_confirmed_and_unavailable_calls_fail_closed() -> None:
    adapter = FakeBrokerAdapter(
        symbols={"EURUSD_": make_contract("EURUSD_")},
        account=make_demo_account(),
    )
    with pytest.raises(BrokerUnavailableError):
        adapter.discover_symbols()

    adapter.connect()
    mapping = adapter.update_mapping("EURUSD", "EURUSD_")
    assert mapping.confirmed_by_owner
    assert adapter.get_mapping("EURUSD") == mapping
    with pytest.raises(ValueError, match="unavailable"):
        adapter.update_mapping("GBPUSD", "MISSING")


def test_reconnecting_is_a_distinct_connection_state() -> None:
    assert ConnectionStatus.RECONNECTING.value == "RECONNECTING"


def test_framing_helpers_round_trip_a_message() -> None:
    sender, receiver = socket.socketpair()
    try:
        message = {"type": "heartbeat", "data": {"sequence": 1}}
        thread = threading.Thread(target=send_message, args=(sender, message))
        thread.start()
        assert recv_message(receiver) == message
        thread.join(timeout=1)
        assert not thread.is_alive()
    finally:
        sender.close()
        receiver.close()
