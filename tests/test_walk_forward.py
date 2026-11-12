"""Walk-forward window tests (T018)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from scalping_core.backtest.walk_forward import WalkForwardError, WalkForwardManager


def _make_ticks(n: int, start: datetime = datetime(2026, 1, 1, 10, 0)) -> list[dict]:
    return [{"timestamp": start + timedelta(seconds=i), "bid": "1.1", "ask": "1.2"} for i in range(n)]


def test_periods_strictly_chronological():
    mgr = WalkForwardManager()
    ticks = _make_ticks(100)
    windows = mgr.split(ticks)
    assert len(windows) == 3
    assert windows[0].window_type == "development"
    assert windows[1].window_type == "validation"
    assert windows[2].window_type == "test"
    assert windows[0].end < windows[1].start
    assert windows[1].end < windows[2].start


def test_no_data_leakage_across_boundaries():
    mgr = WalkForwardManager()
    ticks = _make_ticks(100)
    windows = mgr.split(ticks)
    for i in range(1, len(windows)):
        assert windows[i].start > windows[i - 1].end


def test_pipeline_state_resets_at_boundaries():
    mgr = WalkForwardManager()
    ticks = _make_ticks(100)
    windows = mgr.split(ticks)
    for w in windows:
        assert w.start < w.end


def test_multiple_sliding_windows():
    mgr = WalkForwardManager()
    ticks = _make_ticks(200)
    results = mgr.sliding_windows(ticks, step_ratio=0.3)
    assert len(results) >= 1
    for window_set in results:
        assert len(window_set) == 3


def test_refuses_too_small_dataset():
    mgr = WalkForwardManager()
    with pytest.raises(WalkForwardError):
        mgr.split(_make_ticks(2))


def test_ratios_must_sum_to_one():
    with pytest.raises(WalkForwardError, match="sum to 1.0"):
        WalkForwardManager(dev_ratio=0.5, val_ratio=0.5, test_ratio=0.5)
