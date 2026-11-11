"""Market Regime Detection (§7.4).

Deterministic classifier: consumes a rolling window of PricePoints and
spread state, produces a MarketRegime enum.

All classification thresholds are owner decisions (§19 item 8) and default
to None. When thresholds are unconfigured the detector returns None —
no regime classification, no signal generation downstream.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal
import math

from .strategy_types import MarketRegime, PricePoint

_ZERO = Decimal(0)


@dataclass(slots=True)
class RegimeConfig:
    """All parameters require explicit owner approval before activation."""

    window_size: int | None = None
    trend_slope_threshold: Decimal | None = None
    high_volatility_threshold: Decimal | None = None
    low_volatility_threshold: Decimal | None = None
    range_width_ratio_max: Decimal | None = None
    breakout_sigma_threshold: Decimal | None = None
    unstable_tick_gap_ms: int | None = None


class RegimeDetector:
    """Per-pair regime detector.  Stateful: maintains a rolling price window."""

    def __init__(self, config: RegimeConfig | None = None) -> None:
        self._config = config or RegimeConfig()
        self._history: deque[PricePoint] = deque(
            maxlen=self._config.window_size or 0,
        )

    @property
    def config(self) -> RegimeConfig:
        return self._config

    @config.setter
    def config(self, value: RegimeConfig) -> None:
        old_size = self._config.window_size
        self._config = value
        if value.window_size != old_size:
            self._history = deque(self._history, maxlen=value.window_size or 0)

    @property
    def sample_count(self) -> int:
        return len(self._history)

    def update(self, point: PricePoint) -> MarketRegime | None:
        self._history.append(point)
        return self.classify()

    def classify(self) -> MarketRegime | None:
        if len(self._history) < 2:
            return None
        if not self._thresholds_configured():
            return None

        mids = [p.mid for p in self._history]
        mean = sum(mids) / len(mids)
        if mean == 0:
            return None

        stddev = self._stddev(mids, mean)
        slope = self._ema_slope(mids)
        price_range = max(mids) - min(mids)
        range_ratio = price_range / mean if mean else _ZERO
        latest = mids[-1]
        deviation_sigma = abs(latest - mean) / stddev if stddev > 0 else _ZERO

        cfg = self._config

        if cfg.unstable_tick_gap_ms is not None and len(self._history) >= 2:
            gaps = [
                self._history[i].server_time_ms - self._history[i - 1].server_time_ms
                for i in range(1, len(self._history))
            ]
            if gaps and max(gaps) > cfg.unstable_tick_gap_ms:
                return MarketRegime.UNSTABLE

        if (cfg.breakout_sigma_threshold is not None
                and deviation_sigma >= cfg.breakout_sigma_threshold):
            return MarketRegime.BREAKOUT

        if (cfg.trend_slope_threshold is not None
                and abs(slope) >= cfg.trend_slope_threshold):
            return MarketRegime.TRENDING

        if (cfg.high_volatility_threshold is not None
                and stddev >= cfg.high_volatility_threshold):
            return MarketRegime.HIGH_VOLATILITY

        if (cfg.low_volatility_threshold is not None
                and stddev <= cfg.low_volatility_threshold):
            return MarketRegime.LOW_VOLATILITY

        if (cfg.range_width_ratio_max is not None
                and range_ratio <= cfg.range_width_ratio_max):
            return MarketRegime.RANGING

        return MarketRegime.RANGING

    def _thresholds_configured(self) -> bool:
        cfg = self._config
        if cfg.window_size is None:
            return False
        return any(v is not None for v in (
            cfg.trend_slope_threshold,
            cfg.high_volatility_threshold,
            cfg.low_volatility_threshold,
            cfg.range_width_ratio_max,
            cfg.breakout_sigma_threshold,
        ))

    @staticmethod
    def _stddev(values: list[Decimal], mean: Decimal) -> Decimal:
        if len(values) < 2:
            return _ZERO
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return Decimal(str(math.sqrt(float(variance))))

    @staticmethod
    def _ema_slope(values: list[Decimal], span: int = 10) -> Decimal:
        """Simple EMA slope: difference between last EMA value and the one `span` steps ago."""
        if len(values) < span + 1:
            if len(values) >= 2:
                return (values[-1] - values[0]) / len(values)
            return _ZERO
        alpha = Decimal(2) / (span + 1)
        ema = values[0]
        ema_prev = ema
        for i, v in enumerate(values[1:], 1):
            ema = alpha * v + (1 - alpha) * ema
            if i == len(values) - 1 - span:
                ema_prev = ema
        if ema_prev == 0:
            return _ZERO
        return ema - ema_prev
