"""Tests for spread_engine module — rolling stats, thresholds, stability."""
from decimal import Decimal

from scalping_core.broker_types import SpreadTrend
from scalping_core.fake_broker import make_contract, make_tick
from scalping_core.spread_engine import (
    SpreadCalculationError, SpreadConfig, SpreadEngine, SpreadTracker, StabilityState,
)


def test_basic_update():
    tracker = SpreadTracker()
    snap = tracker.update(Decimal("1.5"), now_mono=0.0)
    assert snap.current_pips == Decimal("1.5")
    assert snap.sample_count == 1
    assert snap.mean_pips == Decimal("1.5")


def test_rolling_stats():
    tracker = SpreadTracker(SpreadConfig(rolling_window_size=10))
    for i in range(1, 6):
        tracker.update(Decimal(str(i)), now_mono=float(i))
    snap = tracker.update(Decimal("6"), now_mono=6.0)
    assert snap.sample_count == 6
    assert snap.mean_pips == Decimal("3.5")
    assert snap.min_pips == Decimal("1")
    assert snap.max_pips == Decimal("6")


def test_median_odd():
    tracker = SpreadTracker(SpreadConfig(rolling_window_size=3))
    for v in [Decimal("1"), Decimal("3"), Decimal("5")]:
        snap = tracker.update(v, now_mono=1.0)
    assert snap.median_pips == Decimal("3")


def test_median_even():
    tracker = SpreadTracker(SpreadConfig(rolling_window_size=4))
    for v in [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")]:
        snap = tracker.update(v, now_mono=1.0)
    assert snap.median_pips == Decimal("2.5")


def test_manual_threshold_ok():
    cfg = SpreadConfig(manual_max_spread=Decimal("3.0"))
    tracker = SpreadTracker(cfg)
    snap = tracker.update(Decimal("2.0"), now_mono=0.0)
    assert snap.manual_ok


def test_manual_threshold_breach():
    cfg = SpreadConfig(manual_max_spread=Decimal("3.0"))
    tracker = SpreadTracker(cfg)
    snap = tracker.update(Decimal("4.0"), now_mono=0.0)
    assert not snap.manual_ok


def test_no_manual_threshold_fails_closed():
    tracker = SpreadTracker(SpreadConfig(manual_max_spread=None))
    snap = tracker.update(Decimal("999"), now_mono=0.0)
    assert not snap.manual_ok


def test_adaptive_threshold_unconfigured_fails_closed():
    cfg = SpreadConfig(rolling_window_size=40)
    tracker = SpreadTracker(cfg)
    for i in range(10):
        snap = tracker.update(Decimal("2"), now_mono=float(i))
    assert not snap.adaptive_ok


def test_adaptive_threshold_breach():
    cfg = SpreadConfig(adaptive_threshold=Decimal("2"), rolling_window_size=50)
    tracker = SpreadTracker(cfg)
    for i in range(40):
        tracker.update(Decimal("2.0"), now_mono=float(i))
    snap = tracker.update(Decimal("100"), now_mono=41.0)
    assert not snap.adaptive_ok


def test_stability_timer_resets_on_breach():
    cfg = _strict_config(stability_period_s=60.0)
    tracker = SpreadTracker(cfg)
    tracker.update(Decimal("4.0"), now_mono=0.0)  # breach
    tracker.update(Decimal("2.0"), now_mono=1.0)  # recovery starts
    snap = tracker.update(Decimal("2.0"), now_mono=30.0)
    assert snap.stable_seconds == 29.0

    tracker.update(Decimal("4.0"), now_mono=31.0)  # second breach
    snap = tracker.update(Decimal("2.0"), now_mono=32.0)
    assert snap.stable_seconds == 0.0


def test_stability_reaches_60s():
    cfg = _strict_config(stability_period_s=60.0)
    tracker = SpreadTracker(cfg)
    tracker.update(Decimal("4.0"), now_mono=0.0)
    tracker.update(Decimal("2.0"), now_mono=1.0)
    snap = tracker.update(Decimal("2.0"), now_mono=61.0)
    assert snap.stable_seconds >= 60.0


def test_spread_spike_doesnt_affect_existing_positions():
    """Spread protection applies to new entries only (§12.4).

    This test documents the contract: SpreadTracker produces boolean flags
    that the entry gate consumes. It never produces a close signal.
    There is no 'force_close' field in SpreadSnapshot.
    """
    cfg = SpreadConfig(manual_max_spread=Decimal("3.0"))
    tracker = SpreadTracker(cfg)
    snap = tracker.update(Decimal("50.0"), now_mono=0.0)
    assert not snap.manual_ok
    assert not hasattr(snap, "force_close")


def test_config_update():
    tracker = SpreadTracker(SpreadConfig(manual_max_spread=Decimal("5.0")))
    tracker.update(Decimal("4.0"), now_mono=0.0)
    assert tracker.config.manual_max_spread == Decimal("5.0")
    tracker.config = SpreadConfig(manual_max_spread=Decimal("2.0"))
    snap = tracker.update(Decimal("4.0"), now_mono=1.0)
    assert not snap.manual_ok


def _strict_config(**kwargs):
    values = dict(manual_max_spread=Decimal("3"), adaptive_threshold=Decimal("2.5"),
                  rolling_window_size=20, trend_lookback=2, anomaly_multiplier=Decimal("3"))
    values.update(kwargs)
    return SpreadConfig(**values)


def test_all_nine_spread_metrics_and_owner_configured_gate():
    tracker = SpreadTracker(_strict_config())
    snaps = [tracker.update(Decimal(v), now_mono=i) for i, v in enumerate(("1", "1", "2", "2", "1"))]
    snap = snaps[-1]
    assert snap.current_pips == Decimal("1")
    assert snap.mean_pips == Decimal("1.4")
    assert snap.median_pips == Decimal("1")
    assert snap.min_pips == Decimal("1")
    assert snap.max_pips == Decimal("2")
    assert snap.stddev_pips > 0
    assert Decimal(0) <= snap.percentile <= Decimal(100)
    assert snap.trend in {SpreadTrend.WIDENING.value, SpreadTrend.NARROWING.value, SpreadTrend.STABLE.value}
    assert isinstance(snap.anomaly_flag, bool)
    assert snap.entry_eligible
    assert tracker.is_entry_eligible()


def test_gate_fails_closed_when_either_threshold_or_statistics_config_missing():
    for config in (
        _strict_config(manual_max_spread=None),
        _strict_config(adaptive_threshold=None),
        _strict_config(rolling_window_size=None),
        _strict_config(trend_lookback=None),
        _strict_config(anomaly_multiplier=None),
    ):
        tracker = SpreadTracker(config)
        tracker.update(Decimal("1"), now_mono=0)
        assert not tracker.is_entry_eligible()


def test_gate_requires_both_limits_and_health():
    tracker = SpreadTracker(_strict_config())
    tracker.update(Decimal("2"), now_mono=0)
    assert not tracker.is_entry_eligible(market_stale=True)
    assert not tracker.is_entry_eligible(market_recovering=True)
    tracker.update(Decimal("4"), now_mono=1)
    assert not tracker.is_entry_eligible()


def test_manual_and_adaptive_gate_failures_are_independent():
    manual_tracker = SpreadTracker(_strict_config(manual_max_spread=Decimal("1.5")))
    assert not manual_tracker.update(Decimal("2"), now_mono=0).manual_ok
    adaptive_tracker = SpreadTracker(_strict_config(adaptive_threshold=Decimal("1.5")))
    snap = adaptive_tracker.update(Decimal("2"), now_mono=0)
    assert snap.manual_ok and not snap.adaptive_ok


def test_trend_and_anomaly_use_observed_rolling_values():
    tracker = SpreadTracker(_strict_config(trend_lookback=2))
    for i, value in enumerate(("1", "1", "1", "2")):
        snap = tracker.update(Decimal(value), now_mono=i)
    assert snap.trend == SpreadTrend.WIDENING.value
    spike = tracker.update(Decimal("10"), now_mono=4)
    assert spike.anomaly_flag


def test_stability_isolated_per_pair():
    first = SpreadTracker(_strict_config())
    second = SpreadTracker(_strict_config())
    first.update(Decimal("4"), now_mono=0)
    second.update(Decimal("1"), now_mono=0)
    first.update(Decimal("1"), now_mono=1)
    first.update(Decimal("1"), now_mono=61)
    assert first.is_entry_eligible()
    assert second.is_entry_eligible()


def test_stability_state_requires_60_seconds_after_breach_and_resets_on_spike():
    tracker = SpreadTracker(_strict_config(stability_period_s=60))
    tracker.update(Decimal("4"), now_mono=0)
    assert tracker._stability_state is StabilityState.ABNORMAL
    tracker.update(Decimal("1"), now_mono=10)
    assert tracker._stability_state is StabilityState.RECOVERING
    tracker.update(Decimal("4"), now_mono=20)
    assert tracker._stability_state is StabilityState.ABNORMAL
    tracker.update(Decimal("1"), now_mono=30)
    snap = tracker.update(Decimal("1"), now_mono=90)
    assert snap.stability_state is StabilityState.NORMAL
    assert tracker.is_entry_eligible()


def test_spread_engine_requires_fresh_spec_and_uses_current_contract_point():
    contract = make_contract("EURUSD", digits=5, point="0.00001")
    engine = SpreadEngine(contract_max_age_s=10)
    engine.update_contract_spec("EURUSD", contract, updated_at_mono=1)
    quote = engine.calculate("EURUSD", make_tick(bid="1.0", ask="1.00015"), now_mono=2)
    assert quote.spread_pips == Decimal("1.5")
    engine.update_contract_spec("EURUSD", make_contract("EURUSD", digits=4, point="0.0001"), updated_at_mono=3)
    quote = engine.calculate("EURUSD", make_tick(bid="1.0", ask="1.0002"), now_mono=3)
    assert quote.spread_pips == Decimal("2")


def test_spread_engine_rejects_unknown_or_stale_spec_and_undetermined_freshness():
    engine = SpreadEngine(contract_max_age_s=1)
    tick = make_tick()
    try:
        engine.calculate("EURUSD", tick, now_mono=1)
    except SpreadCalculationError:
        pass
    else:
        raise AssertionError("missing spec must fail closed")
    engine.update_contract_spec("EURUSD", make_contract("EURUSD"), updated_at_mono=1)
    try:
        engine.calculate("EURUSD", tick, now_mono=3)
    except SpreadCalculationError:
        pass
    else:
        raise AssertionError("stale spec must fail closed")
    unknown_freshness = SpreadEngine()
    unknown_freshness.update_contract_spec("EURUSD", make_contract("EURUSD"), updated_at_mono=1)
    try:
        unknown_freshness.calculate("EURUSD", tick, now_mono=1)
    except SpreadCalculationError:
        pass
    else:
        raise AssertionError("unknown freshness must fail closed")
