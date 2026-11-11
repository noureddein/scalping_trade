"""Breakout Scalping Strategy (§7.2).

Identifies short-term breakouts from local support/resistance via rolling
high/low channels. Pure computation — no I/O, no execution.

All thresholds are owner decisions (§19 item 1) and default to None.
When unconfigured, generate_signal() returns None.
"""
from __future__ import annotations

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
class BreakoutConfig:
    """All parameters require explicit owner approval before activation."""

    window_size: int | None = None
    lookback: int | None = None
    min_breakout_distance: Decimal | None = None
    min_range_width: Decimal | None = None
    min_strength: Decimal | None = None


class BreakoutStrategy:
    """Per-pair breakout signal generator."""

    def __init__(self, config: BreakoutConfig | None = None) -> None:
        self._config = config or BreakoutConfig()
        self._history: deque[PricePoint] = deque(
            maxlen=self._config.window_size or 0,
        )

    @property
    def config(self) -> BreakoutConfig:
        return self._config

    @config.setter
    def config(self, value: BreakoutConfig) -> None:
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
        lookback = min(cfg.lookback, len(self._history) - 1)
        if lookback < 2:
            return None

        channel = list(self._history)[-lookback - 1:-1]
        highs = [p.ask for p in channel]
        lows = [p.bid for p in channel]
        ch_high = max(highs)
        ch_low = min(lows)
        ch_width = ch_high - ch_low

        if cfg.min_range_width is not None and ch_width < cfg.min_range_width:
            return None

        latest = self._history[-1]

        breakout_up = latest.ask - ch_high
        breakout_down = ch_low - latest.bid

        if cfg.min_breakout_distance is not None:
            if breakout_up >= cfg.min_breakout_distance:
                direction = SignalDirection.BUY
                distance = breakout_up
            elif breakout_down >= cfg.min_breakout_distance:
                direction = SignalDirection.SELL
                distance = breakout_down
            else:
                return None
        else:
            return None

        strength = self._compute_strength(distance, ch_width)
        if cfg.min_strength is not None and strength < cfg.min_strength:
            return None

        return Signal(
            direction=direction,
            strategy=StrategyType.BREAKOUT,
            regime=regime,
            strength=strength,
            canonical_pair=canonical_pair,
            reference_price=latest.ask if direction == SignalDirection.BUY else latest.bid,
            timestamp_ms=latest.server_time_ms,
        )

    def _is_configured(self) -> bool:
        cfg = self._config
        return all(v is not None for v in (
            cfg.window_size, cfg.lookback,
            cfg.min_breakout_distance, cfg.min_range_width, cfg.min_strength,
        ))

    @staticmethod
    def _compute_strength(distance: Decimal, ch_width: Decimal) -> Decimal:
        """Breakout strength: distance relative to channel width, capped at 1."""
        if ch_width <= 0:
            return _ZERO
        return min(distance / ch_width, Decimal(1))


class BreakoutRecommendationStrategy(Strategy):
    """Stateless Phase 4 breakout evaluator using prior-only channels."""

    strategy_name = "breakout"

    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.config = config

    def evaluate(self, pair: str, tick: Tick, features: FeatureSnapshot,
                 regime: RecommendationRegime) -> SignalRecommendation | NoSignalReason:
        issue = strategy_config_issue(self.config, self.strategy_name)
        if issue is not None:
            return NoSignalReason(pair, issue, "Breakout strategy parameters are absent or invalid", features.timestamp)
        if (features.channel_high is None or features.channel_low is None
                or features.channel_width is None):
            return NoSignalReason(pair, NoSignalReasonCode.INSUFFICIENT_HISTORY,
                                  "Prior breakout channel is not ready", features.timestamp)
        params = self.config.parameters
        if features.channel_width < params["min_channel_width"]:
            return NoSignalReason(pair, NoSignalReasonCode.CHANNEL_TOO_NARROW,
                                  "Prior channel is narrower than its configured minimum", features.timestamp)
        margin = params["breakout_margin"]
        upper_distance = features.mid_price - features.channel_high
        lower_distance = features.channel_low - features.mid_price
        direction: RecommendationDirection
        distance: Decimal
        if upper_distance > margin:
            direction, distance = RecommendationDirection.BUY, upper_distance
        elif lower_distance > margin:
            direction, distance = RecommendationDirection.SELL, lower_distance
        else:
            return NoSignalReason(pair, NoSignalReasonCode.NO_SIGNAL_CONDITIONS,
                                  "Price has not exceeded the prior channel by its margin", features.timestamp)

        spread_now = tick.ask - tick.bid
        if (features.previous_mid_price is not None and features.previous_spread is not None
                and spread_now > features.previous_spread):
            mid_move = abs(features.mid_price - features.previous_mid_price)
            spread_widening = spread_now - features.previous_spread
            if mid_move <= spread_widening / 2:
                return NoSignalReason(pair, NoSignalReasonCode.SPREAD_ONLY_BREAKOUT,
                                      "The apparent move is fully explained by spread widening", features.timestamp)
        strength = min(Decimal(1), distance / margin)
        return SignalRecommendation(
            pair=pair, direction=direction, strategy_name=self.strategy_name, regime=regime,
            reference_bid=tick.bid, reference_ask=tick.ask, features=features,
            strength=strength, timestamp=features.timestamp,
            signal_id=stable_signal_id(pair, features.timestamp, self.strategy_name,
                                       direction, tick.bid, tick.ask),
        )
