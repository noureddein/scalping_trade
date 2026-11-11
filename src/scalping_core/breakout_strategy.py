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
