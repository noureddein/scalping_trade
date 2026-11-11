from datetime import datetime, timezone
from decimal import Decimal as D

from scalping_core.broker_types import Tick, TickValidationStatus
from scalping_core.momentum_strategy import MomentumRecommendationStrategy
from scalping_core.regime_types import (
    FeatureSnapshot, MarketRegime, NoSignalReason, NoSignalReasonCode,
    SignalDirection, StrategyConfig,
)


def _inputs(mid="1.1001", ema_spread="0.0002", velocity="0.0001"):
    bid, ask = D(mid) - D("0.0001"), D(mid) + D("0.0001")
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tick = Tick(broker_symbol="EURUSD", pair="EURUSD", bid=bid, ask=ask,
                server_time_ms=1767225600000, recv_time_mono=1.0,
                broker_timestamp=stamp, validation_status=TickValidationStatus.VALID)
    features = FeatureSnapshot(
        pair="EURUSD", timestamp=stamp, mid_price=D(mid), bid=bid, ask=ask,
        fast_ema=D("1.1002"), slow_ema=D("1.1000"),
        ema_spread=D(ema_spread), price_velocity=D(velocity),
    )
    return tick, features


def _config():
    return StrategyConfig("momentum", {
        "fast_ema_period": 3, "slow_ema_period": 8,
        "min_ema_spread": D("0.0001"), "min_velocity": D("0.00005"),
        "velocity_lookback": 2, "signal_quality_threshold": D("0.5"),
    })


def test_momentum_buy_sell_strength_and_reference_quotes():
    strategy = MomentumRecommendationStrategy(_config())
    tick, features = _inputs()
    buy = strategy.evaluate("EURUSD", tick, features, MarketRegime.TRENDING)
    assert buy.direction is SignalDirection.BUY
    assert buy.reference_bid == tick.bid and buy.reference_ask == tick.ask
    assert buy.strength == D(1)

    tick, features = _inputs(ema_spread="-0.0002", velocity="-0.0001")
    sell = strategy.evaluate("EURUSD", tick, features, MarketRegime.TRENDING)
    assert sell.direction is SignalDirection.SELL
    assert sell.reference_bid == tick.bid and sell.reference_ask == tick.ask


def test_momentum_no_signal_when_e_m_a_equal_or_velocity_disagrees():
    strategy = MomentumRecommendationStrategy(_config())
    tick, features = _inputs(ema_spread="0", velocity="0.0001")
    result = strategy.evaluate("EURUSD", tick, features, MarketRegime.TRENDING)
    assert isinstance(result, NoSignalReason)
    assert result.reason_code is NoSignalReasonCode.NO_SIGNAL_CONDITIONS
    tick, features = _inputs(ema_spread="0.0002", velocity="-0.0001")
    assert isinstance(strategy.evaluate("EURUSD", tick, features, MarketRegime.TRENDING), NoSignalReason)


def test_momentum_inactive_and_deterministic():
    tick, features = _inputs()
    inactive = MomentumRecommendationStrategy(StrategyConfig("momentum", {}))
    result = inactive.evaluate("EURUSD", tick, features, MarketRegime.TRENDING)
    assert isinstance(result, NoSignalReason)
    assert result.reason_code is NoSignalReasonCode.STRATEGY_INACTIVE

    strategy = MomentumRecommendationStrategy(_config())
    assert strategy.evaluate("EURUSD", tick, features, MarketRegime.TRENDING) == strategy.evaluate(
        "EURUSD", tick, features, MarketRegime.TRENDING)
