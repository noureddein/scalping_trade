"""Spread Intelligence Engine (§12).

Per-pair spread tracking: rolling statistics, hybrid threshold protection,
and stability confirmation. Pure in-memory, no persistence.

Does NOT choose production threshold values — those are owner decisions (§19).
The adaptive threshold is owner-configured; this module does not derive one.

The 5,000-tick rolling window is transient: lost on restart. No persistent
history or aggregation exists; database-backed persistence is deferred.
"""
from __future__ import annotations

import math
import logging
import time
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from .broker_types import ContractSpec, SpreadSnapshot as BrokerSpreadSnapshot, SpreadTrend, Tick
from .market_data import pip_size

_ZERO = Decimal(0)
_LOGGER = logging.getLogger(__name__)


class StabilityState(str, Enum):
    NORMAL = "NORMAL"
    ABNORMAL = "ABNORMAL"
    RECOVERING = "RECOVERING"


@dataclass(slots=True)
class SpreadConfig:
    """Per-pair spread configuration. All thresholds in pips."""

    manual_max_spread: Decimal | None = None
    adaptive_threshold: Decimal | None = None  # owner-configured gate value
    stability_period_s: float = 60.0
    rolling_window_size: int | None = None
    trend_lookback: int | None = None
    anomaly_multiplier: Decimal | None = None

    def __post_init__(self) -> None:
        for name, value in (("manual_max_spread", self.manual_max_spread),
                            ("adaptive_threshold", self.adaptive_threshold),
                            ("anomaly_multiplier", self.anomaly_multiplier)):
            if value is not None and (not value.is_finite() or value <= 0):
                raise ValueError(f"{name} must be a positive finite Decimal")
        if self.rolling_window_size is not None and self.rolling_window_size <= 0:
            raise ValueError("rolling_window_size must be positive")
        if self.trend_lookback is not None and self.trend_lookback <= 0:
            raise ValueError("trend_lookback must be positive")
        if not math.isfinite(self.stability_period_s) or self.stability_period_s < 0:
            raise ValueError("stability period must be finite and non-negative")


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
    percentile: Decimal = _ZERO
    trend: str = "STABLE"
    anomaly_flag: bool = False
    entry_eligible: bool = False
    stability_state: StabilityState = StabilityState.NORMAL

    @property
    def current(self) -> Decimal:
        return self.current_pips

    @property
    def average(self) -> Decimal:
        return self.mean_pips

    @property
    def maximum(self) -> Decimal:
        return self.max_pips

    @property
    def minimum(self) -> Decimal:
        return self.min_pips

    @property
    def volatility(self) -> Decimal:
        return self.stddev_pips

    @property
    def window_size(self) -> int:
        return self.sample_count


@dataclass(frozen=True, slots=True)
class SpreadStatistics:
    pair: str
    current: Decimal
    average: Decimal
    median: Decimal
    maximum: Decimal
    minimum: Decimal
    volatility: Decimal
    percentile: Decimal
    trend: SpreadTrend
    anomaly_flag: bool
    window_size: int


class SpreadTracker:
    """Tracks spread history and threshold state for one canonical pair."""

    def __init__(self, config: SpreadConfig | None = None) -> None:
        self._config = config or SpreadConfig()
        self._history: deque[Decimal] = deque(maxlen=self._config.rolling_window_size or 1)
        self._current: Decimal = _ZERO
        self._last_breach_time: float | None = None
        self._first_ok_time: float | None = None
        self._last_update_time: float = 0.0
        self._stability_state = StabilityState.NORMAL
        self._last_gate_state: bool | None = None
        self._last_anomaly = False

    @property
    def config(self) -> SpreadConfig:
        return self._config

    @config.setter
    def config(self, value: SpreadConfig) -> None:
        old_size = self._config.rolling_window_size
        self._config = value
        if value.rolling_window_size != old_size:
            new_dq: deque[Decimal] = deque(self._history, maxlen=value.rolling_window_size or 1)
            self._history = new_dq

    def update(self, spread_pips: Decimal, now_mono: float | None = None) -> SpreadSnapshot:
        if not isinstance(spread_pips, Decimal) or not spread_pips.is_finite() or spread_pips < 0:
            raise ValueError("spread must be a finite non-negative Decimal")
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
            self._stability_state = StabilityState.ABNORMAL
        else:
            if self._stability_state is StabilityState.ABNORMAL:
                self._first_ok_time = now
                self._stability_state = StabilityState.RECOVERING
            elif self._first_ok_time is None:
                self._first_ok_time = now
            if self._first_ok_time is not None and now - self._first_ok_time >= self._config.stability_period_s:
                self._stability_state = StabilityState.NORMAL

        stable_s = self._stable_seconds(now)
        threshold_configured = self._config.adaptive_threshold is not None
        window_configured = self._config.rolling_window_size is not None
        trend = self._trend()
        anomaly_threshold = self._config.anomaly_multiplier
        anomaly_configured = anomaly_threshold is not None
        history_without_current = list(self._history)[:-1]
        if anomaly_threshold is not None and len(history_without_current) >= 2:
            prior_mean = sum(history_without_current) / len(history_without_current)
            prior_variance = sum((value - prior_mean) ** 2 for value in history_without_current) / len(history_without_current)
            prior_stddev = Decimal(str(math.sqrt(float(prior_variance))))
            anomaly_flag = self._current > prior_mean + anomaly_threshold * prior_stddev
        else:
            anomaly_flag = False
        self._last_anomaly = anomaly_flag
        eligible = (self._config.manual_max_spread is not None and threshold_configured
                    and window_configured and self._config.trend_lookback is not None
                    and anomaly_configured and manual_ok and adaptive_ok
                    and self._stability_state is StabilityState.NORMAL)
        if self._last_gate_state is not None and eligible != self._last_gate_state:
            _LOGGER.info("spread entry gate changed: eligible=%s", eligible)
        self._last_gate_state = eligible

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
            percentile=self._percentile(),
            trend=trend.value,
            anomaly_flag=anomaly_flag,
            entry_eligible=eligible,
            stability_state=self._stability_state,
        )

    def is_entry_eligible(self, *, market_stale: bool = False,
                           market_recovering: bool = False) -> bool:
        """Fail-closed entry query; never affects existing positions."""
        return (self._config.manual_max_spread is not None
                and self._config.adaptive_threshold is not None
                and self._config.rolling_window_size is not None
                and self._config.trend_lookback is not None
                and self._config.anomaly_multiplier is not None
                and self._last_gate_state is True
                and self._stability_state is StabilityState.NORMAL
                and not market_stale and not market_recovering)

    def statistics(self, pair: str) -> SpreadStatistics:
        if not self._history:
            raise ValueError("spread statistics are unavailable before the first observation")
        return SpreadStatistics(
            pair=pair, current=self._current, average=self._mean(), median=self._median(),
            maximum=max(self._history), minimum=min(self._history), volatility=self._stddev(),
            percentile=self._percentile(), trend=self._trend(),
            anomaly_flag=self._last_anomaly, window_size=len(self._history),
        )

    def reset_history(self) -> None:
        """Quarantine rolling indicators after an EA stream restart."""
        self._history.clear()
        self._current = _ZERO
        self._first_ok_time = None
        self._last_breach_time = None
        self._stability_state = StabilityState.ABNORMAL
        self._last_gate_state = False
        self._last_anomaly = False

    def _check_manual(self, spread: Decimal) -> bool:
        if self._config.manual_max_spread is None:
            return False
        return spread <= self._config.manual_max_spread

    def _adaptive_threshold(self) -> Decimal | None:
        return self._config.adaptive_threshold

    def _check_adaptive(self, spread: Decimal, threshold: Decimal | None) -> bool:
        if threshold is None:
            return False
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

    def _percentile(self) -> Decimal:
        if not self._history:
            return _ZERO
        count = sum(value <= self._current for value in self._history)
        return Decimal(count) * Decimal(100) / Decimal(len(self._history))

    def _trend(self) -> "SpreadTrend":
        lookback = self._config.trend_lookback
        if lookback is None or lookback <= 0 or len(self._history) < lookback * 2:
            return SpreadTrend.STABLE
        values = list(self._history)
        prior = sum(values[-2 * lookback:-lookback]) / lookback
        recent = sum(values[-lookback:]) / lookback
        if recent > prior:
            return SpreadTrend.WIDENING
        if recent < prior:
            return SpreadTrend.NARROWING
        return SpreadTrend.STABLE


class SpreadCalculationError(ValueError):
    """Raised when a current broker contract spec cannot be trusted."""


SpreadQuote = BrokerSpreadSnapshot


class SpreadEngine:
    """Calculates contract-aware spreads only with provably fresh specs."""

    def __init__(self, contract_max_age_s: float | None = None) -> None:
        if contract_max_age_s is not None and (not math.isfinite(contract_max_age_s) or contract_max_age_s <= 0):
            raise ValueError("contract max age must be positive")
        self._contract_max_age_s = contract_max_age_s
        self._contracts: dict[str, tuple[ContractSpec, float]] = {}
        self._fingerprints: dict[str, tuple[object, ...]] = {}

    def update_contract_spec(self, pair: str, contract: ContractSpec,
                             *, updated_at_mono: float) -> None:
        if (not pair or not contract.point.is_finite() or contract.point <= 0
                or contract.digits < 0 or not math.isfinite(updated_at_mono)):
            raise ValueError("invalid pair or contract specification")
        fingerprint = (contract.broker_symbol, contract.digits, contract.point)
        old = self._fingerprints.get(pair)
        if old is not None and old != fingerprint:
            _LOGGER.warning("contract specification changed for %s; recalculating spread", pair)
        self._contracts[pair] = (contract, updated_at_mono)
        self._fingerprints[pair] = fingerprint

    def calculate(self, pair: str, tick: Tick, *, now_mono: float) -> BrokerSpreadSnapshot:
        item = self._contracts.get(pair)
        if item is None or self._contract_max_age_s is None:
            raise SpreadCalculationError("contract spec freshness is unavailable")
        contract, updated_at = item
        if not math.isfinite(now_mono):
            raise SpreadCalculationError("current monotonic time is invalid")
        age = now_mono - updated_at
        if age < 0 or age > self._contract_max_age_s:
            raise SpreadCalculationError("contract spec is stale")
        if tick.pair not in (None, pair) or tick.broker_symbol != contract.broker_symbol:
            raise SpreadCalculationError("tick does not match contract symbol")
        size = pip_size(contract)
        if size <= 0:
            raise SpreadCalculationError("contract pip size is invalid")
        spread = (tick.ask - tick.bid) / size
        if not spread.is_finite() or spread < 0:
            raise SpreadCalculationError("tick spread is invalid")
        if tick.broker_timestamp is None:
            raise SpreadCalculationError("tick broker timestamp is missing")
        return BrokerSpreadSnapshot(pair, spread, tick.bid, tick.ask, tick.broker_timestamp)
