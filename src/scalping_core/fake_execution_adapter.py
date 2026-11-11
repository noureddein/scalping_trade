"""Fake execution adapter for testing. No MT5, no network.

Deterministic: caller controls what quotes, fills, and positions are
returned. Tracks all calls for assertion.
"""
from __future__ import annotations

from decimal import Decimal

from .broker_types import Tick
from .execution_adapter import ExecutionAdapter
from .order_types import OrderRequest, OrderResult, OrderSide, OrderState, PositionInfo


class FakeExecutionAdapter(ExecutionAdapter):
    """Test double for execution. All behavior is caller-controlled.

    is_simulation is True — ExecutionEngine refuses to activate with this
    adapter. Use only in tests and simulation; a concrete broker-connected
    adapter is required for live/demo mode.
    """

    @property
    def is_simulation(self) -> bool:
        return True

    @property
    def is_execution_enabled(self) -> bool:
        return True

    def __init__(self) -> None:
        self._quotes: dict[str, Tick] = {}
        self._next_fill: OrderResult | None = None
        self._next_query: OrderResult | None = None
        self._positions: dict[str, list[PositionInfo]] = {}
        self._next_close: OrderResult | None = None
        self._next_ticket: int = 100000
        self.submit_calls: list[OrderRequest] = []
        self.query_calls: list[int] = []
        self.close_calls: list[tuple[int, Decimal]] = []
        self.quote_calls: list[str] = []

    def set_quote(self, broker_symbol: str, tick: Tick) -> None:
        self._quotes[broker_symbol] = tick

    def set_next_fill(self, result: OrderResult | None = None) -> None:
        self._next_fill = result

    def set_next_query(self, result: OrderResult) -> None:
        self._next_query = result

    def set_positions(self, canonical_pair: str, positions: list[PositionInfo]) -> None:
        self._positions[canonical_pair] = positions

    def set_next_close(self, result: OrderResult) -> None:
        self._next_close = result

    def get_fresh_quote(self, broker_symbol: str) -> Tick | None:
        self.quote_calls.append(broker_symbol)
        return self._quotes.get(broker_symbol)

    def submit_order(self, request: OrderRequest) -> OrderResult:
        self.submit_calls.append(request)
        if self._next_fill is not None:
            result = self._next_fill
            self._next_fill = None
            return result
        ticket = self._next_ticket
        self._next_ticket += 1
        return OrderResult(
            state=OrderState.FILLED,
            broker_ticket=ticket,
            fill_price=request.fresh_quote_ask if request.side == OrderSide.BUY else request.fresh_quote_bid,
            fill_volume=request.volume_lots,
            fill_time_ms=request.fresh_quote_time_ms,
        )

    def query_order(self, broker_ticket: int) -> OrderResult:
        self.query_calls.append(broker_ticket)
        if self._next_query is not None:
            result = self._next_query
            self._next_query = None
            return result
        return OrderResult(state=OrderState.UNKNOWN, broker_ticket=broker_ticket)

    def get_open_positions(self, canonical_pair: str) -> list[PositionInfo]:
        return self._positions.get(canonical_pair, [])

    def close_position(self, broker_ticket: int, volume_lots: Decimal) -> OrderResult:
        self.close_calls.append((broker_ticket, volume_lots))
        if self._next_close is not None:
            result = self._next_close
            self._next_close = None
            return result
        return OrderResult(state=OrderState.FILLED, broker_ticket=broker_ticket)
