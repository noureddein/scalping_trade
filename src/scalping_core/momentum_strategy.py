"""Momentum Scalping Strategy (§7.1).

Identifies short-term directional momentum via EMA alignment, price velocity,
and tick activity. Pure computation — no I/O, no execution.

All entry/exit thresholds are owner decisions (§19 item 1) and default to None.
When unconfigured, generate_signal() returns None — no signal, no trade.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from .broker_types import Tick
from .strategy_types import (
    MarketRegime,
    PricePoint,
    Signal,
    SignalDirection,
    StrategyType,
)
from .regime_types import (
    FeatureSnapshot, MarketRegime as RecommendationRegime, NoSignalReason,
    NoSignalReasonCode, SignalDirection as RecommendationDirection,
    SignalRecommendation, StrategyConfig, stable_signal_id, strategy_config_issue,
)
from .strategy_engine import Strategy

_ZERO = Decimal(0)


@dataclass(slots=True)
class MomentumConfig:
    """All parameters require explicit owner approval before activation."""

    window_size: int | None = None
    ema_fast_span: int | None = None
    ema_slow_span: int | None = None
    min_ema_spread: Decimal | None = None
    min_velocity: Decimal | None = None
    min_strength: Decimal | None = None


class MomentumStrategy:
    """Per-pair momentum signal generator."""

    def __init__(self, config: MomentumConfig | None = None) -> None:
        self._config = config or MomentumConfig()
        self._history: deque[PricePoint] = deque(
            maxlen=self._config.window_size or 0,
        )

    @property
    def config(self) -> MomentumConfig:
        return self._config

    @config.setter
    def config(self, value: MomentumConfig) -> None:
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
        if len(self._history) < self._config.ema_slow_span + 1:
            return None

        mids = [p.mid for p in self._history]
        ema_fast = self._ema(mids, self._config.ema_fast_span)
        ema_slow = self._ema(mids, self._config.ema_slow_span)
        ema_spread = ema_fast - ema_slow

        cfg = self._config
        if cfg.min_ema_spread is not None and abs(ema_spread) < cfg.min_ema_spread:
            return None

        velocity = self._price_velocity()
        if cfg.min_velocity is not None and abs(velocity) < cfg.min_velocity:
            return None

        strength = self._compute_strength(ema_spread, velocity)
        if cfg.min_strength is not None and strength < cfg.min_strength:
            return None

        direction = SignalDirection.BUY if ema_spread > 0 else SignalDirection.SELL
        latest = self._history[-1]

        return Signal(
            direction=direction,
            strategy=StrategyType.MOMENTUM,
            regime=regime,
            strength=strength,
            canonical_pair=canonical_pair,
            reference_price=latest.ask if direction == SignalDirection.BUY else latest.bid,
            timestamp_ms=latest.server_time_ms,
        )

    def _is_configured(self) -> bool:
        cfg = self._config
        return all(v is not None for v in (
            cfg.window_size, cfg.ema_fast_span, cfg.ema_slow_span,
            cfg.min_ema_spread, cfg.min_velocity, cfg.min_strength,
        ))

    def _price_velocity(self) -> Decimal:
        if len(self._history) < 2:
            return _ZERO
        first, last = self._history[0], self._history[-1]
        dt_s = (last.server_time_ms - first.server_time_ms) / 1000
        if dt_s <= 0:
            return _ZERO
        return (last.mid - first.mid) / Decimal(str(dt_s))

    def _compute_strength(self, ema_spread: Decimal, velocity: Decimal) -> Decimal:
        """Normalized signal strength [0, 1].

        Simple average of normalized EMA spread and velocity.
        ponytail: linear normalization; upgrade to percentile-rank if needed.
        """
        cfg = self._config
        ema_norm = min(abs(ema_spread) / cfg.min_ema_spread, Decimal(1)) if cfg.min_ema_spread else _ZERO
        vel_norm = min(abs(velocity) / cfg.min_velocity, Decimal(1)) if cfg.min_velocity else _ZERO
        return (ema_norm + vel_norm) / 2

    @staticmethod
    def _ema(values: list[Decimal], span: int) -> Decimal:
        if not values:
            return _ZERO
        alpha = Decimal(2) / (span + 1)
        ema = values[0]
        for v in values[1:]:
            ema = alpha * v + (1 - alpha) * ema
        return ema


class MomentumRecommendationStrategy(Strategy):
    """Stateless Phase 4 momentum evaluator over the shared feature contract."""

    strategy_name = "momentum"

    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.config = config

    def evaluate(self, pair: str, tick: Tick, features: FeatureSnapshot,
                 regime: RecommendationRegime) -> SignalRecommendation | NoSignalReason:
        from datetime import timezone

        timestamp = features.timestamp
        issue = strategy_config_issue(self.config, self.strategy_name)
        if issue is not None:
            return NoSignalReason(pair, issue, "Momentum strategy parameters are absent or invalid", timestamp)
        if (features.ema_spread is None or features.price_velocity is None
                or features.fast_ema is None or features.slow_ema is None):
            return NoSignalReason(pair, NoSignalReasonCode.INSUFFICIENT_HISTORY,
                                  "Momentum features are not ready", timestamp)
        params = self.config.parameters
        min_spread = params["min_ema_spread"]
        min_velocity = params["min_velocity"]
        spread = features.ema_spread
        velocity = features.price_velocity
        if abs(spread) < min_spread or abs(velocity) < min_velocity or spread == 0:
            return NoSignalReason(pair, NoSignalReasonCode.NO_SIGNAL_CONDITIONS,
                                  "EMA alignment or velocity is below its configured threshold", timestamp)
        if (spread > 0) != (velocity > 0):
            return NoSignalReason(pair, NoSignalReasonCode.NO_SIGNAL_CONDITIONS,
                                  "EMA direction and velocity disagree", timestamp)
        direction = RecommendationDirection.BUY if spread > 0 else RecommendationDirection.SELL
        strength = min(Decimal(1), abs(spread) / min_spread * abs(velocity) / min_velocity)
        return SignalRecommendation(
            pair=pair, direction=direction, strategy_name=self.strategy_name, regime=regime,
            reference_bid=tick.bid, reference_ask=tick.ask, features=features,
            strength=strength, timestamp=timestamp,
            signal_id=stable_signal_id(pair, timestamp.astimezone(timezone.utc),
                                       self.strategy_name, direction, tick.bid, tick.ask),
        )
