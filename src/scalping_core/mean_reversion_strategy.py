"""Mean Reversion Scalping Strategy (§7.3).

Identifies short-term deviations from a rolling mean (Bollinger Band–style).
Pure computation — no I/O, no execution.

All thresholds are owner decisions (§19 item 1) and default to None.
When unconfigured, generate_signal() returns None.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from .broker_types import Tick
from .regime_types import (
    FeatureSnapshot, MarketRegime as RecommendationRegime, NoSignalReason,
    NoSignalReasonCode, SignalDirection as RecommendationDirection,
    SignalRecommendation, StrategyConfig, stable_signal_id, strategy_config_issue,
)
from .strategy_engine import Strategy
from .strategy_types import (
    MarketRegime,
    PricePoint,
    Signal,
    SignalDirection,
    StrategyType,
)

_ZERO = Decimal(0)


@dataclass(slots=True)
class MeanReversionConfig:
    """All parameters require explicit owner approval before activation."""

    window_size: int | None = None
    bb_period: int | None = None
    entry_sigma: Decimal | None = None
    min_strength: Decimal | None = None


class MeanReversionStrategy:
    """Per-pair mean reversion signal generator."""

    def __init__(self, config: MeanReversionConfig | None = None) -> None:
        self._config = config or MeanReversionConfig()
        self._history: deque[PricePoint] = deque(
            maxlen=self._config.window_size or 0,
        )

    @property
    def config(self) -> MeanReversionConfig:
        return self._config

    @config.setter
    def config(self, value: MeanReversionConfig) -> None:
        old_size = self._config.window_size
        self._config = value
        if value.window_size != old_size:
            self._history = deque(self._history, maxlen=value.window_size or 0)

    def update(self, point: PricePoint) -> None:
        self._history.append(point)

    def generate_signal(
        self,
        canonical_pair: str,
        regime: MarketRegime,
    ) -> Signal | None:
        if not self._is_configured():
            return None
        cfg = self._config
        if len(self._history) < cfg.bb_period:
            return None

        mids = [p.mid for p in list(self._history)[-cfg.bb_period:]]
        mean = sum(mids) / len(mids)
        stddev = self._stddev(mids, mean)

        if stddev == 0:
            return None

        latest = self._history[-1]
        deviation = latest.mid - mean
        z_score = deviation / stddev

        if cfg.entry_sigma is not None and abs(z_score) < cfg.entry_sigma:
            return None

        # Price below lower band → expect reversion up (BUY)
        # Price above upper band → expect reversion down (SELL)
        direction = SignalDirection.BUY if z_score < 0 else SignalDirection.SELL

        strength = self._compute_strength(z_score)
        if cfg.min_strength is not None and strength < cfg.min_strength:
            return None

        return Signal(
            direction=direction,
            strategy=StrategyType.MEAN_REVERSION,
            regime=regime,
            strength=strength,
            canonical_pair=canonical_pair,
            reference_price=latest.ask if direction == SignalDirection.BUY else latest.bid,
            timestamp_ms=latest.server_time_ms,
        )

    def _is_configured(self) -> bool:
        cfg = self._config
        return all(v is not None for v in (
            cfg.window_size, cfg.bb_period,
            cfg.entry_sigma, cfg.min_strength,
        ))

    @staticmethod
    def _compute_strength(z_score: Decimal) -> Decimal:
        """Strength from z-score: sigmoid-like mapping capped at 1.
        ponytail: linear clamp [1, 3] → [0, 1]; upgrade to sigmoid if needed.
        """
        z_abs = abs(z_score)
        if z_abs <= 1:
            return _ZERO
        return min((z_abs - 1) / 2, Decimal(1))

    @staticmethod
    def _stddev(values: list[Decimal], mean: Decimal) -> Decimal:
        if len(values) < 2:
            return _ZERO
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return Decimal(str(math.sqrt(float(variance))))


class MeanReversionRecommendationStrategy(Strategy):
    """Stateless Phase 4 mean-reversion evaluator for RANGING only."""

    strategy_name = "meanrev"

    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.config = config

    def evaluate(self, pair: str, tick: Tick, features: FeatureSnapshot,
                 regime: RecommendationRegime) -> SignalRecommendation | NoSignalReason:
        issue = strategy_config_issue(self.config, self.strategy_name)
        if issue is not None:
            return NoSignalReason(pair, issue, "Mean-reversion parameters are absent or invalid", features.timestamp)
        if regime is not RecommendationRegime.RANGING:
            return NoSignalReason(pair, NoSignalReasonCode.PROHIBITED_REGIME,
                                  f"Mean reversion is prohibited in {regime.value}", features.timestamp)
        if features.rolling_mean is None or features.rolling_std is None:
            return NoSignalReason(pair, NoSignalReasonCode.INSUFFICIENT_HISTORY,
                                  "Mean-reversion window is not ready", features.timestamp)
        if features.rolling_std == 0:
            return NoSignalReason(pair, NoSignalReasonCode.ZERO_VARIANCE,
                                  "Rolling price variance is zero", features.timestamp)
        z_score = features.z_score
        if z_score is None:
            return NoSignalReason(pair, NoSignalReasonCode.ZERO_VARIANCE,
                                  "Z-score is unavailable", features.timestamp)
        threshold = self.config.parameters["deviation_threshold"]
        if z_score < -threshold:
            direction = RecommendationDirection.BUY
        elif z_score > threshold:
            direction = RecommendationDirection.SELL
        else:
            return NoSignalReason(pair, NoSignalReasonCode.NO_SIGNAL_CONDITIONS,
                                  "Deviation has not reached the configured threshold", features.timestamp)
        strength = min(Decimal(1), abs(z_score) / threshold)
        return SignalRecommendation(
            pair=pair, direction=direction, strategy_name=self.strategy_name, regime=regime,
            reference_bid=tick.bid, reference_ask=tick.ask, features=features,
            strength=strength, timestamp=features.timestamp,
            signal_id=stable_signal_id(pair, features.timestamp, self.strategy_name,
                                       direction, tick.bid, tick.ask),
        )
