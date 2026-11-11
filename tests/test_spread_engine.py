"""Tests for spread_engine module — rolling stats, thresholds, stability."""
from decimal import Decimal

from scalping_core.spread_engine import SpreadConfig, SpreadTracker


def test_basic_update():
    tracker = SpreadTracker()
    snap = tracker.update(Decimal("1.5"), now_mono=0.0)
    assert snap.current_pips == Decimal("1.5")
    assert snap.sample_count == 1
    assert snap.mean_pips == Decimal("1.5")


def test_rolling_stats():
    tracker = SpreadTracker()
    for i in range(1, 6):
        tracker.update(Decimal(str(i)), now_mono=float(i))
    snap = tracker.update(Decimal("6"), now_mono=6.0)
    assert snap.sample_count == 6
    assert snap.mean_pips == Decimal("3.5")
    assert snap.min_pips == Decimal("1")
    assert snap.max_pips == Decimal("6")


def test_median_odd():
    tracker = SpreadTracker()
    for v in [Decimal("1"), Decimal("3"), Decimal("5")]:
        snap = tracker.update(v, now_mono=1.0)
    assert snap.median_pips == Decimal("3")


def test_median_even():
    tracker = SpreadTracker()
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


def test_no_manual_threshold_always_ok():
    tracker = SpreadTracker(SpreadConfig(manual_max_spread=None))
    snap = tracker.update(Decimal("999"), now_mono=0.0)
    assert snap.manual_ok


def test_adaptive_threshold_needs_samples():
    cfg = SpreadConfig(adaptive_sigma_multiplier=Decimal("2"))
    tracker = SpreadTracker(cfg)
    for i in range(10):
        snap = tracker.update(Decimal("2"), now_mono=float(i))
    assert snap.adaptive_ok  # < 30 samples → threshold not computed → ok


def test_adaptive_threshold_breach():
    cfg = SpreadConfig(adaptive_sigma_multiplier=Decimal("2"))
    tracker = SpreadTracker(cfg)
    for i in range(40):
        tracker.update(Decimal("2.0"), now_mono=float(i))
    snap = tracker.update(Decimal("100"), now_mono=41.0)
    assert not snap.adaptive_ok


def test_stability_timer_resets_on_breach():
    cfg = SpreadConfig(manual_max_spread=Decimal("3.0"), stability_period_s=60.0)
    tracker = SpreadTracker(cfg)
    tracker.update(Decimal("2.0"), now_mono=0.0)
    snap = tracker.update(Decimal("2.0"), now_mono=30.0)
    assert snap.stable_seconds == 30.0

    tracker.update(Decimal("5.0"), now_mono=31.0)  # breach
    snap = tracker.update(Decimal("2.0"), now_mono=32.0)
    assert snap.stable_seconds < 1.0  # reset


def test_stability_reaches_60s():
    cfg = SpreadConfig(manual_max_spread=Decimal("3.0"), stability_period_s=60.0)
    tracker = SpreadTracker(cfg)
    snap = tracker.update(Decimal("2.0"), now_mono=0.0)
    snap = tracker.update(Decimal("2.0"), now_mono=60.0)
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
