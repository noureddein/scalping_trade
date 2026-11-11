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

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Mapping

from .broker_types import ContractSpec, Tick, TickValidationStatus
from .market_data import spread_in_pips
from .strategy_types import (
    MarketRegime,
    PricePoint,
    Signal,
    SignalDirection,
    StrategyType,
)
from .regime_types import (
    FeatureSnapshot, MarketRegime as RecommendationRegime, NoSignalReason,
    NoSignalReasonCode, RegimeClassification, RegimeClassifierConfig,
    RegimeMap, SignalDirection as RecommendationDirection, SignalRecommendation,
    StrategyConfig, strategy_config_issue, validate_strategy_parameters,
)

_TWO = Decimal(2)
_RECOMMENDATION_NAMESPACE = uuid.UUID("491ceb43-09b2-4b94-9a2e-96834635ae64")


class Strategy(ABC):
    """Recommendation-only strategy boundary; no execution dependencies."""

    @abstractmethod
    def evaluate(
        self, pair: str, tick: Tick, features: FeatureSnapshot,
        regime: RecommendationRegime = RecommendationRegime.UNKNOWN,
    ) -> SignalRecommendation | NoSignalReason:
        raise NotImplementedError

    @staticmethod
    def validate_config(config: StrategyConfig, expected_name: str | None = None) -> bool:
        return (validate_strategy_parameters(config.strategy_name, config.parameters)
                and (expected_name is None or config.strategy_name == expected_name))


class FeatureComputer:
    """Computes a shared, past-and-current-only feature snapshot per tick."""

    def __init__(self) -> None:
        self._history: dict[str, list[Tick]] = defaultdict(list)

    def history_count(self, pair: str) -> int:
        return len(self._history.get(pair, ()))

    def compute(
        self, pair: str, tick: Tick, strategy_configs: Mapping[str, StrategyConfig],
        regime_config: RegimeClassifierConfig | None = None,
    ) -> FeatureSnapshot:
        if tick.validation_status is not TickValidationStatus.VALID:
            raise ValueError("FeatureComputer accepts only validated ticks")
        if not pair or tick.pair not in (None, pair):
            raise ValueError("tick pair does not match requested canonical pair")
        if tick.bid <= 0 or tick.ask < tick.bid or not tick.bid.is_finite() or not tick.ask.is_finite():
            raise ValueError("tick quote is invalid")
        stamp = tick.broker_timestamp
        if stamp is None or stamp.tzinfo is None:
            raise ValueError("tick broker timestamp must be timezone-aware")

        configs = {name: cfg for name, cfg in strategy_configs.items()
                   if cfg is not None and cfg.is_active}
        momentum = configs.get("momentum")
        breakout = configs.get("breakout")
        meanrev = configs.get("meanrev")
        required_history = [1]
        if momentum:
            required_history.extend((int(momentum.parameters["slow_ema_period"]),
                                     int(momentum.parameters["velocity_lookback"]) + 1))
        if breakout:
            required_history.append(int(breakout.parameters["channel_lookback"]) + 1)
        if meanrev:
            required_history.append(int(meanrev.parameters["rolling_period"]))
        if regime_config and regime_config.is_configured:
            required_history.append(regime_config.warm_up_threshold or 1)
        history = self._history[pair]
        history.append(tick)
        capacity = max(required_history)
        if len(history) > capacity:
            del history[:-capacity]

        mid = (tick.bid + tick.ask) / _TWO
        previous = history[-2] if len(history) >= 2 else None
        fast_ema = slow_ema = ema_spread = velocity = None
        if momentum:
            fast_period = int(momentum.parameters["fast_ema_period"])
            slow_period = int(momentum.parameters["slow_ema_period"])
            if len(history) >= slow_period:
                mids = [(item.bid + item.ask) / _TWO for item in history[-slow_period:]]
                fast_ema = self._ema(mids[-fast_period:])
                slow_ema = self._ema(mids)
                ema_spread = fast_ema - slow_ema
            lookback = int(momentum.parameters["velocity_lookback"])
            if len(history) > lookback:
                earlier = history[-lookback - 1]
                elapsed = (stamp - earlier.broker_timestamp).total_seconds()
                if elapsed > 0:
                    earlier_mid = (earlier.bid + earlier.ask) / _TWO
                    velocity = (mid - earlier_mid) / Decimal(str(elapsed))

        channel_high = channel_low = channel_width = None
        if breakout:
            lookback = int(breakout.parameters["channel_lookback"])
            if len(history) > lookback:
                prior = history[-lookback - 1:-1]
                channel_high = max(item.ask for item in prior)
                channel_low = min(item.bid for item in prior)
                channel_width = channel_high - channel_low

        rolling_mean = rolling_std = z_score = None
        if meanrev:
            period = int(meanrev.parameters["rolling_period"])
            if len(history) >= period:
                mids = [(item.bid + item.ask) / _TWO for item in history[-period:]]
                rolling_mean = sum(mids) / len(mids)
                rolling_std = self._stddev(mids, rolling_mean)
                if rolling_std > 0:
                    z_score = (mid - rolling_mean) / rolling_std

        volatility = None
        if regime_config and regime_config.is_configured:
            warm_up = regime_config.warm_up_threshold or 1
            if len(history) >= warm_up:
                mids = [(item.bid + item.ask) / _TWO for item in history[-warm_up:]]
                volatility = self._stddev(mids, sum(mids) / len(mids))

        previous_mid = ((previous.bid + previous.ask) / _TWO) if previous else None
        previous_spread = (previous.ask - previous.bid) if previous else None
        return FeatureSnapshot(
            pair=pair, timestamp=stamp.astimezone(timezone.utc), mid_price=mid,
            bid=tick.bid, ask=tick.ask, fast_ema=fast_ema, slow_ema=slow_ema,
            ema_spread=ema_spread, price_velocity=velocity,
            channel_high=channel_high, channel_low=channel_low, channel_width=channel_width,
            rolling_mean=rolling_mean, rolling_std=rolling_std, z_score=z_score,
            volatility=volatility, previous_mid_price=previous_mid,
            previous_spread=previous_spread,
        )

    @staticmethod
    def _ema(values: list[Decimal]) -> Decimal:
        alpha = Decimal(2) / Decimal(len(values) + 1)
        result = values[0]
        for value in values[1:]:
            result = alpha * value + (Decimal(1) - alpha) * result
        return result

    @staticmethod
    def _stddev(values: list[Decimal], mean: Decimal) -> Decimal:
        if len(values) < 2:
            return Decimal(0)
        variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values))
        return Decimal(str(math.sqrt(float(variance))))


class RegimeClassifier:
    """Priority-ordered classifier using only the current feature snapshot."""

    def __init__(self, config: RegimeClassifierConfig | None) -> None:
        self._config = config or RegimeClassifierConfig()

    def classify(
        self, features: FeatureSnapshot, *, history_count: int,
        degraded: bool = False, stale: bool = False, has_gap: bool = False,
        crossed: bool = False,
    ) -> RegimeClassification:
        cfg = self._config
        evidence: dict[str, Decimal | int | bool | None] = {
            "volatility": features.volatility,
            "price_velocity": features.price_velocity,
            "ema_spread": features.ema_spread,
            "channel_width": features.channel_width,
            "history_count": history_count,
            "config_valid": cfg.is_configured,
            "degraded": degraded,
            "stale": stale,
            "has_gap": has_gap,
            "crossed": crossed,
        }
        if degraded or stale or has_gap or crossed:
            return RegimeClassification(features.pair, RecommendationRegime.UNSTABLE,
                                        evidence, features.timestamp, False)
        if not cfg.is_configured:
            return RegimeClassification(features.pair, RecommendationRegime.UNKNOWN,
                                        evidence, features.timestamp, False)
        if history_count < cfg.warm_up_threshold or features.volatility is None:
            return RegimeClassification(features.pair, RecommendationRegime.UNKNOWN,
                                        evidence, features.timestamp, False)
        if features.volatility > cfg.volatility_baseline:
            regime = RecommendationRegime.HIGH_VOLATILITY
        elif (features.channel_high is not None and features.channel_low is not None
              and (features.mid_price > features.channel_high + cfg.breakout_exceedance
                   or features.mid_price < features.channel_low - cfg.breakout_exceedance)):
            regime = RecommendationRegime.BREAKOUT
        elif (features.price_velocity is not None and features.ema_spread is not None
              and abs(features.price_velocity) > cfg.trending_min_slope
              and abs(features.ema_spread) > cfg.trending_ema_alignment_min
              and features.price_velocity * features.ema_spread > 0):
            regime = RecommendationRegime.TRENDING
        elif features.volatility < cfg.low_volatility_ceiling:
            regime = RecommendationRegime.LOW_VOLATILITY
        elif (features.price_velocity is not None and features.channel_width is not None
              and abs(features.price_velocity) <= cfg.trending_min_slope
              and features.channel_width <= cfg.volatility_baseline):
            regime = RecommendationRegime.RANGING
        else:
            regime = RecommendationRegime.UNKNOWN
        return RegimeClassification(features.pair, regime, evidence,
                                    features.timestamp, regime is not RecommendationRegime.UNKNOWN)

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
        from .market_regime import RegimeDetector
        from .momentum_strategy import MomentumStrategy
        from .breakout_strategy import BreakoutStrategy
        from .mean_reversion_strategy import MeanReversionStrategy

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
        self._pipelines: dict[str, StrategyPipeline] = {}

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

    def register_pipeline(
        self, canonical_pair: str, classifier_config: RegimeClassifierConfig | None,
        strategy_configs: Mapping[str, StrategyConfig] | None = None,
        regime_map: RegimeMap | None = None,
    ) -> StrategyPipeline:
        pipeline = StrategyPipeline(canonical_pair, classifier_config,
                                    strategy_configs or {}, regime_map)
        self._pipelines[canonical_pair] = pipeline
        return pipeline

    def process_validated_tick(
        self, canonical_pair: str, tick: Tick, *, stale: bool = False,
        has_gap: bool = False, degraded: bool = False,
    ) -> SignalRecommendation | NoSignalReason | None:
        pipeline = self._pipelines.get(canonical_pair)
        if pipeline is None:
            return None
        return pipeline.on_tick(tick, stale=stale, has_gap=has_gap, degraded=degraded)

    def on_tick(self, canonical_pair: str, tick: Tick, contract: ContractSpec) -> Signal | None:
        engine = self._pairs.get(canonical_pair)
        if engine is None:
            return None
        return engine.on_tick(tick, contract)

    @property
    def pairs(self) -> list[str]:
        return sorted(set(self._pairs) | set(self._pipelines))


class StrategyPipeline:
    """Phase 4 validated-tick → features → regime → one strategy → quality gate."""

    def __init__(
        self, canonical_pair: str, classifier_config: RegimeClassifierConfig | None,
        strategy_configs: Mapping[str, StrategyConfig], regime_map: RegimeMap | None,
    ) -> None:
        if not canonical_pair:
            raise ValueError("canonical pair is required")
        self.pair = canonical_pair
        self.strategy_configs = dict(strategy_configs)
        self.regime_map = regime_map
        self.features = FeatureComputer()
        self.classifier = RegimeClassifier(classifier_config)
        from .momentum_strategy import MomentumRecommendationStrategy
        from .breakout_strategy import BreakoutRecommendationStrategy
        from .mean_reversion_strategy import MeanReversionRecommendationStrategy
        self.strategies: dict[str, Strategy] = {
            "momentum": MomentumRecommendationStrategy(self.strategy_configs.get("momentum")),
            "breakout": BreakoutRecommendationStrategy(self.strategy_configs.get("breakout")),
            "meanrev": MeanReversionRecommendationStrategy(self.strategy_configs.get("meanrev")),
        }
        self.last_classification: RegimeClassification | None = None
        self.last_reason: NoSignalReason | None = None
        self.last_recommendation: SignalRecommendation | None = None

    def on_tick(
        self, tick: Tick, *, stale: bool = False, has_gap: bool = False,
        degraded: bool = False,
    ) -> SignalRecommendation | NoSignalReason:
        stamp = tick.broker_timestamp
        if stamp is None:
            stamp = datetime.fromtimestamp(tick.server_time_ms / 1000, tz=timezone.utc)
        stamp = stamp.astimezone(timezone.utc)
        if tick.pair not in (None, self.pair) or tick.validation_status is not TickValidationStatus.VALID:
            return self._no_signal(NoSignalReasonCode.DEGRADED_DATA,
                                   "Pipeline requires a validated tick mapped to this canonical pair", stamp)
        try:
            feature_snapshot = self.features.compute(
                self.pair, tick, self.strategy_configs, self.classifier._config,
            )
        except (ValueError, ArithmeticError):
            return self._no_signal(NoSignalReasonCode.DEGRADED_DATA,
                                   "Tick did not produce a valid feature snapshot", stamp)
        classification = self.classifier.classify(
            feature_snapshot, history_count=self.features.history_count(self.pair),
            stale=stale, has_gap=has_gap, degraded=degraded,
        )
        self.last_classification = classification
        if classification.regime is RecommendationRegime.UNSTABLE:
            return self._no_signal(NoSignalReasonCode.UNSTABLE_REGIME,
                                   "Market data is stale, degraded, or gapped", stamp)
        if classification.regime is RecommendationRegime.UNKNOWN:
            reason = (NoSignalReasonCode.INVALID_CONFIG
                      if not self.classifier._config.is_configured
                      else NoSignalReasonCode.INSUFFICIENT_HISTORY
                      if self.features.history_count(self.pair) < (self.classifier._config.warm_up_threshold or 1)
                      else NoSignalReasonCode.NO_SIGNAL_CONDITIONS)
            return self._no_signal(reason, "Regime is unknown; no strategy will be routed", stamp)
        if self.regime_map is None or not self.regime_map.is_configured:
            return self._no_signal(NoSignalReasonCode.NO_REGIME_MAP,
                                   "No owner-configured regime map is active", stamp)
        if classification.regime not in self.regime_map.mappings:
            return self._no_signal(NoSignalReasonCode.REGIME_NOT_MAPPED,
                                   "The current regime has no strategy mapping", stamp)
        strategy_name = self.regime_map.mappings[classification.regime]
        strategy = self.strategies.get(strategy_name)
        if strategy is None:
            return self._no_signal(NoSignalReasonCode.INVALID_CONFIG,
                                   "Regime map selects an unknown strategy", stamp)
        result = strategy.evaluate(self.pair, tick, feature_snapshot, classification.regime)
        if isinstance(result, NoSignalReason):
            self.last_reason = result
            self.last_recommendation = None
            return result
        config = self.strategy_configs.get(strategy_name)
        threshold = config.parameters.get("signal_quality_threshold") if config else None
        if not isinstance(threshold, Decimal) or not threshold.is_finite() or threshold <= 0:
            return self._no_signal(NoSignalReasonCode.MISSING_PARAMS,
                                   "Signal quality threshold is missing or invalid", stamp)
        if result.strength < threshold:
            return self._no_signal(NoSignalReasonCode.BELOW_QUALITY_THRESHOLD,
                                   "Recommendation strength is below its configured threshold", stamp)
        if (result.pair != self.pair or result.features != feature_snapshot
                or result.reference_bid != tick.bid or result.reference_ask != tick.ask
                or result.regime is not classification.regime):
            return self._no_signal(NoSignalReasonCode.INVALID_CONFIG,
                                   "Recommendation payload does not match the decision tick", stamp)
        self.last_reason = None
        self.last_recommendation = result
        return result

    def consume_valid_tick(self, tick: Tick) -> SignalRecommendation | NoSignalReason:
        """Callback-compatible entry point for the Phase 3 market-data layer."""
        return self.on_tick(tick)

    def _no_signal(self, code: NoSignalReasonCode, detail: str,
                   timestamp: datetime) -> NoSignalReason:
        reason = NoSignalReason(self.pair, code, detail, timestamp)
        self.last_reason = reason
        self.last_recommendation = None
        return reason
