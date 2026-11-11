"""Strategy Engine orchestrator (§7, §8 steps 6–8).

Routes market regime → strategy selection → signal generation.
Read-only: produces Signal recommendations but never executes orders.

DEFAULT_REGIME_MAP is a reference mapping (§7.4), NOT active by default.
PairStrategyConfig.regime_map defaults to None; when None, the engine
returns no signal regardless of detected regime.  The owner must explicitly
approve and supply a regime_map before strategy routing activates.

This mapping is a starting point, not a claim of superiority (§7.5).
Each strategy must be backtested independently before combination.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .broker_types import ContractSpec, Tick
from .market_data import spread_in_pips
from .strategy_types import (
    MarketRegime,
    PricePoint,
    Signal,
    SignalDirection,
    StrategyType,
)
from .market_regime import RegimeConfig, RegimeDetector
from .momentum_strategy import MomentumConfig, MomentumStrategy
from .breakout_strategy import BreakoutConfig, BreakoutStrategy
from .mean_reversion_strategy import MeanReversionConfig, MeanReversionStrategy

_TWO = Decimal(2)

# Regime → strategy type mapping. None = no trade.
DEFAULT_REGIME_MAP: dict[MarketRegime, StrategyType | None] = {
    MarketRegime.TRENDING: StrategyType.MOMENTUM,
    MarketRegime.RANGING: StrategyType.MEAN_REVERSION,
    MarketRegime.BREAKOUT: StrategyType.BREAKOUT,
    MarketRegime.HIGH_VOLATILITY: None,
    MarketRegime.LOW_VOLATILITY: StrategyType.MEAN_REVERSION,
    MarketRegime.UNSTABLE: None,
}


@dataclass(slots=True)
class PairStrategyConfig:
    """Per-pair strategy configuration bundle."""
    regime: RegimeConfig | None = None
    momentum: MomentumConfig | None = None
    breakout: BreakoutConfig | None = None
    mean_reversion: MeanReversionConfig | None = None
    regime_map: dict[MarketRegime, StrategyType | None] | None = None


class PairStrategyEngine:
    """Per-pair strategy engine. Owns regime detector + all three strategies."""

    def __init__(self, canonical_pair: str, config: PairStrategyConfig | None = None) -> None:
        self._pair = canonical_pair
        cfg = config or PairStrategyConfig()
        self._regime_detector = RegimeDetector(cfg.regime)
        self._momentum = MomentumStrategy(cfg.momentum)
        self._breakout = BreakoutStrategy(cfg.breakout)
        self._mean_reversion = MeanReversionStrategy(cfg.mean_reversion)
        self._regime_map = cfg.regime_map
        self._last_regime: MarketRegime | None = None
        self._last_signal: Signal | None = None

    @property
    def canonical_pair(self) -> str:
        return self._pair

    @property
    def last_regime(self) -> MarketRegime | None:
        return self._last_regime

    @property
    def last_signal(self) -> Signal | None:
        return self._last_signal

    def on_tick(self, tick: Tick, contract: ContractSpec) -> Signal | None:
        """Process a validated tick and return a signal if conditions are met.

        Returns None when: regime unconfigured, no strategy for this regime,
        strategy thresholds unconfigured, or signal too weak.
        """
        point = PricePoint(
            mid=(tick.bid + tick.ask) / _TWO,
            bid=tick.bid,
            ask=tick.ask,
            server_time_ms=tick.server_time_ms,
            recv_time_mono=tick.recv_time_mono,
        )

        regime = self._regime_detector.update(point)
        self._last_regime = regime
        if regime is None:
            self._last_signal = None
            return None

        self._momentum.update(point)
        self._breakout.update(point)
        self._mean_reversion.update(point)

        if self._regime_map is None:
            self._last_signal = None
            return None

        strategy_type = self._regime_map.get(regime)
        if strategy_type is None:
            self._last_signal = None
            return None

        signal = self._dispatch(strategy_type, regime)
        self._last_signal = signal
        return signal

    def _dispatch(self, strategy_type: StrategyType, regime: MarketRegime) -> Signal | None:
        if strategy_type == StrategyType.MOMENTUM:
            return self._momentum.generate_signal(self._pair, regime)
        if strategy_type == StrategyType.BREAKOUT:
            return self._breakout.generate_signal(self._pair, regime)
        if strategy_type == StrategyType.MEAN_REVERSION:
            return self._mean_reversion.generate_signal(self._pair, regime)
        return None


class StrategyEngine:
    """Multi-pair strategy engine. Thin router to per-pair engines."""

    def __init__(self) -> None:
        self._pairs: dict[str, PairStrategyEngine] = {}

    def register_pair(
        self, canonical_pair: str, config: PairStrategyConfig | None = None,
    ) -> PairStrategyEngine:
        engine = PairStrategyEngine(canonical_pair, config)
        self._pairs[canonical_pair] = engine
        return engine

    def remove_pair(self, canonical_pair: str) -> None:
        self._pairs.pop(canonical_pair, None)

    def get_pair(self, canonical_pair: str) -> PairStrategyEngine | None:
        return self._pairs.get(canonical_pair)

    def on_tick(self, canonical_pair: str, tick: Tick, contract: ContractSpec) -> Signal | None:
        engine = self._pairs.get(canonical_pair)
        if engine is None:
            return None
        return engine.on_tick(tick, contract)

    @property
    def pairs(self) -> list[str]:
        return list(self._pairs)
