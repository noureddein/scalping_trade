"""Spread Intelligence Engine (§12).

Per-pair spread tracking: rolling statistics, hybrid threshold protection,
and stability confirmation. Pure in-memory, no persistence.

Does NOT choose production threshold values — those are owner decisions (§19).
Thresholds are configurable; None means "not configured / not enforced."

Adaptive thresholds are disabled by default (adaptive_sigma_multiplier=None).
The warm-up sample count (adaptive_warmup_samples) is configurable but has no
approved production value — treat it as a placeholder until owner-approved.

The 5,000-tick rolling window is transient: lost on restart. No persistent
history or aggregation exists; database-backed persistence is deferred.
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from decimal import Decimal

_ZERO = Decimal(0)


@dataclass(slots=True)
class SpreadConfig:
    """Per-pair spread configuration. All thresholds in pips."""

    manual_max_spread: Decimal | None = None
    adaptive_sigma_multiplier: Decimal | None = None  # mean + N*sigma; None = disabled (default)
    adaptive_warmup_samples: int = 30  # configurable; not an approved production value
    stability_period_s: float = 60.0
    # ponytail: fixed 5000-tick window; widen if pairs have very different tick rates
    rolling_window_size: int = 5000


@dataclass(frozen=True, slots=True)
class SpreadSnapshot:
    """Current spread state for one pair."""
    current_pips: Decimal
    mean_pips: Decimal
    median_pips: Decimal
    min_pips: Decimal
    max_pips: Decimal
    stddev_pips: Decimal
    sample_count: int
    manual_ok: bool
    adaptive_ok: bool
    stable_seconds: float
    adaptive_threshold: Decimal | None


class SpreadTracker:
    """Tracks spread history and threshold state for one canonical pair."""

    def __init__(self, config: SpreadConfig | None = None) -> None:
        self._config = config or SpreadConfig()
        self._history: deque[Decimal] = deque(maxlen=self._config.rolling_window_size)
        self._current: Decimal = _ZERO
        self._last_breach_time: float | None = None
        self._first_ok_time: float | None = None
        self._last_update_time: float = 0.0

    @property
    def config(self) -> SpreadConfig:
        return self._config

    @config.setter
    def config(self, value: SpreadConfig) -> None:
        old_size = self._config.rolling_window_size
        self._config = value
        if value.rolling_window_size != old_size:
            new_dq: deque[Decimal] = deque(self._history, maxlen=value.rolling_window_size)
            self._history = new_dq

    def update(self, spread_pips: Decimal, now_mono: float | None = None) -> SpreadSnapshot:
        now = now_mono if now_mono is not None else time.monotonic()
        self._current = spread_pips
        self._history.append(spread_pips)
        self._last_update_time = now

        manual_ok = self._check_manual(spread_pips)
        adaptive_threshold = self._adaptive_threshold()
        adaptive_ok = self._check_adaptive(spread_pips, adaptive_threshold)

        both_ok = manual_ok and adaptive_ok
        if not both_ok:
            self._last_breach_time = now
            self._first_ok_time = None
        else:
            if self._first_ok_time is None:
                self._first_ok_time = now

        stable_s = self._stable_seconds(now)

        return SpreadSnapshot(
            current_pips=spread_pips,
            mean_pips=self._mean(),
            median_pips=self._median(),
            min_pips=min(self._history) if self._history else _ZERO,
            max_pips=max(self._history) if self._history else _ZERO,
            stddev_pips=self._stddev(),
            sample_count=len(self._history),
            manual_ok=manual_ok,
            adaptive_ok=adaptive_ok,
            stable_seconds=stable_s,
            adaptive_threshold=adaptive_threshold,
        )

    def _check_manual(self, spread: Decimal) -> bool:
        if self._config.manual_max_spread is None:
            return True
        return spread <= self._config.manual_max_spread

    def _adaptive_threshold(self) -> Decimal | None:
        if self._config.adaptive_sigma_multiplier is None:
            return None
        if len(self._history) < self._config.adaptive_warmup_samples:
            return None
        return self._mean() + self._config.adaptive_sigma_multiplier * self._stddev()

    def _check_adaptive(self, spread: Decimal, threshold: Decimal | None) -> bool:
        if threshold is None:
            return True
        return spread <= threshold

    def _stable_seconds(self, now: float) -> float:
        if self._first_ok_time is None:
            return 0.0
        return now - self._first_ok_time

    def _mean(self) -> Decimal:
        if not self._history:
            return _ZERO
        return sum(self._history) / len(self._history)

    def _median(self) -> Decimal:
        if not self._history:
            return _ZERO
        # ponytail: sorted copy of deque, O(n log n). Fine for <=5000 elements.
        s = sorted(self._history)
        n = len(s)
        mid = n // 2
        if n % 2 == 0:
            return (s[mid - 1] + s[mid]) / 2
        return s[mid]

    def _stddev(self) -> Decimal:
        if len(self._history) < 2:
            return _ZERO
        mean = self._mean()
        variance = sum((x - mean) ** 2 for x in self._history) / len(self._history)
        # Decimal doesn't have sqrt; convert through float
        # ponytail: float precision fine for spread stats
        return Decimal(str(math.sqrt(float(variance))))
