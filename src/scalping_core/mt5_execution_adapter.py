"""MT5 execution adapter — TCP-based, hard-disabled.

Implements ExecutionAdapter for the approved Architecture C:
  - Local Windows MT5 + WSL2 Python (development)
  - Ubuntu server MT5 under Wine (production)

The adapter communicates with the MQL5 EA over TCP 127.0.0.1 using the
same length-prefixed JSON wire protocol as TcpBrokerAdapter. Execution
commands (order submission, position close, order query) are sent as
request messages; the EA executes them via MT5's order_send/order_check
and returns results.

HARD-DISABLED: live execution is permanently disabled in this module.
submit_order and close_position return FAILED without transmitting.
This is a structural safety constraint, not a configuration toggle —
the adapter must be modified and re-reviewed before any broker
communication can occur. The adapter's is_simulation property returns
False (it is not a test double), but the DISABLED flag prevents any
outbound execution.

Quote retrieval and position queries are read-only and permitted.

Post-restart correlation limits:
  MT5 does not provide authoritative request-level correlation. The
  comment field (max 31 chars) in MqlTradeRequest is the only vector
  for embedding a correlation token, but MT5 may truncate or modify it.
  history_deals_get() is a sequential scan, not an indexed lookup.
  If correlation cannot be verified exactly, the order stays unresolved.
  See execution_engine.py StartupReconciler docstring for full analysis.
"""
from __future__ import annotations

import json
import logging
import socket
import struct
import threading
import time
from decimal import Decimal

from .broker_types import Tick
from .execution_adapter import ExecutionAdapter
from .order_types import (
    OrderRequest,
    OrderResult,
    OrderState,
    PositionInfo,
)

log = logging.getLogger(__name__)

_HEADER_SIZE = 4
_MAX_MESSAGE_SIZE = 1024 * 1024
_EXECUTION_DISABLED = True


class Mt5ExecutionAdapter(ExecutionAdapter):
    """TCP-based MT5 execution adapter. Hard-disabled for safety.

    Connects to the MQL5 EA's TCP server on 127.0.0.1. Read-only
    operations (quotes, positions, order queries) work when connected.
    Execution operations (submit, close) are structurally disabled.
    """

    @property
    def is_simulation(self) -> bool:
        return False

    @property
    def is_execution_enabled(self) -> bool:
        return not _EXECUTION_DISABLED

    def __init__(
        self,
        port: int,
        *,
        connect_timeout_s: float = 5.0,
        recv_timeout_s: float = 10.0,
    ) -> None:
        self._port = port
        self._connect_timeout_s = connect_timeout_s
        self._recv_timeout_s = recv_timeout_s
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._quotes: dict[str, Tick] = {}
        self._quotes_time: dict[str, float] = {}
        self._quote_staleness_s = 5.0

    def connect(self) -> bool:
        """Connect to the EA's TCP server. Returns True on success."""
        with self._lock:
            if self._sock is not None:
                return True
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self._connect_timeout_s)
                sock.connect(("127.0.0.1", self._port))
                sock.settimeout(self._recv_timeout_s)
                self._sock = sock
                log.info("connected to MT5 EA on port %d", self._port)
                return True
            except OSError as e:
                log.warning("failed to connect to EA on port %d: %s", self._port, e)
                return False

    def disconnect(self) -> None:
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None

    def get_fresh_quote(self, broker_symbol: str) -> Tick | None:
        with self._lock:
            tick = self._quotes.get(broker_symbol)
            if tick is None:
                return None
            age = time.monotonic() - self._quotes_time.get(broker_symbol, 0.0)
            if age > self._quote_staleness_s:
                return None
            return tick

    def update_quote(self, tick: Tick) -> None:
        """Called by the tick receiver to update cached quotes."""
        with self._lock:
            self._quotes[tick.broker_symbol] = tick
            self._quotes_time[tick.broker_symbol] = tick.recv_time_mono

    def submit_order(self, request: OrderRequest) -> OrderResult:
        """Submit a market order via the EA's TCP protocol.

        Hard-disabled by default (_EXECUTION_DISABLED = True): returns
        FAILED without transmitting. FAILED is correct per the adapter
        contract — proven local failure before any request bytes left
        the process.

        When enabled, builds an MqlTradeRequest-shaped JSON message,
        sends it to the EA, and parses the response. Once transmission
        begins (sendall called), any error returns UNKNOWN — never
        FAILED — because the EA may have received and forwarded the
        request to MT5.
        """
        if _EXECUTION_DISABLED:
            log.warning(
                "submit_order called but execution is hard-disabled — "
                "returning FAILED for %s",
                request.idempotency_key,
            )
            return OrderResult(
                state=OrderState.FAILED,
                reject_reason="execution_hard_disabled",
            )

        with self._lock:
            sock = self._sock
        if sock is None:
            return OrderResult(
                state=OrderState.FAILED,
                reject_reason="not_connected",
            )

        action = "ORDER_TYPE_BUY" if request.side.value == "BUY" else "ORDER_TYPE_SELL"
        params = {
            "symbol": request.broker_symbol,
            "action": action,
            "volume": str(request.volume_lots),
            "sl": str(request.stop_loss_price),
            "tp": str(request.take_profit_price) if request.take_profit_price else "",
            "comment": request.idempotency_key[:31],
        }

        # Once _send_request calls sendall, bytes may have reached the
        # EA. Any error after that point is UNKNOWN, not FAILED.
        response = self._send_request("order_send", params)
        if response is None:
            # sendall was attempted inside _send_request — the request
            # may have reached the EA. Cannot prove it didn't.
            return OrderResult(
                state=OrderState.UNKNOWN,
                reject_reason="ea_communication_failed",
            )

        return _parse_order_result(response, response.get("broker_ticket"))

    def query_order(self, broker_ticket: int) -> OrderResult:
        """Query order state from the broker via the EA."""
        response = self._send_request("query_order", {
            "ticket": broker_ticket,
        })
        if response is None:
            return OrderResult(
                state=OrderState.UNKNOWN,
                broker_ticket=broker_ticket,
                reject_reason="ea_communication_failed",
            )
        return _parse_order_result(response, broker_ticket)

    def get_open_positions(self, canonical_pair: str) -> list[PositionInfo]:
        """Query open positions for a pair from the broker via the EA."""
        response = self._send_request("get_positions", {
            "pair": canonical_pair,
        })
        if response is None:
            return []
        positions = response.get("positions", [])
        result = []
        for p in positions:
            parsed = _parse_position(p)
            if parsed is not None:
                result.append(parsed)
        return result

    def close_position(self, broker_ticket: int, volume_lots: Decimal) -> OrderResult:
        """Close a position via the EA's TCP protocol.

        Hard-disabled by default — blocked alongside order_send. The
        disabled gate is structural: ALL broker-mutating operations
        are blocked, including risk-reducing closes. This is a
        structural default, not an owner-approved policy — see
        ExecutionAdapter.close_position for the unresolved decision.

        When enabled, sends a close request for the given ticket.
        Once transmission begins, any error returns UNKNOWN — never
        FAILED.
        """
        if _EXECUTION_DISABLED:
            log.warning(
                "close_position called but execution is hard-disabled — "
                "returning FAILED for ticket %d",
                broker_ticket,
            )
            return OrderResult(
                state=OrderState.FAILED,
                reject_reason="execution_hard_disabled",
            )

        with self._lock:
            sock = self._sock
        if sock is None:
            return OrderResult(
                state=OrderState.FAILED,
                reject_reason="not_connected",
            )

        params = {
            "ticket": broker_ticket,
            "volume": str(volume_lots),
        }

        response = self._send_request("close_position", params)
        if response is None:
            return OrderResult(
                state=OrderState.UNKNOWN,
                broker_ticket=broker_ticket,
                reject_reason="ea_communication_failed",
            )

        return _parse_order_result(response, broker_ticket)

    def _send_request(
        self, request_type: str, params: dict,
    ) -> dict | None:
        """Send a request to the EA and wait for response.

        Returns the parsed response dict on success, None on error.

        Callers that distinguish FAILED (no bytes sent) from UNKNOWN
        (bytes may have been sent) must check socket availability
        themselves *before* calling this method. Once this method is
        entered with a live socket, the caller must assume bytes may
        have left the process and treat a None return as UNKNOWN.
        """
        with self._lock:
            sock = self._sock
        if sock is None:
            return None
        msg = json.dumps({
            "type": "request",
            "data": {"request": request_type, **params},
        })
        payload = msg.encode("utf-8")
        frame = struct.pack("!I", len(payload)) + payload
        try:
            sock.sendall(frame)
            return self._recv_response(sock)
        except OSError:
            log.warning("EA communication failed for %s", request_type)
            return None

    def _recv_response(self, sock: socket.socket) -> dict | None:
        """Read one length-prefixed JSON response."""
        try:
            header = self._recv_exact(sock, _HEADER_SIZE)
            if header is None:
                return None
            msg_len = struct.unpack("!I", header)[0]
            if msg_len > _MAX_MESSAGE_SIZE:
                return None
            body = self._recv_exact(sock, msg_len)
            if body is None:
                return None
            return json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return None

    @staticmethod
    def _recv_exact(sock: socket.socket, n: int) -> bytes | None:
        buf = b""
        while len(buf) < n:
            try:
                chunk = sock.recv(n - len(buf))
            except OSError:
                return None
            if not chunk:
                return None
            buf += chunk
        return buf


def _parse_order_result(data: dict, ticket: int) -> OrderResult:
    try:
        state_str = data.get("state", "UNKNOWN")
        state = OrderState(state_str)
        return OrderResult(
            state=state,
            broker_ticket=data.get("broker_ticket", ticket),
            fill_price=Decimal(str(data["fill_price"])) if data.get("fill_price") else None,
            fill_volume=Decimal(str(data["fill_volume"])) if data.get("fill_volume") else None,
            fill_time_ms=data.get("fill_time_ms"),
            reject_reason=data.get("reject_reason"),
            broker_retcode=data.get("broker_retcode"),
            raw_comment=data.get("raw_comment"),
        )
    except (KeyError, ValueError):
        return OrderResult(state=OrderState.UNKNOWN, broker_ticket=ticket)


def _parse_position(data: dict) -> PositionInfo | None:
    try:
        from .order_types import OrderSide
        return PositionInfo(
            broker_ticket=int(data["ticket"]),
            canonical_pair=str(data["pair"]),
            broker_symbol=str(data["symbol"]),
            side=OrderSide(data["side"]),
            volume_lots=Decimal(str(data["volume"])),
            open_price=Decimal(str(data["open_price"])),
            current_price=Decimal(str(data["current_price"])),
            stop_loss=Decimal(str(data["stop_loss"])),
            take_profit=Decimal(str(data["take_profit"])) if data.get("take_profit") else None,
            floating_pnl_usd=Decimal(str(data["floating_pnl"])),
            open_time_ms=int(data["open_time_ms"]),
            swap_usd=Decimal(str(data.get("swap", "0"))),
            commission_usd=Decimal(str(data.get("commission", "0"))),
        )
    except (KeyError, ValueError, TypeError):
        return None
