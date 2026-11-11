"""Execution adapter interface (Phase 5).

Concrete implementations:
  - Mt5ExecutionAdapter: TCP to MQL5 EA, hard-disabled by default.
  - FakeExecutionAdapter: test double (is_simulation=True).

Phase 2's TcpBrokerAdapter is read-only and does not implement
ExecutionAdapter. Until a concrete, non-simulation adapter is injected
into ExecutionEngine, the engine remains inactive.
"""
from __future__ import annotations

import abc

from .broker_types import Tick
from .order_types import OrderRequest, OrderResult, PositionInfo


class ExecutionAdapter(abc.ABC):
    """Abstract execution boundary — order submission and position query.

    Implementations must be fail-closed. get_fresh_quote must return None
    when no reliable quote is available.

    submit_order / close_position state contract:

      FAILED — proven local failure *before* any request bytes or side
      effect left the process. No socket write started, no broker state
      could have been created. The engine trusts this and releases the
      pair reservation immediately.

      UNKNOWN — any partial send, timeout, exception, or uncertain
      result *after* transmission begins. The engine holds the pair
      reservation until reconciliation confirms the outcome.

      REJECTED — the broker explicitly refused the order. Terminal.

      Rule: once the first byte of a request has been (or might have
      been) written to the transport, the outcome is UNKNOWN — never
      FAILED. Returning FAILED after a possible send lets the engine
      release the reservation and risks a duplicate entry.

    Subclasses must set is_simulation: True for test doubles, False for
    broker-connected adapters. ExecutionEngine refuses to activate when
    the adapter is a simulation.

    Subclasses must set is_execution_enabled: True only when the adapter
    can actually transmit orders to the broker. A hard-disabled adapter
    must return False so the engine does not report itself as active.
    """

    @property
    @abc.abstractmethod
    def is_simulation(self) -> bool:
        """True for test/simulation adapters that must not activate live trading."""

    @property
    @abc.abstractmethod
    def is_execution_enabled(self) -> bool:
        """True when the adapter can actually submit orders to the broker.

        A hard-disabled adapter (e.g. _EXECUTION_DISABLED = True) must
        return False. The engine checks this in is_active() so it does
        not report readiness when execution is structurally prevented."""

    @abc.abstractmethod
    def get_fresh_quote(self, broker_symbol: str) -> Tick | None:
        """Obtain a fresh bid/ask from the broker. None if unavailable."""

    @abc.abstractmethod
    def submit_order(self, request: OrderRequest) -> OrderResult:
        """Submit a market order.

        FAILED only for proven local failure before any bytes leave the
        process. Once transmission begins (or might have begun), return
        UNKNOWN — never FAILED. See class docstring for the full contract."""

    @abc.abstractmethod
    def query_order(self, broker_ticket: int) -> OrderResult:
        """Query current state of a previously submitted order."""

    @abc.abstractmethod
    def get_open_positions(self, canonical_pair: str) -> list[PositionInfo]:
        """Return all open positions for a canonical pair."""

    @abc.abstractmethod
    def close_position(self, broker_ticket: int, volume_lots: "Decimal") -> OrderResult:
        """Request position close.

        FAILED only for proven local failure before any bytes leave the
        process. Once transmission begins (or might have begun), return
        UNKNOWN — never FAILED. See class docstring for the full contract.

        EA disabled-gate behavior: when execution is disabled (the EA's
        InpExecutionEnabled=false or the Python adapter's
        _EXECUTION_DISABLED=True), close requests are blocked alongside
        entry requests. The disabled gate is a structural safety stop
        that prevents ALL broker-mutating operations.

        UNRESOLVED POLICY: blocking risk-reducing closes alongside
        entries is the current structural default, NOT an owner-approved
        decision. The project requires managing existing positions
        (§9, §12), but the owner has not decided whether risk-reducing
        closes should be permitted while entries are disabled. Until
        that decision is made, execution remains inactive and this gate
        blocks both. Separating entry and close permission requires a
        new EA input parameter (e.g. InpCloseEnabled) and a
        corresponding Python adapter flag — the entry gate must never
        implicitly grant close permission or vice versa."""
