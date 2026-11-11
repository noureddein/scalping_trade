"""Architecture C TCP broker adapter — read-only.

In Architecture C the MQL5 EA is the TCP client and the Python backend
is the TCP server. The EA pushes market data, account info, and symbol
data to the backend over 127.0.0.1 using a length-prefixed JSON
protocol. This module implements the server (listening) side.

Phase 2 scope: health check, account discovery, symbol discovery,
contract specs. No order submission or position management.

This is implementation scaffolding. End-to-end MT5/Wine validation has
NOT been performed. The MQL5 EA client (ReadOnlyConnector.mq5) has been
written but not compiled or tested — MT5 under Wine is not available in
the current environment. All tests use a local fake socket harness.

## Wire protocol

Each message is framed as:
    [4 bytes big-endian uint32 length][UTF-8 JSON payload]

JSON payload structure:
    {
        "type": "<message_type>",
        "data": { ... }
    }

Message types (EA → backend, read-only phase):
    "heartbeat"       — periodic liveness signal
    "account_info"    — account details snapshot
    "symbol_list"     — list of available broker symbols
    "contract_spec"   — contract specification for one symbol
    "tick"            — single tick (Phase 2 legacy, still accepted)
    "tick_batch"      — batch of ticks from the ring buffer (Phase 3)
        data fields: broker_symbol, ticks (array oldest-to-newest),
        newest_index, dropped, batch_size, terminal_instance_id,
        ea_instance_id, ea_run_id, batch_seq.

        Identity model (each dimension is a separate wire field):
          terminal_instance_id: TerminalInfoString(TERMINAL_DATA_PATH).
            Unique per MT5 installation. Distinguishes two terminals
            on the same machine.
          ea_instance_id: Symbol + "_" + ChartID(). Stable per chart
            within a terminal. Survives restarts, recompilation.
          ea_run_id: persistent per-instance counter incremented on
            every OnInit (file: MQL5/Files/ReadOnlyConnector/<id>.run_counter).
            Unique even for sub-ms restarts. Falls back to GetTickCount64()
            only if file I/O fails. Set once per EA lifetime; unchanged
            across reconnects so retried batches keep the same identity.
          batch_seq: monotonic within a run, starts at 0, incremented
            only on successful send. On send failure the EA resends
            the same (terminal, instance, run, seq) tuple.

        Dedup rules (Python side):
          Stream key: (terminal_instance_id, ea_instance_id).
          - Same run_id, seq <= last accepted: rejected (duplicate/stale).
          - Same run_id, seq > last + 1: accepted, gap counted (not proof
            of loss — EA ring overflow and network drops are independent).
          - Different run_id: accepted, gap counter for that stream
            reset (new EA lifetime). Run transition counted.
          - Gaps are tracked for observability, never treated as proof of
            lossless or lossy capture.
    "TICK_DATA"       — Phase 3 canonical tick batches (ISO timestamps,
                        run_counter and batch_sequence fields)
    "MARKET_STATUS"   — optional market-open observation from the EA

Response types (backend → EA, read-only phase):
    "request"         — request data from EA (e.g. get_symbols, get_account, get_contracts)

## Timeouts and reconnection

- The adapter listens on 127.0.0.1 only (loopback, per decision #6).
- ``heartbeat_timeout_s``: if no message arrives within this window the
  connection is considered stale and health_check returns DISCONNECTED.
- The EA is responsible for reconnecting on disconnect. The server
  accepts one client connection at a time per adapter instance (one EA
  per pair, decision #7).
- Stale data: ``get_account_info`` and ``get_contract_spec`` return the
  most recent snapshot pushed by the EA. If the snapshot is older than
  ``data_staleness_s``, these methods return None (fail-closed).
- Timing constraint: the EA's discovery push interval (InpDiscoverySec)
  must be shorter than ``data_staleness_s``, or data will intermittently
  appear stale while the connection is healthy. Default: EA pushes every
  15 s, backend marks stale after 30 s.
"""
from __future__ import annotations

import json
import logging
import socket
import struct
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .broker_adapter import BrokerAdapter, BrokerUnavailableError, SymbolUnavailableError, _is_forex_canonical
from .broker_types import AccountInfo, BrokerSymbol, ConnectionStatus, ContractSpec, SymbolMapping, Tick

_HEADER_SIZE = 4
_MAX_MESSAGE_SIZE = 1024 * 1024  # 1 MiB
_LOGGER = logging.getLogger(__name__)


def send_message(sock: socket.socket, payload: dict) -> None:
    """Send one bounded, length-prefixed UTF-8 JSON object."""
    encoded = json.dumps(payload, allow_nan=False).encode("utf-8")
    if not encoded or len(encoded) > _MAX_MESSAGE_SIZE:
        raise ValueError("broker message size is outside the allowed range")
    sock.sendall(struct.pack("!I", len(encoded)) + encoded)


def recv_message(sock: socket.socket) -> dict:
    """Read one complete framed JSON object, including across partial reads."""
    header = _recv_exact(sock, _HEADER_SIZE)
    size = struct.unpack("!I", header)[0]
    if size == 0 or size > _MAX_MESSAGE_SIZE:
        raise ValueError("broker message size is outside the allowed range")
    payload = _recv_exact(sock, size)
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("broker message payload must be a JSON object")
    return decoded


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise ConnectionError("broker socket closed during a framed message")
        chunks.extend(chunk)
    return bytes(chunks)


class TcpBrokerAdapter(BrokerAdapter):
    """TCP server adapter for Architecture C.

    Listens on 127.0.0.1 for a single EA client connection. Receives
    read-only data pushes (account info, symbols, contract specs).
    No order methods exist.
    """

    def __init__(
        self,
        port: int,
        heartbeat_timeout_s: float = 10.0,
        data_staleness_s: float = 30.0,
        on_tick: "Callable[[Tick], None] | None" = None,
        on_tick_batch: "Callable[[str, int, int, list[Tick], int], None] | None" = None,
        on_market_status: "Callable[[str, bool, datetime], None] | None" = None,
    ) -> None:
        self._port = port
        self._heartbeat_timeout_s = heartbeat_timeout_s
        self._data_staleness_s = data_staleness_s
        self._on_tick = on_tick
        self._on_tick_batch = on_tick_batch
        self._on_market_status = on_market_status

        self._server_sock: socket.socket | None = None
        self._client_sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._receiver_thread: threading.Thread | None = None
        self._running = False

        self._last_message_time: float = 0.0
        self._connection_state = ConnectionStatus.DISCONNECTED
        self._account_info: AccountInfo | None = None
        self._account_info_time: float = 0.0
        self._symbols: list[tuple[str, bool]] = []
        self._symbols_time: float = 0.0
        self._contracts: dict[str, ContractSpec] = {}
        self._contracts_time: dict[str, float] = {}
        self._owner_mappings: dict[str, SymbolMapping] = {}
        # Keyed by (terminal_instance_id, ea_instance_id) stream tuple
        self._batch_dedup: dict[tuple[str, str], tuple[int, int]] = {}
        self._batch_gaps: dict[tuple[str, str], int] = {}
        self._batch_run_transitions: dict[tuple[str, str], int] = {}
        self._batch_accepted: dict[tuple[str, str], int] = {}
        self._batch_rejected: dict[tuple[str, str], int] = {}

    def connect(self) -> ConnectionStatus:
        with self._lock:
            if self._server_sock is not None:
                return ConnectionStatus.CONNECTED
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", self._port))
                sock.listen(1)
                sock.settimeout(1.0)
                self._server_sock = sock
                self._running = True
                self._connection_state = ConnectionStatus.DISCONNECTED
                self._receiver_thread = threading.Thread(
                    target=self._accept_loop, daemon=True,
                )
                self._receiver_thread.start()
                return ConnectionStatus.CONNECTED
            except OSError:
                return ConnectionStatus.ERROR

    def disconnect(self) -> None:
        with self._lock:
            self._running = False
            self._connection_state = ConnectionStatus.DISCONNECTED
            self._clear_session_data_locked()
            if self._client_sock is not None:
                try:
                    self._client_sock.close()
                except OSError:
                    pass
                self._client_sock = None
            if self._server_sock is not None:
                try:
                    self._server_sock.close()
                except OSError:
                    pass
                self._server_sock = None
        if self._receiver_thread is not None:
            self._receiver_thread.join(timeout=5.0)
            self._receiver_thread = None

    def health_check(self) -> ConnectionStatus:
        with self._lock:
            if self._server_sock is None:
                self._connection_state = ConnectionStatus.DISCONNECTED
                return ConnectionStatus.DISCONNECTED
            if self._client_sock is None:
                self._connection_state = ConnectionStatus.DISCONNECTED
                return ConnectionStatus.DISCONNECTED
            elapsed = time.monotonic() - self._last_message_time
            if elapsed > self._heartbeat_timeout_s:
                self._connection_state = ConnectionStatus.DISCONNECTED
                return ConnectionStatus.DISCONNECTED
            if self._account_info is None or self._account_info_time == 0:
                self._connection_state = ConnectionStatus.RECONNECTING
                return ConnectionStatus.RECONNECTING
            self._connection_state = ConnectionStatus.CONNECTED
            return self._connection_state

    def get_account_info(self) -> AccountInfo | None:
        with self._lock:
            self._require_ready_locked()
            if self._account_info is None:
                raise BrokerUnavailableError("fresh account information is unavailable")
            if time.monotonic() - self._account_info_time > self._data_staleness_s:
                raise BrokerUnavailableError("account information is stale")
            return self._account_info

    def discover_symbols(self) -> list[BrokerSymbol]:
        with self._lock:
            self._require_ready_locked()
            if time.monotonic() - self._symbols_time > self._data_staleness_s:
                raise BrokerUnavailableError("symbol list is stale or unavailable")
            account_number = self._account_info.login if self._account_info else None
            return [BrokerSymbol(name, permitted, account_number) for name, permitted in self._symbols]

    def get_contract_spec(self, broker_symbol: str) -> ContractSpec | None:
        with self._lock:
            self._require_ready_locked()
            spec = self._contracts.get(broker_symbol)
            if spec is None:
                raise SymbolUnavailableError(f"symbol unavailable: {broker_symbol}")
            ts = self._contracts_time.get(broker_symbol, 0.0)
            if time.monotonic() - ts > self._data_staleness_s:
                raise BrokerUnavailableError(f"contract specification is stale: {broker_symbol}")
            return spec

    def get_contract_spec_updated_at(self, broker_symbol: str) -> float | None:
        with self._lock:
            self._require_ready_locked()
            if broker_symbol not in self._contracts:
                return None
            updated_at = self._contracts_time.get(broker_symbol)
            if updated_at is None or time.monotonic() - updated_at > self._data_staleness_s:
                return None
            return updated_at

    def update_mapping(self, canonical_name: str, broker_name: str) -> SymbolMapping:
        if not _is_forex_canonical(canonical_name):
            raise ValueError(f"invalid canonical Forex symbol: {canonical_name}")
        symbol = next(
            (item for item in self.discover_symbols() if item.broker_name == broker_name),
            None,
        )
        contract = self.get_contract_spec(broker_name)
        if symbol is None or contract is None:
            raise ValueError(f"broker symbol unavailable: {broker_name}")
        with self._lock:
            if any(
                item.broker_symbol == broker_name and key != canonical_name
                for key, item in self._owner_mappings.items()
            ):
                raise ValueError(f"broker symbol already mapped: {broker_name}")
            mapping = SymbolMapping(canonical_name, broker_name, contract, True)
            self._owner_mappings[canonical_name] = mapping
            return mapping

    def get_mapping(self, canonical_name: str) -> SymbolMapping | None:
        with self._lock:
            return self._owner_mappings.get(canonical_name)

    def _require_ready_locked(self) -> None:
        if self._server_sock is None or self._client_sock is None:
            self._connection_state = ConnectionStatus.DISCONNECTED
            raise BrokerUnavailableError("broker unavailable until fresh account data is received")
        if time.monotonic() - self._last_message_time > self._heartbeat_timeout_s:
            self._connection_state = ConnectionStatus.DISCONNECTED
            raise BrokerUnavailableError("broker heartbeat is stale")
        if self._account_info is None or self._account_info_time == 0:
            self._connection_state = ConnectionStatus.RECONNECTING
            raise BrokerUnavailableError("broker unavailable until fresh account data is received")
        if time.monotonic() - self._account_info_time > self._data_staleness_s:
            self._connection_state = ConnectionStatus.DISCONNECTED
            raise BrokerUnavailableError("account information is stale")

    def _clear_session_data_locked(self) -> None:
        self._account_info = None
        self._account_info_time = 0.0
        self._symbols = []
        self._symbols_time = 0.0
        self._contracts.clear()
        self._contracts_time.clear()
        self._last_message_time = 0.0

    def get_batch_stats(self) -> dict[tuple[str, str], dict[str, int]]:
        """Per-stream batch dedup stats keyed by (terminal_instance_id, ea_instance_id)."""
        with self._lock:
            streams = set(self._batch_dedup) | set(self._batch_accepted)
            result = {}
            for stream in streams:
                dedup = self._batch_dedup.get(stream)
                result[stream] = {
                    "run_id": dedup[0] if dedup else 0,
                    "last_seq": dedup[1] if dedup else -1,
                    "accepted": self._batch_accepted.get(stream, 0),
                    "rejected": self._batch_rejected.get(stream, 0),
                    "gaps": self._batch_gaps.get(stream, 0),
                    "run_transitions": self._batch_run_transitions.get(stream, 0),
                }
            return result

    # -- internal --

    def _accept_loop(self) -> None:
        while self._running:
            srv = self._server_sock
            if srv is None:
                break
            try:
                client, _ = srv.accept()
            except (OSError, socket.timeout):
                continue
            with self._lock:
                if self._client_sock is not None:
                    _LOGGER.warning("replacing existing EA connection with a new loopback client")
                    try:
                        self._client_sock.close()
                    except OSError:
                        pass
                self._clear_session_data_locked()
                self._client_sock = client
                self._connection_state = ConnectionStatus.RECONNECTING
                client.settimeout(1.0)
            self._read_loop(client)

    def _read_loop(self, client: socket.socket) -> None:
        buf = b""
        while self._running:
            try:
                chunk = client.recv(4096)
            except socket.timeout:
                with self._lock:
                    timed_out = time.monotonic() - self._last_message_time > self._heartbeat_timeout_s
                if timed_out:
                    break
                continue
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while len(buf) >= _HEADER_SIZE:
                msg_len = struct.unpack("!I", buf[:_HEADER_SIZE])[0]
                if msg_len > _MAX_MESSAGE_SIZE:
                    _LOGGER.warning("closing broker connection with oversized frame: %d bytes", msg_len)
                    buf = b""
                    try:
                        client.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    try:
                        client.close()
                    except OSError:
                        pass
                    break
                if len(buf) < _HEADER_SIZE + msg_len:
                    break
                payload = buf[_HEADER_SIZE:_HEADER_SIZE + msg_len]
                buf = buf[_HEADER_SIZE + msg_len:]
                self._handle_message(payload)
        with self._lock:
            if self._client_sock is client:
                self._client_sock = None
                self._connection_state = ConnectionStatus.DISCONNECTED
                self._clear_session_data_locked()
        try:
            client.close()
        except OSError:
            pass

    _KNOWN_TYPES = frozenset({
        "heartbeat", "account_info", "symbol_list", "contract_spec",
        "tick", "tick_batch", "tick_data", "market_status",
    })

    def _handle_message(self, payload: bytes) -> None:
        try:
            msg = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            _LOGGER.warning("discarding malformed broker message: invalid JSON or UTF-8")
            return
        if not isinstance(msg, dict):
            _LOGGER.warning("discarding malformed broker message: expected a JSON object")
            return
        raw_type = msg.get("type")
        msg_type = raw_type.lower() if isinstance(raw_type, str) else raw_type
        if msg_type not in self._KNOWN_TYPES:
            _LOGGER.warning("discarding broker message with unknown type: %r", msg_type)
            return
        data = msg.get("data")
        if not isinstance(data, dict):
            _LOGGER.warning("discarding malformed %s message: expected object data", msg_type)
            return
        now = time.monotonic()
        accepted = False
        tick: Tick | None = None
        batch_ticks: list[Tick] | None = None
        tick_metadata: tuple[str, int, int, int] | None = None
        market_status: tuple[str, bool, datetime] | None = None

        with self._lock:
            if msg_type == "heartbeat":
                accepted = True

            elif msg_type == "account_info":
                parsed = _parse_account_info(data)
                if parsed is not None:
                    self._account_info = parsed
                    self._account_info_time = now
                    accepted = True

            elif msg_type == "symbol_list":
                syms = _parse_symbols(data, self._account_info.login if self._account_info else None)
                if syms is not None:
                    self._symbols = [(item.broker_name, item.trading_permitted) for item in syms]
                    self._symbols_time = now
                    accepted = True

            elif msg_type == "contract_spec":
                spec = _parse_contract_spec(data)
                if spec is not None:
                    self._contracts[spec.broker_symbol] = spec
                    self._contracts_time[spec.broker_symbol] = now
                    accepted = True

            elif msg_type == "tick":
                tick = _parse_tick(data, now)
                if tick is not None:
                    accepted = True

            elif msg_type == "tick_batch":
                batch_ticks = _parse_tick_batch(data, now)
                if batch_ticks is not None:
                    term = str(data["terminal_instance_id"])
                    ea = str(data["ea_instance_id"])
                    stream = (term, ea)
                    run_id = int(data["ea_run_id"])
                    seq = int(data["batch_seq"])
                    prev = self._batch_dedup.get(stream)
                    if prev is not None:
                        prev_run, prev_seq = prev
                        if run_id != prev_run:
                            self._batch_run_transitions[stream] = (
                                self._batch_run_transitions.get(stream, 0) + 1
                            )
                            self._batch_gaps.pop(stream, None)
                        elif seq <= prev_seq:
                            batch_ticks = None
                            self._batch_rejected[stream] = (
                                self._batch_rejected.get(stream, 0) + 1
                            )
                        elif seq > prev_seq + 1:
                            gap = seq - prev_seq - 1
                            self._batch_gaps[stream] = (
                                self._batch_gaps.get(stream, 0) + gap
                            )
                    if batch_ticks is not None:
                        self._batch_dedup[stream] = (run_id, seq)
                        self._batch_accepted[stream] = (
                            self._batch_accepted.get(stream, 0) + 1
                        )
                        accepted = True

            elif msg_type == "tick_data":
                parsed = _parse_tick_data(data, now)
                if parsed is not None:
                    broker_pair, run_counter, sequence_number, dropped_count, batch_ticks = parsed
                    mapping = next((m for m in self._owner_mappings.values()
                                    if m.broker_symbol == broker_pair and m.confirmed_by_owner), None)
                    if mapping is not None:
                        batch_ticks = [Tick(
                            broker_symbol=t.broker_symbol, bid=t.bid, ask=t.ask,
                            server_time_ms=t.server_time_ms, recv_time_mono=t.recv_time_mono,
                            is_newest=t.is_newest, pair=mapping.canonical_pair,
                            broker_timestamp=t.broker_timestamp,
                            local_receipt_time=t.local_receipt_time,
                            batch_sequence=sequence_number, run_counter=run_counter,
                        ) for t in batch_ticks]
                        accepted = True
                        tick_metadata = (mapping.canonical_pair, run_counter,
                                         sequence_number, dropped_count)

            elif msg_type == "market_status":
                parsed_status = _parse_market_status(data)
                if parsed_status is not None:
                    broker_pair, is_open, server_time = parsed_status
                    mapping = next((m for m in self._owner_mappings.values()
                                    if m.broker_symbol == broker_pair and m.confirmed_by_owner), None)
                    if mapping is not None:
                        market_status = (mapping.canonical_pair, is_open, server_time)
                        accepted = True

            if accepted:
                self._last_message_time = now
                if msg_type == "account_info":
                    self._connection_state = ConnectionStatus.CONNECTED

        if msg_type == "tick" and tick is not None and self._on_tick is not None:
            self._on_tick(tick)
        if msg_type == "tick_batch" and batch_ticks and self._on_tick is not None:
            for t in batch_ticks:
                self._on_tick(t)
        if msg_type == "tick_data" and tick_metadata is not None:
            pair, run_counter, sequence_number, dropped_count = tick_metadata
            if self._on_tick_batch is not None:
                self._on_tick_batch(pair, sequence_number, run_counter, batch_ticks or [], dropped_count)
        if msg_type == "market_status" and market_status is not None and self._on_market_status is not None:
            self._on_market_status(*market_status)

    def send_request(self, request_type: str, params: dict | None = None) -> bool:
        """Send a request message to the EA. Returns False if no client."""
        msg = {"type": "request", "data": {"request": request_type, **(params or {})}}
        with self._lock:
            client = self._client_sock
        if client is None:
            return False
        try:
            send_message(client, msg)
            return True
        except OSError:
            return False

    def request_symbols(self) -> bool:
        return self.send_request("get_symbols")

    def request_contract_specs(self) -> bool:
        """Request the EA's current contract snapshot for Market Watch symbols."""
        return self.send_request("get_contracts")

    def request_contract_spec(self, broker_symbol: str) -> bool:
        if not broker_symbol or not isinstance(broker_symbol, str):
            raise ValueError("broker_symbol must be a non-empty string")
        return self.send_request("get_contracts", {"symbol": broker_symbol})


def _parse_account_info(data: dict) -> AccountInfo | None:
    try:
        login = data.get("account_number", data.get("login"))
        server = data.get("broker_name", data.get("server"))
        margin = data.get("margin", data.get("margin_free"))
        balance = Decimal(str(data["balance"]))
        equity = Decimal(str(data["equity"]))
        margin_value = Decimal(str(margin))
        currency = data["currency"]
        if isinstance(login, bool) or not isinstance(login, int) or login <= 0:
            return None
        if not isinstance(server, str) or not server.strip():
            return None
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isascii() or not currency.isalpha() or not currency.isupper():
            return None
        if not all(value.is_finite() for value in (balance, equity, margin_value)):
            return None
        if balance <= 0 or margin_value < 0:
            return None
        return AccountInfo(
            login=login,
            server=server.strip(),
            currency=currency,
            balance=balance,
            equity=equity,
            margin_free=margin_value,
            account_type=str(data.get("account_type", "demo")),
            leverage=int(data.get("leverage", 0)),
            company=str(data.get("company", "")),
        )
    except (KeyError, ValueError, TypeError, InvalidOperation):
        return None


def _parse_symbols(data: dict, account_number: int | None) -> list[BrokerSymbol] | None:
    raw_symbols = data.get("symbols")
    if not isinstance(raw_symbols, list):
        return None
    result: list[BrokerSymbol] = []
    seen: set[str] = set()
    for item in raw_symbols:
        if not isinstance(item, dict):
            return None
        name = item.get("name")
        permitted = item.get("trading_permitted")
        if not isinstance(name, str) or not name.strip() or name in seen:
            return None
        if not isinstance(permitted, bool):
            return None
        seen.add(name)
        result.append(BrokerSymbol(name, permitted, account_number))
    return result


def _parse_tick(data: dict, recv_mono: float) -> Tick | None:
    try:
        bid = Decimal(str(data["bid"]))
        ask = Decimal(str(data["ask"]))
        if not bid.is_finite() or not ask.is_finite():
            return None
        return Tick(
            broker_symbol=str(data["broker_symbol"]),
            bid=bid,
            ask=ask,
            server_time_ms=int(data["server_time_ms"]),
            recv_time_mono=recv_mono,
        )
    except (KeyError, ValueError, TypeError, InvalidOperation):
        return None


def _parse_tick_data(
    data: dict, recv_mono: float,
) -> tuple[str, int, int, int, list[Tick]] | None:
    """Parse Phase 3 TICK_DATA; malformed items are rejected individually."""
    try:
        pair = data["pair"]
        run_counter = data["run_counter"]
        sequence = data["batch_sequence"]
        raw_ticks = data["ticks"]
        dropped = data.get("dropped_count", 0)
        if not isinstance(pair, str) or not pair.strip():
            return None
        if (isinstance(run_counter, bool) or not isinstance(run_counter, int) or run_counter < 0
                or isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0
                or isinstance(dropped, bool) or not isinstance(dropped, int) or dropped < 0):
            return None
        if not isinstance(raw_ticks, list):
            return None
        if not raw_ticks:
            return None
        ticks: list[Tick] = []
        rejected = 0
        for index, item in enumerate(raw_ticks):
            if not isinstance(item, dict):
                rejected += 1
                continue
            try:
                bid = Decimal(str(item["bid"]))
                ask = Decimal(str(item["ask"]))
                stamp_text = item["broker_timestamp"]
                if not isinstance(stamp_text, str):
                    rejected += 1
                    continue
                stamp = datetime.fromisoformat(stamp_text.replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    rejected += 1
                    continue
                if not bid.is_finite() or not ask.is_finite() or bid <= 0 or ask < bid:
                    rejected += 1
                    continue
                stamp = stamp.astimezone(timezone.utc)
                ticks.append(Tick(
                    broker_symbol=pair, pair=pair, bid=bid, ask=ask,
                    server_time_ms=int(stamp.timestamp() * 1000),
                    recv_time_mono=recv_mono, local_receipt_time=recv_mono,
                    broker_timestamp=stamp, batch_sequence=sequence,
                    run_counter=run_counter, is_newest=(index == len(raw_ticks) - 1),
                ))
            except (KeyError, ValueError, TypeError, InvalidOperation, OverflowError):
                rejected += 1
                continue
        if rejected:
            _LOGGER.warning("rejected %d malformed or crossed ticks from TICK_DATA for %s", rejected, pair)
        if not ticks:
            return None
        return pair.strip(), run_counter, sequence, dropped, ticks
    except (KeyError, TypeError):
        return None


def _parse_market_status(data: dict) -> tuple[str, bool, datetime] | None:
    try:
        pair = data["pair"]
        is_open = data["is_market_open"]
        raw_time = data["server_time"]
        if not isinstance(pair, str) or not pair.strip() or not isinstance(is_open, bool):
            return None
        if not isinstance(raw_time, str):
            return None
        server_time = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        if server_time.tzinfo is None:
            return None
        return pair.strip(), is_open, server_time.astimezone(timezone.utc)
    except (KeyError, ValueError, TypeError):
        return None


def _parse_tick_batch(data: dict, recv_mono: float) -> list[Tick] | None:
    try:
        symbol = str(data["broker_symbol"])
        ticks_raw = data["ticks"]
        if not isinstance(ticks_raw, list) or not ticks_raw:
            return None
        newest_index = int(data["newest_index"])
        batch_size = int(data["batch_size"])
        dropped = int(data["dropped"])
        terminal_instance_id = str(data["terminal_instance_id"])
        if not terminal_instance_id:
            return None
        ea_instance_id = str(data["ea_instance_id"])
        if not ea_instance_id:
            return None
        int(data["ea_run_id"])
        int(data["batch_seq"])
        if newest_index < 0 or newest_index >= len(ticks_raw):
            return None
        if batch_size != len(ticks_raw):
            return None
        if dropped < 0:
            return None
        ticks: list[Tick] = []
        for i, t in enumerate(ticks_raw):
            bid = Decimal(str(t["bid"]))
            ask = Decimal(str(t["ask"]))
            if not bid.is_finite() or not ask.is_finite():
                return None
            ticks.append(Tick(
                broker_symbol=symbol,
                bid=bid,
                ask=ask,
                server_time_ms=int(t["server_time_ms"]),
                recv_time_mono=recv_mono,
                is_newest=(i == newest_index),
            ))
        return ticks
    except (KeyError, ValueError, TypeError, IndexError, InvalidOperation):
        return None


def _parse_contract_spec(data: dict) -> ContractSpec | None:
    try:
        digits = data["digits"]
        permissions = data.get("trading_permissions")
        if permissions is None:
            permitted = data.get("trade_allowed")
            if not isinstance(permitted, bool):
                return None
            permissions = "FULL" if permitted else "DISABLED"
        if not isinstance(permissions, str) or not permissions.strip():
            return None
        if permissions not in {"FULL", "LONGONLY", "SHORTONLY", "CLOSEONLY", "DISABLED"}:
            return None
        if isinstance(digits, bool) or not isinstance(digits, int) or digits < 0:
            return None
        margin = Decimal(str(data["margin_requirement"] if "margin_requirement" in data else data["margin_initial"]))
        commission_raw = data["commission_per_lot"] if "commission_per_lot" in data else data["commission"]
        commission = Decimal(str(commission_raw))
        swap_long = Decimal(str(data["swap_long"]))
        swap_short = Decimal(str(data["swap_short"]))
        point = Decimal(str(data["point"]))
        tick_size = Decimal(str(data["tick_size"]))
        tick_value = Decimal(str(data["tick_value"]))
        contract_size = Decimal(str(data["contract_size"]))
        volume_min = Decimal(str(data["volume_min"]))
        volume_max = Decimal(str(data["volume_max"]))
        volume_step = Decimal(str(data["volume_step"]))
        stop_distance = Decimal(str(data.get("min_stop_distance", "0")))
        positive = (margin, point, tick_size, tick_value, contract_size, volume_min, volume_max, volume_step)
        if not all(value.is_finite() and value > 0 for value in positive):
            return None
        if not all(value.is_finite() for value in (commission, swap_long, swap_short, stop_distance)):
            return None
        if stop_distance < 0 or stop_distance != stop_distance.to_integral_value() or volume_max < volume_min:
            return None
        broker_symbol = data["broker_symbol"]
        if not isinstance(broker_symbol, str) or not broker_symbol.strip():
            return None
        trade_allowed = permissions in {"FULL", "LONGONLY", "SHORTONLY"}
        return ContractSpec(
            broker_symbol=broker_symbol.strip(),
            digits=digits,
            point=point,
            tick_size=tick_size,
            tick_value=tick_value,
            contract_size=contract_size,
            volume_min=volume_min,
            volume_max=volume_max,
            volume_step=volume_step,
            min_stop_distance=stop_distance,
            trade_allowed=trade_allowed,
            margin_initial=margin,
            commission_per_lot=commission,
            swap_long=swap_long,
            swap_short=swap_short,
            trading_permissions=permissions,
        )
    except (KeyError, ValueError, TypeError, InvalidOperation):
        return None
