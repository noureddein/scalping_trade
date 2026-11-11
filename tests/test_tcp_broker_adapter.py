"""Tests for the Architecture C TCP broker adapter.

Uses a local socket harness to simulate an EA client pushing data to the
Python backend server. No MT5, no Wine, no network beyond loopback.
"""
from __future__ import annotations

import json
import socket
import struct
import time
from decimal import Decimal

import pytest

from scalping_core.broker_adapter import BrokerUnavailableError, SymbolUnavailableError
from scalping_core.broker_types import ConnectionStatus, SymbolMapping
from scalping_core.fake_broker import make_contract
from scalping_core.market_data import MarketDataProcessor
from scalping_core.tcp_broker_adapter import (
    TcpBrokerAdapter, _parse_market_status, _parse_tick_data, recv_message,
)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _send_message(sock: socket.socket, msg_type: str, data: dict) -> None:
    payload = json.dumps({"type": msg_type, "data": data}).encode("utf-8")
    sock.sendall(struct.pack("!I", len(payload)) + payload)


def _send_raw_json(sock: socket.socket, obj: object) -> None:
    payload = json.dumps(obj).encode("utf-8")
    sock.sendall(struct.pack("!I", len(payload)) + payload)


def _connect_client(port: int, timeout: float = 2.0) -> socket.socket:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(("127.0.0.1", port))
            return s
        except ConnectionRefusedError:
            s.close()
            time.sleep(0.05)
    raise TimeoutError(f"Could not connect to 127.0.0.1:{port}")


def test_tick_data_parser_keeps_valid_ticks_and_rejects_bad_items():
    parsed = _parse_tick_data({
        "pair": "EURUSD.x", "run_counter": 3, "batch_sequence": 8,
        "ticks": [
            {"bid": "1.1", "ask": "1.1001", "broker_timestamp": "2026-11-11T10:00:00.123Z"},
            {"bid": "NaN", "ask": "1.2", "broker_timestamp": "2026-11-11T10:00:01Z"},
            {"bid": "1.2", "ask": "1.1", "broker_timestamp": "2026-11-11T10:00:02Z"},
            {"bid": "1.1", "ask": "1.2", "broker_timestamp": "no-time"},
        ],
    }, 123.0)
    assert parsed is not None
    pair, run_counter, sequence, dropped, ticks = parsed
    assert (pair, run_counter, sequence, dropped) == ("EURUSD.x", 3, 8, 0)
    assert len(ticks) == 1
    assert ticks[0].broker_timestamp.isoformat() == "2026-11-11T10:00:00.123000+00:00"
    assert ticks[0].local_receipt_time == 123.0


def test_market_status_parser_requires_aware_timestamp_and_boolean():
    valid = _parse_market_status({"pair": "EURUSD", "is_market_open": True,
                                  "server_time": "2026-11-11T10:00:00Z"})
    assert valid is not None and valid[1] is True
    assert _parse_market_status({"pair": "EURUSD", "is_market_open": 1,
                                 "server_time": "2026-11-11T10:00:00Z"}) is None
    assert _parse_market_status({"pair": "EURUSD", "is_market_open": True,
                                 "server_time": "2026-11-11T10:00:00"}) is None


def test_tick_data_message_maps_broker_symbol_and_forwards_batch_status():
    batches = []
    statuses = []
    a = TcpBrokerAdapter(1, on_tick_batch=lambda *args: batches.append(args),
                         on_market_status=lambda *args: statuses.append(args))
    a._owner_mappings["EURUSD"] = SymbolMapping("EURUSD", "EURUSD.x", make_contract("EURUSD.x"), True)
    tick_payload = json.dumps({"type": "TICK_DATA", "data": {
        "pair": "EURUSD.x", "run_counter": 4, "batch_sequence": 0,
        "ticks": [{"bid": "1.1", "ask": "1.1001", "broker_timestamp": "2026-11-11T10:00:00Z"}],
    }}).encode()
    a._handle_message(tick_payload)
    status_payload = json.dumps({"type": "MARKET_STATUS", "data": {
        "pair": "EURUSD.x", "is_market_open": True,
        "server_time": "2026-11-11T10:00:00Z",
    }}).encode()
    a._handle_message(status_payload)
    assert len(batches) == 1
    assert batches[0][0:3] == ("EURUSD", 0, 4)
    assert batches[0][3][0].pair == "EURUSD"
    assert statuses[0][0:2] == ("EURUSD", True)


def test_adapter_to_market_data_pipeline_only_delivers_valid_ticks():
    delivered = []
    processor = MarketDataProcessor(delivered.append)
    processor.register_pair("EURUSD", "EURUSD.x", staleness_threshold_s=5,
                            normal_min_ticks_per_second=0.1,
                            low_min_ticks_per_second=0.01,
                            none_after_s=30, baseline_window_s=10)
    a = TcpBrokerAdapter(1, on_tick_batch=processor.consume_tick_batch,
                         on_market_status=processor.consume_market_status)
    a._owner_mappings["EURUSD"] = SymbolMapping("EURUSD", "EURUSD.x", make_contract("EURUSD.x"), True)
    payload = json.dumps({"type": "TICK_DATA", "data": {
        "pair": "EURUSD.x", "run_counter": 1, "batch_sequence": 0,
        "ticks": [
            {"bid": "1.1", "ask": "1.1001", "broker_timestamp": "2026-11-11T10:00:00Z"},
            {"bid": "1.1", "ask": "1.1001", "broker_timestamp": "2026-11-11T10:00:00Z"},
            {"bid": "1.2", "ask": "1.1", "broker_timestamp": "2026-11-11T10:00:01Z"},
        ],
    }}).encode()
    a._handle_message(payload)
    assert len(delivered) == 1
    assert delivered[0].pair == "EURUSD"
    status = json.dumps({"type": "MARKET_STATUS", "data": {
        "pair": "EURUSD.x", "is_market_open": False,
        "server_time": "2026-11-11T10:00:00Z",
    }}).encode()
    a._handle_message(status)
    assert processor.health("EURUSD").is_entry_blocked


@pytest.fixture
def adapter():
    port = _find_free_port()
    a = TcpBrokerAdapter(port=port, heartbeat_timeout_s=5.0, data_staleness_s=10.0)
    yield a
    a.disconnect()


class TestTcpConnect:
    def test_connect_starts_listener(self, adapter):
        status = adapter.connect()
        assert status is ConnectionStatus.CONNECTED

    def test_health_check_no_client(self, adapter):
        adapter.connect()
        assert adapter.health_check() is ConnectionStatus.DISCONNECTED

    def test_health_check_after_heartbeat(self, adapter):
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            _send_message(client, "heartbeat", {})
            time.sleep(0.1)
            assert adapter.health_check() is ConnectionStatus.RECONNECTING
        finally:
            client.close()

    def test_disconnect_cleans_up(self, adapter):
        adapter.connect()
        adapter.disconnect()
        assert adapter.health_check() is ConnectionStatus.DISCONNECTED


class TestTcpAccountInfo:
    def test_receives_account_info(self, adapter):
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            _send_message(client, "account_info", {
                "login": 12345678,
                "server": "MetaQuotes-Demo",
                "currency": "USD",
                "balance": "10000.00",
                "equity": "10000.00",
                "margin_free": "10000.00",
                "account_type": "demo",
                "leverage": 100,
                "company": "MetaQuotes",
            })
            time.sleep(0.1)
            info = adapter.get_account_info()
            assert info is not None
            assert info.login == 12345678
            assert info.currency == "USD"
            assert info.balance == Decimal("10000.00")
        finally:
            client.close()

    def test_returns_none_when_no_data(self, adapter):
        adapter.connect()
        with pytest.raises(BrokerUnavailableError):
            adapter.get_account_info()

    def test_stale_data_returns_none(self):
        port = _find_free_port()
        a = TcpBrokerAdapter(port=port, heartbeat_timeout_s=5.0, data_staleness_s=0.1)
        try:
            a.connect()
            client = _connect_client(port)
            try:
                _send_message(client, "account_info", {
                    "login": 1, "server": "s", "currency": "USD",
                    "balance": "100", "equity": "100", "margin_free": "0",
                })
                time.sleep(0.2)
                with pytest.raises(BrokerUnavailableError):
                    a.get_account_info()
            finally:
                client.close()
        finally:
            a.disconnect()


class TestTcpSymbolDiscovery:
    def test_receives_symbol_list(self, adapter):
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            _send_message(client, "account_info", _ACCOUNT_DATA)
            _send_message(client, "symbol_list", {
                "symbols": [
                    {"name": "EURUSD_", "trading_permitted": True},
                    {"name": "GBPJPY", "trading_permitted": True},
                    {"name": "XAUUSD", "trading_permitted": True},
                ],
            })
            time.sleep(0.1)
            syms = adapter.discover_symbols()
            assert {symbol.broker_name for symbol in syms} == {"EURUSD_", "GBPJPY", "XAUUSD"}
        finally:
            client.close()

    def test_empty_when_no_data(self, adapter):
        adapter.connect()
        with pytest.raises(BrokerUnavailableError):
            adapter.discover_symbols()


class TestTcpContractSpec:
    def test_receives_contract_spec(self, adapter):
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            _send_message(client, "account_info", _ACCOUNT_DATA)
            _send_message(client, "contract_spec", {
                "broker_symbol": "EURUSD_",
                "digits": 5,
                "point": "0.00001",
                "tick_size": "0.00001",
                "tick_value": "1.0",
                "contract_size": "100000",
                "volume_min": "0.01",
                "volume_max": "100.0",
                "volume_step": "0.01",
                "min_stop_distance": "0",
                "trade_allowed": True,
                "margin_initial": "1000",
                "commission_per_lot": "0",
                "swap_long": "0",
                "swap_short": "0",
            })
            time.sleep(0.1)
            spec = adapter.get_contract_spec("EURUSD_")
            assert spec is not None
            assert spec.digits == 5
            assert spec.point == Decimal("0.00001")
        finally:
            client.close()

    def test_unknown_symbol_reports_unavailable(self, adapter):
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            _send_message(client, "account_info", _ACCOUNT_DATA)
            time.sleep(0.1)
            with pytest.raises(SymbolUnavailableError, match="symbol unavailable"):
                adapter.get_contract_spec("UNKNOWN")
        finally:
            client.close()

    def test_malformed_contract_spec_no_heartbeat(self, adapter):
        """Malformed contract_spec must not refresh heartbeat health."""
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            _send_message(client, "contract_spec", {"bad": "data"})
            time.sleep(0.1)
            with pytest.raises(BrokerUnavailableError):
                adapter.get_contract_spec("anything")
            assert adapter.health_check() is ConnectionStatus.DISCONNECTED
        finally:
            client.close()


class TestMalformedRecognizedTypes:
    """Malformed payloads for recognized types must not refresh heartbeat."""

    def test_malformed_account_info_no_heartbeat(self):
        port = _find_free_port()
        a = TcpBrokerAdapter(port=port, heartbeat_timeout_s=0.2, data_staleness_s=10.0)
        try:
            a.connect()
            client = _connect_client(port)
            try:
                _send_message(client, "heartbeat", {})
                time.sleep(0.05)
                assert a.health_check() is ConnectionStatus.RECONNECTING
                time.sleep(0.3)
                _send_message(client, "account_info", {"bad": "fields"})
                time.sleep(0.1)
                assert a.health_check() is ConnectionStatus.DISCONNECTED
                with pytest.raises(BrokerUnavailableError):
                    a.get_account_info()
            finally:
                client.close()
        finally:
            a.disconnect()

    def test_malformed_symbol_list_no_heartbeat(self):
        port = _find_free_port()
        a = TcpBrokerAdapter(port=port, heartbeat_timeout_s=0.2, data_staleness_s=10.0)
        try:
            a.connect()
            client = _connect_client(port)
            try:
                _send_message(client, "heartbeat", {})
                time.sleep(0.05)
                assert a.health_check() is ConnectionStatus.RECONNECTING
                time.sleep(0.3)
                _send_message(client, "symbol_list", {"symbols": "not_a_list"})
                time.sleep(0.1)
                assert a.health_check() is ConnectionStatus.DISCONNECTED
            finally:
                client.close()
        finally:
            a.disconnect()

    def test_malformed_contract_spec_no_heartbeat(self):
        port = _find_free_port()
        a = TcpBrokerAdapter(port=port, heartbeat_timeout_s=0.2, data_staleness_s=10.0)
        try:
            a.connect()
            client = _connect_client(port)
            try:
                _send_message(client, "heartbeat", {})
                time.sleep(0.05)
                assert a.health_check() is ConnectionStatus.RECONNECTING
                time.sleep(0.3)
                _send_message(client, "contract_spec", {"broker_symbol": "X"})
                time.sleep(0.1)
                assert a.health_check() is ConnectionStatus.DISCONNECTED
            finally:
                client.close()
        finally:
            a.disconnect()

    def test_heartbeat_missing_data_no_heartbeat(self):
        """Heartbeat with missing data field must not refresh health."""
        port = _find_free_port()
        a = TcpBrokerAdapter(port=port, heartbeat_timeout_s=0.2, data_staleness_s=10.0)
        try:
            a.connect()
            client = _connect_client(port)
            try:
                _send_message(client, "heartbeat", {})
                time.sleep(0.05)
                assert a.health_check() is ConnectionStatus.RECONNECTING
                time.sleep(0.3)
                _send_raw_json(client, {"type": "heartbeat"})
                time.sleep(0.1)
                assert a.health_check() is ConnectionStatus.DISCONNECTED
            finally:
                client.close()
        finally:
            a.disconnect()

    def test_heartbeat_non_dict_data_no_heartbeat(self):
        """Heartbeat with non-object data must not refresh health."""
        port = _find_free_port()
        a = TcpBrokerAdapter(port=port, heartbeat_timeout_s=0.2, data_staleness_s=10.0)
        try:
            a.connect()
            client = _connect_client(port)
            try:
                _send_message(client, "heartbeat", {})
                time.sleep(0.05)
                assert a.health_check() is ConnectionStatus.RECONNECTING
                time.sleep(0.3)
                _send_raw_json(client, {"type": "heartbeat", "data": "not_a_dict"})
                time.sleep(0.1)
                assert a.health_check() is ConnectionStatus.DISCONNECTED
            finally:
                client.close()
        finally:
            a.disconnect()

    def test_valid_message_after_malformed_restores_health(self, adapter):
        """A valid message after malformed ones does refresh heartbeat."""
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            _send_message(client, "account_info", {"bad": True})
            _send_message(client, "heartbeat", {})
            time.sleep(0.15)
            assert adapter.health_check() is ConnectionStatus.RECONNECTING
        finally:
            client.close()


class TestTcpReconnect:
    def test_new_client_replaces_old(self, adapter):
        adapter.connect()
        client1 = _connect_client(adapter._port)
        try:
            _send_message(client1, "heartbeat", {})
            time.sleep(0.1)
            assert adapter.health_check() is ConnectionStatus.RECONNECTING
        finally:
            client1.close()

        time.sleep(0.2)
        client2 = _connect_client(adapter._port)
        try:
            _send_message(client2, "heartbeat", {})
            time.sleep(0.1)
            assert adapter.health_check() is ConnectionStatus.RECONNECTING
        finally:
            client2.close()

    def test_reconnect_blocks_operations_until_fresh_account_info(self, adapter):
        adapter.connect()
        first = _connect_client(adapter._port)
        _send_message(first, "account_info", _ACCOUNT_DATA)
        time.sleep(0.1)
        assert adapter.get_account_info() is not None
        first.close()
        time.sleep(0.1)

        second = _connect_client(adapter._port)
        try:
            _send_message(second, "heartbeat", {})
            time.sleep(0.1)
            assert adapter.health_check() is ConnectionStatus.RECONNECTING
            with pytest.raises(BrokerUnavailableError):
                adapter.get_account_info()

            _send_message(second, "account_info", _ACCOUNT_DATA)
            time.sleep(0.1)
            assert adapter.health_check() is ConnectionStatus.CONNECTED
            assert adapter.get_account_info() is not None
        finally:
            second.close()


class TestTcpHeartbeatTimeout:
    def test_stale_heartbeat_disconnects(self):
        port = _find_free_port()
        a = TcpBrokerAdapter(port=port, heartbeat_timeout_s=0.2, data_staleness_s=10.0)
        try:
            a.connect()
            client = _connect_client(port)
            try:
                _send_message(client, "heartbeat", {})
                time.sleep(0.05)
                assert a.health_check() is ConnectionStatus.RECONNECTING
                time.sleep(0.3)
                assert a.health_check() is ConnectionStatus.DISCONNECTED
            finally:
                client.close()
        finally:
            a.disconnect()


class TestTcpSendRequest:
    def test_send_request_to_client(self, adapter):
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            _send_message(client, "heartbeat", {})
            time.sleep(0.1)
            ok = adapter.send_request("get_symbols")
            assert ok is True
            client.settimeout(2.0)
            header = client.recv(4)
            msg_len = struct.unpack("!I", header)[0]
            payload = client.recv(msg_len)
            msg = json.loads(payload)
            assert msg["type"] == "request"
            assert msg["data"]["request"] == "get_symbols"
        finally:
            client.close()

    def test_send_request_no_client(self, adapter):
        adapter.connect()
        ok = adapter.send_request("get_symbols")
        assert ok is False

    def test_named_discovery_requests_match_ea_contract(self, adapter):
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            _send_message(client, "heartbeat", {})
            time.sleep(0.1)
            assert adapter.request_symbols()
            assert recv_message(client) == {
                "type": "request", "data": {"request": "get_symbols"},
            }
            assert adapter.request_contract_spec("EURUSD_")
            assert recv_message(client) == {
                "type": "request",
                "data": {"request": "get_contracts", "symbol": "EURUSD_"},
            }
        finally:
            client.close()


class TestTcpMessageHardening:
    """Reject non-object JSON and unrecognized types without crashing."""

    def test_json_array_ignored(self, adapter):
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            _send_raw_json(client, [1, 2, 3])
            time.sleep(0.1)
            assert adapter.health_check() is ConnectionStatus.DISCONNECTED

        finally:
            client.close()

    def test_json_string_ignored(self, adapter):
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            _send_raw_json(client, "hello")
            time.sleep(0.1)
            assert adapter.health_check() is ConnectionStatus.DISCONNECTED
        finally:
            client.close()

    def test_json_number_ignored(self, adapter):
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            _send_raw_json(client, 42)
            time.sleep(0.1)
            assert adapter.health_check() is ConnectionStatus.DISCONNECTED
        finally:
            client.close()

    def test_unrecognized_type_no_heartbeat_bump(self):
        port = _find_free_port()
        a = TcpBrokerAdapter(port=port, heartbeat_timeout_s=0.2, data_staleness_s=10.0)
        try:
            a.connect()
            client = _connect_client(port)
            try:
                _send_message(client, "heartbeat", {})
                time.sleep(0.05)
                assert a.health_check() is ConnectionStatus.RECONNECTING
                time.sleep(0.25)
                _send_raw_json(client, {"type": "unknown_type", "data": {}})
                time.sleep(0.1)
                assert a.health_check() is ConnectionStatus.DISCONNECTED
            finally:
                client.close()
        finally:
            a.disconnect()

    def test_missing_type_field_ignored(self, adapter):
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            _send_raw_json(client, {"data": {"foo": "bar"}})
            time.sleep(0.1)
            assert adapter.health_check() is ConnectionStatus.DISCONNECTED
        finally:
            client.close()

    def test_valid_after_invalid_sequence(self, adapter):
        """Invalid messages don't kill the receiver thread."""
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            _send_raw_json(client, [1, 2])
            _send_raw_json(client, "bad")
            _send_raw_json(client, {"type": "unknown"})
            _send_message(client, "heartbeat", {})
            time.sleep(0.15)
            assert adapter.health_check() is ConnectionStatus.RECONNECTING
        finally:
            client.close()


def _send_raw_bytes(sock: socket.socket, data: bytes) -> None:
    """Send a pre-built length-prefixed frame (simulates EA byte output)."""
    sock.sendall(struct.pack("!I", len(data)) + data)


class TestProtocolConformance:
    """Simulate exact EA output format and verify Python parses it.

    These tests use raw JSON strings matching MQL5 StringFormat output
    (%.10g numbers, null optionals, escaped strings). Labeled: simulated
    EA output, not verified against compiled MQL5.
    """

    def test_ea_account_info_format(self, adapter):
        """Simulated: MQL5 StringFormat account_info message."""
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            raw = (
                b'{"type":"account_info","data":'
                b'{"login":67890,"server":"ICMarkets-Demo02",'
                b'"currency":"USD","balance":"25000.00","equity":"25123.45",'
                b'"margin_free":"24500.00","account_type":"demo",'
                b'"leverage":500,"company":"IC Markets"}}'
            )
            _send_raw_bytes(client, raw)
            time.sleep(0.1)
            info = adapter.get_account_info()
            assert info is not None
            assert info.login == 67890
            assert info.server == "ICMarkets-Demo02"
            assert info.balance == Decimal("25000.00")
            assert info.equity == Decimal("25123.45")
            assert info.leverage == 500
        finally:
            client.close()

    def test_ea_contract_spec_with_scientific_notation(self, adapter):
        """Simulated: %.10g produces scientific notation for small values."""
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            raw = (
                b'{"type":"account_info","data":{"login":1,"server":"s",'
                b'"currency":"USD","balance":"100","equity":"100","margin_free":"0"}}'
            )
            _send_raw_bytes(client, raw)
            raw = (
                b'{"type":"contract_spec","data":'
                b'{"broker_symbol":"EURUSD","digits":5,'
                b'"point":"1e-05","tick_size":"1e-05","tick_value":"1",'
                b'"contract_size":"100000",'
                b'"volume_min":"0.01","volume_max":"500","volume_step":"0.01",'
                b'"min_stop_distance":"0","trade_allowed":true,'
                b'"margin_initial":"1000",'
                b'"commission_per_lot":"0","swap_long":"-7.2","swap_short":"3.1"}}'
            )
            _send_raw_bytes(client, raw)
            time.sleep(0.1)
            spec = adapter.get_contract_spec("EURUSD")
            assert spec is not None
            assert spec.point == Decimal("0.00001")
            assert spec.tick_size == Decimal("0.00001")
            assert spec.contract_size == Decimal("100000")
            assert spec.margin_initial == Decimal("1000")
            assert spec.commission_per_lot == Decimal("0")
            assert spec.swap_long == Decimal("-7.2")
            assert spec.swap_short == Decimal("3.1")
        finally:
            client.close()

    def test_ea_contract_spec_with_margin_initial(self, adapter):
        """Simulated: margin_initial sent as numeric string when non-zero."""
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            _send_message(client, "account_info", _ACCOUNT_DATA)
            raw = (
                b'{"type":"contract_spec","data":'
                b'{"broker_symbol":"USDJPY","digits":3,'
                b'"point":"0.001","tick_size":"0.001","tick_value":"0.67",'
                b'"contract_size":"100000",'
                b'"volume_min":"0.01","volume_max":"100","volume_step":"0.01",'
                b'"min_stop_distance":"0","trade_allowed":true,'
                b'"margin_initial":"1000",'
                b'"commission_per_lot":"0","swap_long":"5.3","swap_short":"-8.1"}}'
            )
            _send_raw_bytes(client, raw)
            time.sleep(0.1)
            spec = adapter.get_contract_spec("USDJPY")
            assert spec is not None
            assert spec.margin_initial == Decimal("1000")
        finally:
            client.close()

    def test_ea_symbol_list_format(self, adapter):
        """Simulated: MQL5 StringFormat symbol_list message."""
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            _send_message(client, "account_info", _ACCOUNT_DATA)
            raw = (
                b'{"type":"symbol_list","data":'
                b'{"symbols":[{"name":"EURUSD","trading_permitted":true},'
                b'{"name":"GBPJPY","trading_permitted":true},'
                b'{"name":"USDJPY","trading_permitted":true},'
                b'{"name":"XAUUSD","trading_permitted":false}]}}'
            )
            _send_raw_bytes(client, raw)
            time.sleep(0.1)
            syms = adapter.discover_symbols()
            assert len(syms) == 4
            assert "EURUSD" in {symbol.broker_name for symbol in syms}
            assert "XAUUSD" in {symbol.broker_name for symbol in syms}
            assert next(s for s in syms if s.broker_name == "XAUUSD").trading_permitted is False
        finally:
            client.close()

    def test_ea_heartbeat_format(self, adapter):
        """Simulated: heartbeat with empty data object."""
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            raw = b'{"type":"heartbeat","data":{}}'
            _send_raw_bytes(client, raw)
            time.sleep(0.1)
            assert adapter.health_check() is ConnectionStatus.RECONNECTING
        finally:
            client.close()

    def test_ea_json_escaped_strings(self, adapter):
        """Simulated: server/company with special characters."""
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            raw = (
                b'{"type":"account_info","data":'
                b'{"login":1,"server":"Broker\\"Demo\\"","currency":"USD",'
                b'"balance":"100","equity":"100","margin_free":"100",'
                b'"account_type":"demo","leverage":100,'
                b'"company":"Test\\\\Corp"}}'
            )
            _send_raw_bytes(client, raw)
            time.sleep(0.1)
            info = adapter.get_account_info()
            assert info is not None
            assert info.server == 'Broker"Demo"'
            assert info.company == "Test\\Corp"
        finally:
            client.close()

    def test_backend_request_framing(self, adapter):
        """Verify backend→EA request matches the wire protocol the EA reads."""
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            _send_raw_bytes(client, b'{"type":"heartbeat","data":{}}')
            time.sleep(0.1)
            adapter.send_request("get_symbols")
            client.settimeout(2.0)
            header = client.recv(4)
            msg_len = struct.unpack("!I", header)[0]
            payload = client.recv(msg_len)
            msg = json.loads(payload)
            assert msg["type"] == "request"
            assert msg["data"]["request"] == "get_symbols"
            assert isinstance(msg["data"], dict)
        finally:
            client.close()

    def test_64bit_login(self, adapter):
        """Simulated: login exceeding 32-bit int range (MQL5 long → %I64d)."""
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            raw = (
                b'{"type":"account_info","data":'
                b'{"login":5000000000,"server":"s","currency":"USD",'
                b'"balance":"1","equity":"1","margin_free":"0",'
                b'"account_type":"demo","leverage":100,"company":"c"}}'
            )
            _send_raw_bytes(client, raw)
            time.sleep(0.1)
            info = adapter.get_account_info()
            assert info is not None
            assert info.login == 5_000_000_000
        finally:
            client.close()

    def test_json_control_characters(self, adapter):
        """Simulated: EA JsonEscape encodes control chars as \\uXXXX."""
        adapter.connect()
        client = _connect_client(adapter._port)
        try:
            raw = (
                b'{"type":"account_info","data":'
                b'{"login":1,"server":"test\\u0001srv","currency":"USD",'
                b'"balance":"1","equity":"1","margin_free":"0",'
                b'"account_type":"demo","leverage":1,"company":"co\\u001f"}}'
            )
            _send_raw_bytes(client, raw)
            time.sleep(0.1)
            info = adapter.get_account_info()
            assert info is not None
            assert info.server == "test\x01srv"
            assert info.company == "co\x1f"
        finally:
            client.close()


def _make_tick_batch(symbol, terminal_id, instance_id, run_id, seq,
                     bid="1.10000", ask="1.10010"):
    return {
        "broker_symbol": symbol,
        "ticks": [{"bid": bid, "ask": ask, "server_time_ms": 1000000 + seq}],
        "newest_index": 0,
        "dropped": 0,
        "batch_size": 1,
        "terminal_instance_id": terminal_id,
        "ea_instance_id": instance_id,
        "ea_run_id": run_id,
        "batch_seq": seq,
    }


_T = "C:\\Users\\test\\AppData\\Roaming\\MetaQuotes\\Terminal\\ABC123"


class TestTickBatchDedup:
    def test_accepts_first_batch(self, adapter):
        adapter.connect()
        client = _connect_client(adapter._port)
        ticks = []
        adapter._on_tick = ticks.append
        try:
            _send_message(client, "tick_batch", _make_tick_batch("EURUSD", _T, "EURUSD_1", 100, 0))
            time.sleep(0.1)
            assert len(ticks) == 1
            stats = adapter.get_batch_stats()
            assert stats[(_T, "EURUSD_1")]["accepted"] == 1
        finally:
            client.close()

    def test_rejects_duplicate_seq(self, adapter):
        adapter.connect()
        client = _connect_client(adapter._port)
        ticks = []
        adapter._on_tick = ticks.append
        try:
            _send_message(client, "tick_batch", _make_tick_batch("EURUSD", _T, "EURUSD_1", 100, 0))
            _send_message(client, "tick_batch", _make_tick_batch("EURUSD", _T, "EURUSD_1", 100, 0))
            time.sleep(0.1)
            assert len(ticks) == 1
            stats = adapter.get_batch_stats()
            assert stats[(_T, "EURUSD_1")]["rejected"] == 1
        finally:
            client.close()

    def test_rejects_older_seq(self, adapter):
        adapter.connect()
        client = _connect_client(adapter._port)
        ticks = []
        adapter._on_tick = ticks.append
        try:
            _send_message(client, "tick_batch", _make_tick_batch("EURUSD", _T, "EURUSD_1", 100, 5))
            _send_message(client, "tick_batch", _make_tick_batch("EURUSD", _T, "EURUSD_1", 100, 3))
            time.sleep(0.1)
            assert len(ticks) == 1
        finally:
            client.close()

    def test_tracks_gaps(self, adapter):
        adapter.connect()
        client = _connect_client(adapter._port)
        ticks = []
        adapter._on_tick = ticks.append
        try:
            _send_message(client, "tick_batch", _make_tick_batch("EURUSD", _T, "EURUSD_1", 100, 0))
            _send_message(client, "tick_batch", _make_tick_batch("EURUSD", _T, "EURUSD_1", 100, 3))
            time.sleep(0.1)
            assert len(ticks) == 2
            stats = adapter.get_batch_stats()
            assert stats[(_T, "EURUSD_1")]["gaps"] == 2
        finally:
            client.close()

    def test_new_run_resets_gaps(self, adapter):
        adapter.connect()
        client = _connect_client(adapter._port)
        ticks = []
        adapter._on_tick = ticks.append
        try:
            _send_message(client, "tick_batch", _make_tick_batch("EURUSD", _T, "EURUSD_1", 100, 0))
            _send_message(client, "tick_batch", _make_tick_batch("EURUSD", _T, "EURUSD_1", 100, 5))
            time.sleep(0.1)
            assert adapter.get_batch_stats()[(_T, "EURUSD_1")]["gaps"] == 4
            # New run_id resets gaps
            _send_message(client, "tick_batch", _make_tick_batch("EURUSD", _T, "EURUSD_1", 200, 0))
            time.sleep(0.1)
            stats = adapter.get_batch_stats()
            assert stats[(_T, "EURUSD_1")]["gaps"] == 0
            assert stats[(_T, "EURUSD_1")]["run_transitions"] == 1
        finally:
            client.close()

    def test_two_instances_independent(self, adapter):
        """Two different ea_instance_ids on the same terminal don't interfere."""
        adapter.connect()
        client = _connect_client(adapter._port)
        ticks = []
        adapter._on_tick = ticks.append
        try:
            _send_message(client, "tick_batch", _make_tick_batch("EURUSD", _T, "EURUSD_1", 100, 0))
            _send_message(client, "tick_batch", _make_tick_batch("GBPJPY", _T, "GBPJPY_2", 100, 0))
            time.sleep(0.1)
            assert len(ticks) == 2
            stats = adapter.get_batch_stats()
            assert (_T, "EURUSD_1") in stats
            assert (_T, "GBPJPY_2") in stats
            assert stats[(_T, "EURUSD_1")]["accepted"] == 1
            assert stats[(_T, "GBPJPY_2")]["accepted"] == 1
        finally:
            client.close()

    def test_same_run_id_different_instances_no_collision(self, adapter):
        """Same run_id on different streams is fine — keyed by (terminal, instance)."""
        adapter.connect()
        client = _connect_client(adapter._port)
        ticks = []
        adapter._on_tick = ticks.append
        try:
            _send_message(client, "tick_batch", _make_tick_batch("EURUSD", _T, "EURUSD_1", 999, 0))
            _send_message(client, "tick_batch", _make_tick_batch("GBPJPY", _T, "GBPJPY_2", 999, 0))
            time.sleep(0.1)
            assert len(ticks) == 2
        finally:
            client.close()


_ACCOUNT_DATA = {
    "login": 1, "server": "s", "currency": "USD",
    "balance": "100", "equity": "100", "margin_free": "0",
    "account_type": "demo", "leverage": 1, "company": "c",
}

_CONTRACT_DATA = {
    "broker_symbol": "EURUSD", "digits": 5,
    "point": "0.00001", "tick_size": "0.00001", "tick_value": "1",
    "contract_size": "100000",
    "volume_min": "0.01", "volume_max": "100", "volume_step": "0.01",
    "min_stop_distance": "0", "trade_allowed": True,
    "margin_initial": "1000", "commission_per_lot": "0",
    "swap_long": "0", "swap_short": "0",
}

_SYMBOLS = [{"name": "EURUSD", "trading_permitted": True}]


class TestTimingPolicy:
    """Prove the EA push interval / data_staleness_s alignment.

    Uses short timeouts to keep tests fast. The invariant under test:
    data pushed within data_staleness_s stays available; data older than
    data_staleness_s becomes unavailable (fail-closed).
    """

    def test_pushes_within_staleness_keep_data_fresh(self):
        """Simulates EA pushing faster than data_staleness_s."""
        port = _find_free_port()
        a = TcpBrokerAdapter(port=port, heartbeat_timeout_s=5.0, data_staleness_s=0.5)
        try:
            a.connect()
            client = _connect_client(port)
            try:
                _send_message(client, "account_info", _ACCOUNT_DATA)
                _send_message(client, "symbol_list", {"symbols": _SYMBOLS})
                _send_message(client, "contract_spec", _CONTRACT_DATA)
                _send_message(client, "heartbeat", {})
                time.sleep(0.1)
                assert a.get_account_info() is not None
                assert a.discover_symbols()[0].broker_name == "EURUSD"
                assert a.get_contract_spec("EURUSD") is not None

                time.sleep(0.25)
                _send_message(client, "account_info", _ACCOUNT_DATA)
                _send_message(client, "symbol_list", {"symbols": _SYMBOLS})
                _send_message(client, "contract_spec", _CONTRACT_DATA)
                _send_message(client, "heartbeat", {})
                time.sleep(0.1)
                assert a.get_account_info() is not None
                assert a.discover_symbols()[0].broker_name == "EURUSD"
                assert a.get_contract_spec("EURUSD") is not None
            finally:
                client.close()
        finally:
            a.disconnect()

    def test_data_becomes_stale_after_limit(self):
        """Data expires when not refreshed within data_staleness_s."""
        port = _find_free_port()
        a = TcpBrokerAdapter(port=port, heartbeat_timeout_s=5.0, data_staleness_s=0.2)
        try:
            a.connect()
            client = _connect_client(port)
            try:
                _send_message(client, "account_info", _ACCOUNT_DATA)
                _send_message(client, "symbol_list", {"symbols": _SYMBOLS})
                _send_message(client, "contract_spec", _CONTRACT_DATA)
                _send_message(client, "heartbeat", {})
                time.sleep(0.1)
                assert a.get_account_info() is not None
                assert a.discover_symbols()[0].broker_name == "EURUSD"
                assert a.get_contract_spec("EURUSD") is not None

                # Keep heartbeat alive but let data go stale
                time.sleep(0.25)
                _send_message(client, "heartbeat", {})
                time.sleep(0.1)
                assert a.health_check() is ConnectionStatus.CONNECTED
                with pytest.raises(BrokerUnavailableError):
                    a.get_account_info()
                with pytest.raises(BrokerUnavailableError):
                    a.discover_symbols()
                with pytest.raises(BrokerUnavailableError):
                    a.get_contract_spec("EURUSD")
            finally:
                client.close()
        finally:
            a.disconnect()

    def test_reconnect_repopulates_all_data(self):
        """After disconnect and reconnect, fresh pushes restore data."""
        port = _find_free_port()
        a = TcpBrokerAdapter(port=port, heartbeat_timeout_s=0.2, data_staleness_s=5.0)
        try:
            a.connect()
            client1 = _connect_client(port)
            try:
                _send_message(client1, "account_info", _ACCOUNT_DATA)
                _send_message(client1, "symbol_list", {"symbols": _SYMBOLS})
                _send_message(client1, "contract_spec", _CONTRACT_DATA)
                _send_message(client1, "heartbeat", {})
                time.sleep(0.1)
                assert a.get_account_info() is not None
            finally:
                client1.close()

            time.sleep(0.4)
            assert a.health_check() is ConnectionStatus.DISCONNECTED

            client2 = _connect_client(port)
            try:
                _send_message(client2, "account_info", _ACCOUNT_DATA)
                _send_message(client2, "symbol_list", {"symbols": [{"name": "GBPJPY", "trading_permitted": True}]})
                _send_message(client2, "contract_spec", {
                    **_CONTRACT_DATA, "broker_symbol": "GBPJPY",
                })
                _send_message(client2, "heartbeat", {})
                time.sleep(0.1)
                assert a.health_check() is ConnectionStatus.CONNECTED
                assert a.get_account_info() is not None
                assert "GBPJPY" in {symbol.broker_name for symbol in a.discover_symbols()}
                assert a.get_contract_spec("GBPJPY") is not None
            finally:
                client2.close()
        finally:
            a.disconnect()
