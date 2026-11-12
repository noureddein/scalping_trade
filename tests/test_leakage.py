"""Leakage detection tests (T022)."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from scalping_core.backtest.leakage import check_no_future_leakage, check_tick_buffer


def _make_ticks(n: int) -> list[dict[str, Any]]:
    base = datetime(2026, 1, 1, 10, 0)
    return [
        {"timestamp": base + timedelta(seconds=i), "bid": Decimal("1.1"), "ask": Decimal("1.2"), "pair": "EURUSD"}
        for i in range(n)
    ]


def _clean_strategy(tick: dict, visible_ticks: list[dict]) -> str:
    return f"signal_{tick['timestamp']}"


def _leaky_strategy(tick: dict, visible_ticks: list[dict]) -> str:
    if any(t["bid"] == Decimal("999.99") for t in visible_ticks):
        return "LEAKED"
    return f"signal_{tick['timestamp']}"


def test_leakage_detection_catches_injected_future():
    ticks = _make_ticks(20)
    result = check_no_future_leakage(ticks, _leaky_strategy, injection_index=10)
    assert result["leakage_check_passed"] is False
    assert result["signals_changed"] is True


def test_clean_run_passes():
    ticks = _make_ticks(20)
    result = check_no_future_leakage(ticks, _clean_strategy, injection_index=10)
    assert result["leakage_check_passed"] is True
    assert result["signals_changed"] is False


def test_tick_buffer_contains_only_past():
    ticks = _make_ticks(10)
    for i in range(len(ticks)):
        assert check_tick_buffer(ticks, i) is True


def test_tick_buffer_detects_future():
    ticks = _make_ticks(5)
    ticks[2]["timestamp"] = ticks[4]["timestamp"] + timedelta(hours=1)
    assert check_tick_buffer(ticks, 3) is False
