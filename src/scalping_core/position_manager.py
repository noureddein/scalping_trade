"""Position manager (§9).

Tracks open positions per canonical pair. Enforces one-position-per-pair.
Queries the broker for current position state and floating P/L.

Pure in-memory — a restart loses all position tracking. Account-wide
pair reservation (to prevent duplicate entries across restarts) requires
durable state. Until a PairReservationProvider is injected into
ExecutionEngine, the engine remains inactive.

Pure orchestration — delegates broker queries to ExecutionAdapter.
Does NOT force-close positions (spread spikes, risk locks manage open
positions without forced exits per §12.4, §11.3).
"""
from __future__ import annotations

from decimal import Decimal

from .execution_adapter import ExecutionAdapter
from .order_types import PositionInfo


class PositionManager:
    """Per-pair position tracking with broker reconciliation."""

    def __init__(self) -> None:
        self._positions: dict[str, PositionInfo] = {}

    def has_open_position(self, canonical_pair: str) -> bool:
        return canonical_pair in self._positions

    def get_position(self, canonical_pair: str) -> PositionInfo | None:
        return self._positions.get(canonical_pair)

    @property
    def all_positions(self) -> dict[str, PositionInfo]:
        return dict(self._positions)

    @property
    def count(self) -> int:
        return len(self._positions)

    def floating_pnl_usd(self) -> Decimal:
        return sum((p.floating_pnl_usd for p in self._positions.values()), Decimal(0))

    def total_commission_usd(self) -> Decimal:
        return sum((p.commission_usd for p in self._positions.values()), Decimal(0))

    def total_swap_usd(self) -> Decimal:
        return sum((p.swap_usd for p in self._positions.values()), Decimal(0))

    def register_fill(self, position: PositionInfo) -> bool:
        """Register a newly filled position. Returns False if pair already has one."""
        if position.canonical_pair in self._positions:
            return False
        self._positions[position.canonical_pair] = position
        return True

    def update_from_broker(self, canonical_pair: str, adapter: ExecutionAdapter) -> PositionInfo | None:
        """Refresh position state from broker. Removes if broker reports no position."""
        positions = adapter.get_open_positions(canonical_pair)
        if not positions:
            self._positions.pop(canonical_pair, None)
            return None
        pos = positions[0]
        self._positions[canonical_pair] = pos
        return pos

    def mark_closed(self, canonical_pair: str) -> None:
        self._positions.pop(canonical_pair, None)

    def sync_all(self, pairs: list[str], adapter: ExecutionAdapter) -> None:
        """Reconcile all tracked pairs against the broker."""
        for pair in pairs:
            self.update_from_broker(pair, adapter)
