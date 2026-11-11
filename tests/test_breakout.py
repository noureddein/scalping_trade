from datetime import datetime, timezone
from decimal import Decimal as D

from scalping_core.broker_types import Tick, TickValidationStatus
from scalping_core.breakout_strategy import BreakoutRecommendationStrategy
from scalping_core.regime_types import (
    FeatureSnapshot, MarketRegime, NoSignalReason, NoSignalReasonCode,
    SignalDirection, StrategyConfig,
)


def _inputs(mid, *, high="1.1000", low="1.0990", width="0.0010",
            previous_mid="1.1000", previous_spread="0.0001", spread="0.0001"):
    mid, spread = D(mid), D(spread)
    bid, ask = mid - spread / 2, mid + spread / 2
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tick = Tick(broker_symbol="EURUSD", pair="EURUSD", bid=bid, ask=ask,
                server_time_ms=1767225600000, recv_time_mono=1,
                broker_timestamp=stamp, validation_status=TickValidationStatus.VALID)
    features = FeatureSnapshot(
        pair="EURUSD", timestamp=stamp, mid_price=mid, bid=bid, ask=ask,
        channel_high=D(high), channel_low=D(low), channel_width=D(width),
        previous_mid_price=D(previous_mid), previous_spread=D(previous_spread),
    )
    return tick, features


def _config():
    return StrategyConfig("breakout", {
        "channel_lookback": 10, "min_channel_width": D("0.0005"),
        "breakout_margin": D("0.0001"), "signal_quality_threshold": D("0.5"),
    })


def test_breakout_genuine_up_and_down_and_candidate_excluded_channel():
    strategy = BreakoutRecommendationStrategy(_config())
    tick, features = _inputs("1.1003", previous_mid="1.1000")
    result = strategy.evaluate("EURUSD", tick, features, MarketRegime.BREAKOUT)
    assert result.direction is SignalDirection.BUY
    assert result.strength == D(1)
    assert result.features.channel_high == D("1.1000")

    tick, features = _inputs("1.0987", high="1.1010", low="1.0990",
                             previous_mid="1.0990")
    result = strategy.evaluate("EURUSD", tick, features, MarketRegime.BREAKOUT)
    assert result.direction is SignalDirection.SELL


def test_breakout_rejects_spread_only_jump_and_narrow_channel():
    strategy = BreakoutRecommendationStrategy(_config())
    tick, features = _inputs("1.1003", previous_mid="1.1002",
                             previous_spread="0.0001", spread="0.0003")
    result = strategy.evaluate("EURUSD", tick, features, MarketRegime.BREAKOUT)
    assert isinstance(result, NoSignalReason)
    assert result.reason_code is NoSignalReasonCode.SPREAD_ONLY_BREAKOUT

    tick, features = _inputs("1.1003", width="0.0001")
    result = strategy.evaluate("EURUSD", tick, features, MarketRegime.BREAKOUT)
    assert isinstance(result, NoSignalReason)
    assert result.reason_code is NoSignalReasonCode.CHANNEL_TOO_NARROW


def test_breakout_inactive_and_repeatable():
    tick, features = _inputs("1.1003")
    inactive = BreakoutRecommendationStrategy(StrategyConfig("breakout", {}))
    result = inactive.evaluate("EURUSD", tick, features, MarketRegime.BREAKOUT)
    assert isinstance(result, NoSignalReason)
    assert result.reason_code is NoSignalReasonCode.STRATEGY_INACTIVE
    strategy = BreakoutRecommendationStrategy(_config())
    assert strategy.evaluate("EURUSD", tick, features, MarketRegime.BREAKOUT) == strategy.evaluate(
        "EURUSD", tick, features, MarketRegime.BREAKOUT)
