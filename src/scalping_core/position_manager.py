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

from datetime import date, datetime
from decimal import Decimal
from dataclasses import replace

from .broker_types import ContractSpec
from .daily_risk import DailyPnL, DailyRiskController, calculate_floating_pnl_usd
from .risk_gate import RiskState
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

    def update_floating_from_quote(
        self, canonical_pair: str, *, bid: Decimal, ask: Decimal,
        contract: ContractSpec, account_to_usd_rate: Decimal | None,
    ) -> PositionInfo | None:
        """Refresh a tracked position using the current exit-side quote."""
        current = self._positions.get(canonical_pair)
        if current is None:
            return None
        mark = bid if current.side.value == "BUY" else ask
        pnl = calculate_floating_pnl_usd(
            side=current.side, entry_price=current.open_price,
            current_bid=bid, current_ask=ask, lot_size=current.volume_lots,
            contract=contract, account_to_usd_rate=account_to_usd_rate,
        )
        updated = replace(current, current_price=mark, floating_pnl_usd=pnl)
        self._positions[canonical_pair] = updated
        return updated

    def update_floating_and_persist_risk(
        self, canonical_pair: str, *, bid: Decimal, ask: Decimal,
        contract: ContractSpec, account_to_usd_rate: Decimal | None,
        controller: DailyRiskController, account_id: str, trading_day: date,
        current_state: RiskState, pnl: DailyPnL, at: datetime,
    ) -> tuple[RiskState, DailyPnL]:
        """Mark one pair and persist aggregate daily risk on every quote.

        The position's commission and swap remain separate daily P/L fields;
        only the floating component is replaced from its current market mark.
        With no tracked position, aggregate floating P/L is reset to zero.
        """
        self.update_floating_from_quote(
            canonical_pair, bid=bid, ask=ask, contract=contract,
            account_to_usd_rate=account_to_usd_rate,
        )
        updated_pnl = DailyPnL(
            realized_pnl_usd=pnl.realized_pnl_usd,
            floating_pnl_usd=self.floating_pnl_usd(),
            commission_usd=pnl.commission_usd,
            swap_usd=pnl.swap_usd,
        )
        state = controller.update_pnl(
            account_id=account_id, trading_day=trading_day,
            current_state=current_state, pnl=updated_pnl, at=at,
        )
        return state, updated_pnl

    def settle_position(
        self, canonical_pair: str, *,
        exit_price: Decimal, exit_time_ms: int,
        realized_pnl: Decimal, commission: Decimal, swap: Decimal,
    ) -> PositionInfo | None:
        """Settle an open position: OPEN→SETTLING→CLOSED.

        Returns the settled PositionInfo with exit data, or None if no
        position tracked for this pair.
        """
        current = self._positions.get(canonical_pair)
        if current is None:
            return None
        settled = replace(
            current,
            current_price=exit_price,
            floating_pnl_usd=realized_pnl,
            commission_usd=commission,
            swap_usd=swap,
        )
        self._positions.pop(canonical_pair, None)
        return settled

    def sync_all(self, pairs: list[str], adapter: ExecutionAdapter) -> None:
        """Reconcile all tracked pairs against the broker."""
        for pair in pairs:
            self.update_from_broker(pair, adapter)
