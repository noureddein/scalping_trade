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
import socket
import struct
import threading
import time
from collections.abc import Callable
from decimal import Decimal

from .broker_adapter import BrokerAdapter
from .broker_types import AccountInfo, ConnectionStatus, ContractSpec, Tick

_HEADER_SIZE = 4
_MAX_MESSAGE_SIZE = 1024 * 1024  # 1 MiB


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
    ) -> None:
        self._port = port
        self._heartbeat_timeout_s = heartbeat_timeout_s
        self._data_staleness_s = data_staleness_s
        self._on_tick = on_tick

        self._server_sock: socket.socket | None = None
        self._client_sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._receiver_thread: threading.Thread | None = None
        self._running = False

        self._last_message_time: float = 0.0
        self._account_info: AccountInfo | None = None
        self._account_info_time: float = 0.0
        self._symbols: list[str] = []
        self._symbols_time: float = 0.0
        self._contracts: dict[str, ContractSpec] = {}
        self._contracts_time: dict[str, float] = {}
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
                return ConnectionStatus.DISCONNECTED
            if self._client_sock is None:
                return ConnectionStatus.DISCONNECTED
            elapsed = time.monotonic() - self._last_message_time
            if elapsed > self._heartbeat_timeout_s:
                return ConnectionStatus.DISCONNECTED
            return ConnectionStatus.CONNECTED

    def get_account_info(self) -> AccountInfo | None:
        with self._lock:
            if self._account_info is None:
                return None
            if time.monotonic() - self._account_info_time > self._data_staleness_s:
                return None
            return self._account_info

    def discover_symbols(self) -> list[str]:
        with self._lock:
            if not self._symbols:
                return []
            if time.monotonic() - self._symbols_time > self._data_staleness_s:
                return []
            return list(self._symbols)

    def get_contract_spec(self, broker_symbol: str) -> ContractSpec | None:
        with self._lock:
            spec = self._contracts.get(broker_symbol)
            if spec is None:
                return None
            ts = self._contracts_time.get(broker_symbol, 0.0)
            if time.monotonic() - ts > self._data_staleness_s:
                return None
            return spec

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
                    try:
                        self._client_sock.close()
                    except OSError:
                        pass
                self._client_sock = client
                client.settimeout(1.0)
            self._read_loop(client)

    def _read_loop(self, client: socket.socket) -> None:
        buf = b""
        while self._running:
            try:
                chunk = client.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while len(buf) >= _HEADER_SIZE:
                msg_len = struct.unpack("!I", buf[:_HEADER_SIZE])[0]
                if msg_len > _MAX_MESSAGE_SIZE:
                    buf = b""
                    break
                if len(buf) < _HEADER_SIZE + msg_len:
                    break
                payload = buf[_HEADER_SIZE:_HEADER_SIZE + msg_len]
                buf = buf[_HEADER_SIZE + msg_len:]
                self._handle_message(payload)
        with self._lock:
            if self._client_sock is client:
                self._client_sock = None
        try:
            client.close()
        except OSError:
            pass

    _KNOWN_TYPES = frozenset({
        "heartbeat", "account_info", "symbol_list", "contract_spec",
        "tick", "tick_batch",
    })

    def _handle_message(self, payload: bytes) -> None:
        try:
            msg = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if not isinstance(msg, dict):
            return
        msg_type = msg.get("type")
        if msg_type not in self._KNOWN_TYPES:
            return
        data = msg.get("data")
        if not isinstance(data, dict):
            return
        now = time.monotonic()
        accepted = False
        tick: Tick | None = None
        batch_ticks: list[Tick] | None = None

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
                syms = data.get("symbols")
                if isinstance(syms, list):
                    self._symbols = [str(s) for s in syms]
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

            if accepted:
                self._last_message_time = now

        if msg_type == "tick" and tick is not None and self._on_tick is not None:
            self._on_tick(tick)
        if msg_type == "tick_batch" and batch_ticks and self._on_tick is not None:
            for t in batch_ticks:
                self._on_tick(t)

    def send_request(self, request_type: str, params: dict | None = None) -> bool:
        """Send a request message to the EA. Returns False if no client."""
        msg = json.dumps({"type": "request", "data": {"request": request_type, **(params or {})}})
        payload = msg.encode("utf-8")
        frame = struct.pack("!I", len(payload)) + payload
        with self._lock:
            client = self._client_sock
        if client is None:
            return False
        try:
            client.sendall(frame)
            return True
        except OSError:
            return False


def _parse_account_info(data: dict) -> AccountInfo | None:
    try:
        return AccountInfo(
            login=int(data["login"]),
            server=str(data["server"]),
            currency=str(data["currency"]),
            balance=Decimal(str(data["balance"])),
            equity=Decimal(str(data["equity"])),
            margin_free=Decimal(str(data["margin_free"])),
            account_type=str(data.get("account_type", "demo")),
            leverage=int(data.get("leverage", 0)),
            company=str(data.get("company", "")),
        )
    except (KeyError, ValueError, TypeError):
        return None


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
    except (KeyError, ValueError, TypeError, IndexError):
        return None


def _parse_contract_spec(data: dict) -> ContractSpec | None:
    try:
        return ContractSpec(
            broker_symbol=str(data["broker_symbol"]),
            digits=int(data["digits"]),
            point=Decimal(str(data["point"])),
            tick_size=Decimal(str(data["tick_size"])),
            tick_value=Decimal(str(data["tick_value"])),
            contract_size=Decimal(str(data["contract_size"])),
            volume_min=Decimal(str(data["volume_min"])),
            volume_max=Decimal(str(data["volume_max"])),
            volume_step=Decimal(str(data["volume_step"])),
            min_stop_distance=Decimal(str(data.get("min_stop_distance", "0"))),
            trade_allowed=bool(data.get("trade_allowed", True)),
            margin_initial=Decimal(str(data["margin_initial"])) if data.get("margin_initial") is not None else None,
            commission_per_lot=Decimal(str(data["commission_per_lot"])) if data.get("commission_per_lot") is not None else None,
            swap_long=Decimal(str(data["swap_long"])) if data.get("swap_long") is not None else None,
            swap_short=Decimal(str(data["swap_short"])) if data.get("swap_short") is not None else None,
        )
    except (KeyError, ValueError, TypeError):
        return None
