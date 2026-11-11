"""Market data ingestion and validation.

Receives Tick objects from the broker adapter, validates them, and tracks
per-pair feed health. Pure in-memory — no database, no persistence.

Fail-closed: any tick that fails validation is rejected and counted.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from collections import deque
from collections.abc import Callable

from .broker_types import (
    ContractSpec, Tick, TickActivityLevel, TickBatch, TickValidationStatus,
)

_LOGGER = logging.getLogger(__name__)


class TickRejectReason(str, Enum):
    INVALID_BID = "INVALID_BID"
    INVALID_ASK = "INVALID_ASK"
    INVERTED_SPREAD = "INVERTED_SPREAD"
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    STALE_SERVER_TIME = "STALE_SERVER_TIME"
    CROSSED = "CROSSED"
    STALE = "STALE"
    MALFORMED = "MALFORMED"
    REORDERED = "REORDERED"


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
        staleness_threshold_ms: int | None = None,
        max_tick_age_s: float | None = None,
    ) -> None:
        if staleness_threshold_ms is not None and staleness_threshold_ms <= 0:
            raise ValueError("staleness threshold must be positive")
        if max_tick_age_s is not None and max_tick_age_s <= 0:
            raise ValueError("maximum tick age must be positive")
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
        if self._last_tick is None or self._max_tick_age_s is None:
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


@dataclass(frozen=True, slots=True)
class MarketStatus:
    pair: str
    is_market_open: bool
    server_time: datetime


@dataclass(frozen=True, slots=True)
class BatchResult:
    batch: TickBatch
    accepted_ticks: tuple[Tick, ...]
    rejected_ticks: tuple[TickResult, ...]
    deduplicated_count: int = 0


@dataclass(slots=True)
class MarketHealthState:
    pair: str
    staleness_threshold_s: float | None
    normal_min_ticks_per_second: float | None = None
    low_min_ticks_per_second: float | None = None
    none_after_s: float | None = None
    baseline_window_s: float | None = None
    is_stale: bool = True
    last_tick_time: float | None = None
    tick_activity_level: TickActivityLevel = TickActivityLevel.NONE
    is_spread_abnormal: bool = False
    is_recovering: bool = False
    reopened_unstable: bool = False
    is_market_open: bool | None = None
    ticks: deque[float] = field(default_factory=deque)
    activity_rate_samples: deque[tuple[float, float]] = field(default_factory=deque)
    last_activity_sample_time: float | None = None
    _was_none: bool = True

    @property
    def is_entry_blocked(self) -> bool:
        configured = all(value is not None and value > 0 for value in (
            self.staleness_threshold_s, self.normal_min_ticks_per_second,
            self.low_min_ticks_per_second, self.none_after_s,
            self.baseline_window_s,
        ))
        return (not configured or self.is_stale or
                self.tick_activity_level is not TickActivityLevel.NORMAL or
                self.is_spread_abnormal or self.is_recovering or self.reopened_unstable or
                self.is_market_open is False)


class MarketDataProcessor:
    """Strict Phase 3 ingestion, validation, batching, and feed health."""

    def __init__(self, on_valid_tick: Callable[[Tick], None] | None = None,
                 on_run_boundary: Callable[[str], None] | None = None) -> None:
        self._on_valid_tick = on_valid_tick
        self._on_run_boundary = on_run_boundary
        self._pairs: dict[str, tuple[str, MarketHealthState]] = {}
        self._last_broker_time: dict[str, datetime] = {}
        self._last_batch: dict[str, tuple[int, int]] = {}
        self._degraded_intervals: list[tuple[str, int, int]] = []
        self._rejections: dict[TickValidationStatus, int] = {}
        self._statuses: dict[str, MarketStatus] = {}

    def register_pair(
        self, canonical_pair: str, broker_symbol: str, *,
        staleness_threshold_s: float | None = None,
        normal_min_ticks_per_second: float | None = None,
        low_min_ticks_per_second: float | None = None,
        none_after_s: float | None = None,
        baseline_window_s: float | None = None,
    ) -> MarketHealthState:
        if not canonical_pair or not broker_symbol:
            raise ValueError("canonical pair and broker symbol are required")
        if canonical_pair in self._pairs:
            raise ValueError(f"pair already registered: {canonical_pair}")
        config_values = (staleness_threshold_s, normal_min_ticks_per_second,
                         low_min_ticks_per_second, none_after_s, baseline_window_s)
        if any(value is not None and (not math.isfinite(value) or value <= 0) for value in config_values):
            raise ValueError("market data thresholds must be positive")
        state = MarketHealthState(
            canonical_pair, staleness_threshold_s, normal_min_ticks_per_second,
            low_min_ticks_per_second, none_after_s, baseline_window_s,
        )
        self._pairs[canonical_pair] = (broker_symbol, state)
        return state

    @property
    def degraded_intervals(self) -> tuple[tuple[str, int, int], ...]:
        return tuple(self._degraded_intervals)

    @property
    def rejection_counts(self) -> dict[TickValidationStatus, int]:
        return dict(self._rejections)

    def process_tick(self, tick: Tick, *, pair: str | None = None,
                     now_mono: float | None = None) -> TickResult:
        canonical = pair or tick.pair or tick.broker_symbol
        registered = self._pairs.get(canonical)
        now = time.monotonic() if now_mono is None else now_mono
        reason: TickValidationStatus | None = None
        receipt = tick.local_receipt_time
        if registered is None or registered[0] != tick.broker_symbol:
            reason = TickValidationStatus.MALFORMED
        elif (isinstance(tick.batch_sequence, bool) or not isinstance(tick.batch_sequence, int)
              or tick.batch_sequence < 0 or isinstance(tick.run_counter, bool)
              or not isinstance(tick.run_counter, int) or tick.run_counter < 0
              or not isinstance(tick.validation_status, TickValidationStatus)):
            reason = TickValidationStatus.MALFORMED
        elif not isinstance(tick.bid, Decimal) or not isinstance(tick.ask, Decimal):
            reason = TickValidationStatus.MALFORMED
        elif not tick.bid.is_finite() or not tick.ask.is_finite() or tick.bid <= 0 or tick.ask <= 0:
            reason = TickValidationStatus.MALFORMED
        elif tick.ask < tick.bid:
            reason = TickValidationStatus.CROSSED
        elif (not isinstance(tick.broker_timestamp, datetime) or tick.broker_timestamp.tzinfo is None
              or receipt is None or isinstance(receipt, bool)
              or not isinstance(receipt, (int, float)) or not math.isfinite(receipt)
              or not math.isfinite(now)):
            reason = TickValidationStatus.MALFORMED
        elif tick.validation_status not in (TickValidationStatus.MALFORMED, TickValidationStatus.VALID):
            reason = tick.validation_status
        else:
            previous = self._last_broker_time.get(canonical)
            if previous is not None and tick.broker_timestamp <= previous:
                reason = (TickValidationStatus.DUPLICATE if tick.broker_timestamp == previous
                          else TickValidationStatus.REORDERED)
            else:
                threshold = registered[1].staleness_threshold_s
                age = now - float(receipt)
                if age < 0 or (threshold is not None and age > threshold):
                    reason = TickValidationStatus.STALE
        if reason is not None:
            self._rejections[reason] = self._rejections.get(reason, 0) + 1
            _LOGGER.warning("rejected market tick for %s: %s", canonical, reason.value)
            legacy = {
                TickValidationStatus.CROSSED: TickRejectReason.CROSSED,
                TickValidationStatus.DUPLICATE: TickRejectReason.DUPLICATE,
                TickValidationStatus.REORDERED: TickRejectReason.REORDERED,
                TickValidationStatus.STALE: TickRejectReason.STALE,
            }.get(reason, TickRejectReason.MALFORMED)
            return TickResult(False, replace(tick, validation_status=reason), legacy)
        state = registered[1]
        assert tick.broker_timestamp is not None
        self._last_broker_time[canonical] = tick.broker_timestamp
        state.is_stale = False
        state.last_tick_time = now
        state.ticks.append(now)
        self._prune_activity(state, now)
        if state._was_none:
            state.reopened_unstable = True
            state.is_recovering = True
        state._was_none = False
        if self._on_valid_tick is not None:
            valid_tick = replace(tick, pair=canonical, validation_status=TickValidationStatus.VALID)
            self._on_valid_tick(valid_tick)
        else:
            valid_tick = replace(tick, pair=canonical, validation_status=TickValidationStatus.VALID)
        return TickResult(True, valid_tick, None, None)

    def process_batch(self, pair: str, sequence_number: int, run_counter: int,
                      ticks: list[Tick], *, now_mono: float | None = None,
                      dropped_count: int = 0) -> BatchResult:
        if (isinstance(sequence_number, bool) or not isinstance(sequence_number, int)
                or isinstance(run_counter, bool) or not isinstance(run_counter, int)
                or sequence_number < 0 or run_counter < 0):
            raise ValueError("batch sequence and run counter must be non-negative")
        if dropped_count < 0:
            raise ValueError("dropped_count must be non-negative")
        if not ticks:
            raise ValueError("empty tick batches are ignored")
        previous = self._last_batch.get(pair)
        boundary = previous is not None and previous[0] != run_counter
        sequence_gap = previous is not None and not boundary and sequence_number > previous[1] + 1
        gap = sequence_gap or dropped_count > 0
        deduped = previous is not None and not boundary and sequence_number <= previous[1]
        rejected: list[TickResult] = []
        accepted: list[Tick] = []
        if not deduped:
            if sequence_gap:
                self._degraded_intervals.append((pair, previous[1] + 1, sequence_number - 1))
                _LOGGER.warning("tick batch sequence gap for %s: %d..%d", pair,
                                previous[1] + 1, sequence_number - 1)
            if dropped_count:
                self._degraded_intervals.append((pair, sequence_number, sequence_number))
                _LOGGER.warning("EA ring buffer dropped %d ticks for %s batch %d",
                                dropped_count, pair, sequence_number)
            if boundary:
                self._last_broker_time.pop(pair, None)
                _LOGGER.info("EA run boundary detected for %s: run_counter=%d", pair, run_counter)
                if self._on_run_boundary is not None:
                    self._on_run_boundary(pair)
            self._last_batch[pair] = (run_counter, sequence_number)
            for tick in ticks:
                candidate = replace(tick, batch_sequence=sequence_number, run_counter=run_counter)
                result = self.process_tick(candidate, pair=pair, now_mono=now_mono)
                if result.accepted:
                    accepted.append(result.tick)
                else:
                    rejected.append(result)
        batch = TickBatch(pair, sequence_number, run_counter, len(ticks), gap, boundary)
        if deduped:
            _LOGGER.info("discarded duplicate or reordered batch for %s sequence=%d", pair, sequence_number)
        return BatchResult(batch, tuple(accepted), tuple(rejected), len(ticks) if deduped else 0)

    def consume_tick_batch(self, pair: str, sequence_number: int, run_counter: int,
                           ticks: list[Tick], dropped: int | bool = 0) -> BatchResult:
        """Adapter callback for ``TcpBrokerAdapter(on_tick_batch=...)``."""
        return self.process_batch(pair, sequence_number, run_counter, ticks,
                                  dropped_count=int(dropped))

    def consume_market_status(self, pair: str, is_market_open: bool,
                              server_time: datetime) -> None:
        """Adapter callback for ``TcpBrokerAdapter(on_market_status=...)``."""
        self.update_market_status(MarketStatus(pair, is_market_open, server_time))

    def check_staleness(self, pair: str, *, now_mono: float | None = None) -> bool:
        _, state = self._pairs[pair]
        now = time.monotonic() if now_mono is None else now_mono
        if not math.isfinite(now):
            state.is_stale = True
            return True
        if state.staleness_threshold_s is None or state.last_tick_time is None:
            state.is_stale = True
        else:
            state.is_stale = now - state.last_tick_time > state.staleness_threshold_s
        self._prune_activity(state, now)
        return state.is_stale

    def set_spread_health(self, pair: str, *, abnormal: bool, recovering: bool) -> None:
        _, state = self._pairs[pair]
        state.is_spread_abnormal = abnormal
        state.is_recovering = recovering

    def acknowledge_stability(self, pair: str) -> None:
        _, state = self._pairs[pair]
        state.reopened_unstable = False
        state.is_recovering = False

    def update_market_status(self, status: MarketStatus) -> None:
        if status.pair not in self._pairs:
            return
        if (not isinstance(status.is_market_open, bool)
                or not isinstance(status.server_time, datetime) or status.server_time.tzinfo is None):
            raise ValueError("market status server_time must be timezone-aware")
        self._statuses[status.pair] = status
        self._pairs[status.pair][1].is_market_open = status.is_market_open

    def health(self, pair: str, *, now_mono: float | None = None) -> MarketHealthState:
        self.check_staleness(pair, now_mono=now_mono)
        return self._pairs[pair][1]

    @staticmethod
    def _prune_activity(state: MarketHealthState, now: float) -> None:
        if state.baseline_window_s is None or state.none_after_s is None:
            state.tick_activity_level = TickActivityLevel.NONE
            state._was_none = True
            return
        cutoff = now - state.baseline_window_s
        while state.ticks and state.ticks[0] < cutoff:
            state.ticks.popleft()
        idle = float("inf") if state.last_tick_time is None else now - state.last_tick_time
        if idle >= state.none_after_s:
            state.tick_activity_level = TickActivityLevel.NONE
            state._was_none = True
        else:
            rate = len(state.ticks) / state.baseline_window_s
            cutoff_rates = now - state.baseline_window_s
            while state.activity_rate_samples and state.activity_rate_samples[0][0] < cutoff_rates:
                state.activity_rate_samples.popleft()
            baseline = ([sample for _, sample in state.activity_rate_samples])
            reduced_vs_baseline = bool(baseline) and rate < (sum(baseline) / len(baseline))
            if (state.last_activity_sample_time is None or
                    now - state.last_activity_sample_time >= state.baseline_window_s):
                state.activity_rate_samples.append((now, rate))
                state.last_activity_sample_time = now
            if state.low_min_ticks_per_second is None or state.normal_min_ticks_per_second is None:
                state.tick_activity_level = TickActivityLevel.NONE
            elif reduced_vs_baseline or rate < state.low_min_ticks_per_second:
                state.tick_activity_level = TickActivityLevel.LOW
            elif rate < state.normal_min_ticks_per_second:
                state.tick_activity_level = TickActivityLevel.LOW
            else:
                state.tick_activity_level = TickActivityLevel.NORMAL
