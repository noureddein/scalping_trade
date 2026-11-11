"""Market data ingestion and validation.

Receives Tick objects from the broker adapter, validates them, and tracks
per-pair feed health. Pure in-memory — no database, no persistence.

Fail-closed: any tick that fails validation is rejected and counted.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from .broker_types import ContractSpec, Tick


class TickRejectReason(str, Enum):
    INVALID_BID = "INVALID_BID"
    INVALID_ASK = "INVALID_ASK"
    INVERTED_SPREAD = "INVERTED_SPREAD"
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    STALE_SERVER_TIME = "STALE_SERVER_TIME"


@dataclass(frozen=True, slots=True)
class TickResult:
    accepted: bool
    tick: Tick
    reject_reason: TickRejectReason | None = None
    spread_pips: Decimal | None = None


def pip_size(contract: ContractSpec) -> Decimal:
    """Derive pip size from contract spec.

    5-digit and 3-digit brokers quote sub-pips: 1 pip = 10 points.
    4-digit and 2-digit brokers: 1 pip = 1 point.
    """
    if contract.digits in (3, 5):
        return contract.point * 10
    return contract.point


def spread_in_pips(tick: Tick, contract: ContractSpec) -> Decimal:
    ps = pip_size(contract)
    if ps == 0:
        return Decimal(0)
    return (tick.ask - tick.bid) / ps


class PairFeed:
    """Per-pair tick validation and feed health tracking."""

    def __init__(
        self,
        contract: ContractSpec,
        *,
        staleness_threshold_ms: int = 5000,
        max_tick_age_s: float = 10.0,
    ) -> None:
        self._contract = contract
        self._staleness_threshold_ms = staleness_threshold_ms
        self._max_tick_age_s = max_tick_age_s

        self._last_tick: Tick | None = None
        self._last_accepted_time: float = 0.0
        self._accept_count: int = 0
        self._reject_counts: dict[TickRejectReason, int] = {}

    @property
    def contract(self) -> ContractSpec:
        return self._contract

    @property
    def last_tick(self) -> Tick | None:
        return self._last_tick

    @property
    def accept_count(self) -> int:
        return self._accept_count

    @property
    def reject_counts(self) -> dict[TickRejectReason, int]:
        return dict(self._reject_counts)

    def is_fresh(self, now_mono: float | None = None) -> bool:
        if self._last_tick is None:
            return False
        now = now_mono if now_mono is not None else time.monotonic()
        return (now - self._last_accepted_time) <= self._max_tick_age_s

    def process_tick(self, tick: Tick) -> TickResult:
        reason = self._validate(tick)
        if reason is not None:
            self._reject_counts[reason] = self._reject_counts.get(reason, 0) + 1
            return TickResult(accepted=False, tick=tick, reject_reason=reason)

        sp = spread_in_pips(tick, self._contract)
        self._last_tick = tick
        self._last_accepted_time = tick.recv_time_mono
        self._accept_count += 1
        return TickResult(accepted=True, tick=tick, spread_pips=sp)

    def _validate(self, tick: Tick) -> TickRejectReason | None:
        if tick.bid <= 0:
            return TickRejectReason.INVALID_BID
        if tick.ask <= 0:
            return TickRejectReason.INVALID_ASK
        if tick.ask < tick.bid:
            return TickRejectReason.INVERTED_SPREAD

        prev = self._last_tick
        if prev is not None:
            if (tick.server_time_ms == prev.server_time_ms
                    and tick.bid == prev.bid
                    and tick.ask == prev.ask):
                return TickRejectReason.DUPLICATE

            if tick.server_time_ms < prev.server_time_ms:
                return TickRejectReason.OUT_OF_ORDER

        if self._last_tick is not None:
            age_ms = tick.recv_time_mono - self._last_accepted_time
            if age_ms > self._staleness_threshold_ms / 1000.0:
                pass  # gap detected but tick itself is valid

        return None
