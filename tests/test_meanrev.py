from datetime import datetime, timezone
from decimal import Decimal as D

from scalping_core.broker_types import Tick, TickValidationStatus
from scalping_core.mean_reversion_strategy import MeanReversionRecommendationStrategy
from scalping_core.regime_types import (
    FeatureSnapshot, MarketRegime, NoSignalReason, NoSignalReasonCode,
    SignalDirection, StrategyConfig,
)


def _inputs(z="-2", std="0.0001"):
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mean = D("1.1000")
    mid = mean + D(z) * D(std)
    bid, ask = mid - D("0.0001"), mid + D("0.0001")
    tick = Tick(broker_symbol="EURUSD", pair="EURUSD", bid=bid, ask=ask,
                server_time_ms=1767225600000, recv_time_mono=1,
                broker_timestamp=stamp, validation_status=TickValidationStatus.VALID)
    features = FeatureSnapshot(
        pair="EURUSD", timestamp=stamp, mid_price=mid,
        bid=bid, ask=ask, rolling_mean=mean, rolling_std=D(std), z_score=D(z),
    )
    return tick, features


def _config():
    return StrategyConfig("meanrev", {
        "rolling_period": 20, "deviation_threshold": D("2"),
        "signal_quality_threshold": D("0.5"),
    })


def test_meanrev_buy_sell_only_in_ranging_regime():
    strategy = MeanReversionRecommendationStrategy(_config())
    tick, features = _inputs("-2.5")
    result = strategy.evaluate("EURUSD", tick, features, MarketRegime.RANGING)
    assert result.direction is SignalDirection.BUY
    tick, features = _inputs("2.5")
    result = strategy.evaluate("EURUSD", tick, features, MarketRegime.RANGING)
    assert result.direction is SignalDirection.SELL


def test_meanrev_suppresses_prohibited_regimes_and_zero_variance():
    strategy = MeanReversionRecommendationStrategy(_config())
    tick, features = _inputs()
    for regime in (MarketRegime.TRENDING, MarketRegime.BREAKOUT,
                   MarketRegime.HIGH_VOLATILITY, MarketRegime.UNSTABLE):
        result = strategy.evaluate("EURUSD", tick, features, regime)
        assert isinstance(result, NoSignalReason)
        assert result.reason_code is NoSignalReasonCode.PROHIBITED_REGIME
    tick, features = _inputs("0", "0")
    result = strategy.evaluate("EURUSD", tick, features, MarketRegime.RANGING)
    assert isinstance(result, NoSignalReason)
    assert result.reason_code is NoSignalReasonCode.ZERO_VARIANCE


def test_meanrev_inactive_and_deterministic():
    tick, features = _inputs()
    inactive = MeanReversionRecommendationStrategy(StrategyConfig("meanrev", {}))
    result = inactive.evaluate("EURUSD", tick, features, MarketRegime.RANGING)
    assert isinstance(result, NoSignalReason)
    assert result.reason_code is NoSignalReasonCode.STRATEGY_INACTIVE
    strategy = MeanReversionRecommendationStrategy(_config())
    assert strategy.evaluate("EURUSD", tick, features, MarketRegime.RANGING) == strategy.evaluate(
        "EURUSD", tick, features, MarketRegime.RANGING)
