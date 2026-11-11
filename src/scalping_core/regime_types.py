"""Contracts for the Phase 4 strategy recommendation pipeline.

These values are deterministic, in-memory diagnostics. None of them imply
an order, executable price, or owner approval for the associated strategy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid5

from .broker_types import SpreadTrend


class MarketRegime(str, Enum):
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    BREAKOUT = "BREAKOUT"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    UNSTABLE = "UNSTABLE"
    UNKNOWN = "UNKNOWN"


class SignalDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class NoSignalReasonCode(str, Enum):
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    DEGRADED_DATA = "DEGRADED_DATA"
    UNSTABLE_REGIME = "UNSTABLE_REGIME"
    NO_REGIME_MAP = "NO_REGIME_MAP"
    REGIME_NOT_MAPPED = "REGIME_NOT_MAPPED"
    STRATEGY_INACTIVE = "STRATEGY_INACTIVE"
    MISSING_PARAMS = "MISSING_PARAMS"
    INVALID_CONFIG = "INVALID_CONFIG"
    BELOW_QUALITY_THRESHOLD = "BELOW_QUALITY_THRESHOLD"
    NO_SIGNAL_CONDITIONS = "NO_SIGNAL_CONDITIONS"
    PROHIBITED_REGIME = "PROHIBITED_REGIME"
    ZERO_VARIANCE = "ZERO_VARIANCE"
    SPREAD_ONLY_BREAKOUT = "SPREAD_ONLY_BREAKOUT"
    CHANNEL_TOO_NARROW = "CHANNEL_TOO_NARROW"


@dataclass(frozen=True, slots=True)
class RegimeClassification:
    pair: str
    regime: MarketRegime
    confidence_features: dict[str, Decimal | int | bool | None]
    timestamp: datetime
    is_valid: bool

    def __post_init__(self) -> None:
        if not self.pair or self.timestamp.tzinfo is None:
            raise ValueError("classification needs a pair and aware timestamp")
        if self.regime in (MarketRegime.UNKNOWN, MarketRegime.UNSTABLE) and self.is_valid:
            raise ValueError("UNKNOWN and UNSTABLE classifications cannot be valid")


@dataclass(frozen=True, slots=True)
class RegimeMap:
    mappings: dict[MarketRegime, str]
    is_configured: bool = False


_REQUIRED_PARAMETERS: dict[str, dict[str, type | str]] = {
    "momentum": {
        "fast_ema_period": "positive_int", "slow_ema_period": "positive_int",
        "min_ema_spread": Decimal, "min_velocity": Decimal,
        "velocity_lookback": "positive_int", "signal_quality_threshold": Decimal,
    },
    "breakout": {
        "channel_lookback": "positive_int", "min_channel_width": Decimal,
        "breakout_margin": Decimal, "signal_quality_threshold": Decimal,
    },
    "meanrev": {
        "rolling_period": "positive_int", "deviation_threshold": Decimal,
        "signal_quality_threshold": Decimal,
    },
}


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    strategy_name: str
    parameters: dict[str, object]

    @property
    def is_active(self) -> bool:
        return validate_strategy_parameters(self.strategy_name, self.parameters)


def validate_strategy_parameters(strategy_name: str, parameters: dict[str, object]) -> bool:
    required = _REQUIRED_PARAMETERS.get(strategy_name)
    if required is None or not isinstance(parameters, dict):
        return False
    for name, expected in required.items():
        value = parameters.get(name)
        if expected == "positive_int":
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                return False
        elif expected is Decimal:
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                return False
    if strategy_name == "momentum":
        if parameters["fast_ema_period"] >= parameters["slow_ema_period"]:
            return False
    if parameters["signal_quality_threshold"] <= 0:
        return False
    return True


def strategy_config_issue(config: StrategyConfig | None, expected_name: str) -> NoSignalReasonCode | None:
    """Return the fail-closed reason for a strategy config, or None if valid."""
    if config is None or (config.strategy_name == expected_name and not config.parameters):
        return NoSignalReasonCode.STRATEGY_INACTIVE
    if config.strategy_name != expected_name:
        return NoSignalReasonCode.INVALID_CONFIG
    required = _REQUIRED_PARAMETERS.get(expected_name)
    if required is None:
        return NoSignalReasonCode.INVALID_CONFIG
    if any(name not in config.parameters for name in required):
        return NoSignalReasonCode.MISSING_PARAMS
    if not validate_strategy_parameters(config.strategy_name, config.parameters):
        return NoSignalReasonCode.INVALID_CONFIG
    return None


def stable_signal_id(pair: str, timestamp: datetime, strategy_name: str,
                     direction: SignalDirection, bid: Decimal, ask: Decimal) -> str:
    """Create a UUID stable for identical recommendation inputs."""
    name = f"{pair}|{timestamp.isoformat()}|{strategy_name}|{direction.value}|{bid}|{ask}"
    return str(uuid5(UUID("491ceb43-09b2-4b94-9a2e-96834635ae64"), name))


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    pair: str
    timestamp: datetime
    mid_price: Decimal
    bid: Decimal
    ask: Decimal
    fast_ema: Decimal | None = None
    slow_ema: Decimal | None = None
    ema_spread: Decimal | None = None
    price_velocity: Decimal | None = None
    channel_high: Decimal | None = None
    channel_low: Decimal | None = None
    channel_width: Decimal | None = None
    rolling_mean: Decimal | None = None
    rolling_std: Decimal | None = None
    z_score: Decimal | None = None
    volatility: Decimal | None = None
    previous_mid_price: Decimal | None = None
    previous_spread: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.pair or self.timestamp.tzinfo is None:
            raise ValueError("features need a pair and aware timestamp")
        values = (self.mid_price, self.bid, self.ask, self.fast_ema, self.slow_ema,
                  self.ema_spread, self.price_velocity, self.channel_high, self.channel_low,
                  self.channel_width, self.rolling_mean, self.rolling_std, self.z_score,
                  self.volatility, self.previous_mid_price, self.previous_spread)
        if any(value is not None and (not isinstance(value, Decimal) or not value.is_finite())
               for value in values):
            raise ValueError("feature values must be finite Decimal values")
        if self.bid <= 0 or self.ask < self.bid or self.mid_price != (self.bid + self.ask) / 2:
            raise ValueError("feature quote or mid-price is invalid")


@dataclass(frozen=True, slots=True)
class RegimeClassifierConfig:
    warm_up_threshold: int | None = None
    volatility_baseline: Decimal | None = None
    breakout_exceedance: Decimal | None = None
    trending_min_slope: Decimal | None = None
    trending_ema_alignment_min: Decimal | None = None
    low_volatility_ceiling: Decimal | None = None

    @property
    def is_configured(self) -> bool:
        values = (self.volatility_baseline, self.breakout_exceedance,
                  self.trending_min_slope, self.trending_ema_alignment_min,
                  self.low_volatility_ceiling)
        return (isinstance(self.warm_up_threshold, int)
                and not isinstance(self.warm_up_threshold, bool)
                and self.warm_up_threshold > 0
                and all(isinstance(value, Decimal) and value.is_finite() and value > 0
                        for value in values))


@dataclass(frozen=True, slots=True)
class SignalRecommendation:
    pair: str
    direction: SignalDirection
    strategy_name: str
    regime: MarketRegime
    reference_bid: Decimal
    reference_ask: Decimal
    features: FeatureSnapshot
    strength: Decimal
    timestamp: datetime
    signal_id: str

    def __post_init__(self) -> None:
        if not self.pair or self.features.pair != self.pair:
            raise ValueError("recommendation pair must match its feature snapshot")
        if self.timestamp.tzinfo is None:
            raise ValueError("recommendation timestamp must be timezone-aware")
        if (not self.reference_bid.is_finite() or not self.reference_ask.is_finite()
                or self.reference_bid <= 0 or self.reference_ask < self.reference_bid):
            raise ValueError("recommendation reference quote is invalid")
        if not self.strength.is_finite() or not Decimal(0) <= self.strength <= Decimal(1):
            raise ValueError("recommendation strength must be in [0, 1]")
        UUID(self.signal_id)


@dataclass(frozen=True, slots=True)
class NoSignalReason:
    pair: str
    reason_code: NoSignalReasonCode
    detail: str
    timestamp: datetime

    def __post_init__(self) -> None:
        if not self.pair or not self.detail or self.timestamp.tzinfo is None:
            raise ValueError("no-signal reason needs pair, detail, and aware timestamp")


__all__ = [
    "FeatureSnapshot", "MarketRegime", "NoSignalReason", "NoSignalReasonCode",
    "RegimeClassification", "RegimeClassifierConfig", "RegimeMap",
    "SignalDirection", "SignalRecommendation", "SpreadTrend", "StrategyConfig",
    "validate_strategy_parameters",
    "strategy_config_issue",
    "stable_signal_id",
]
