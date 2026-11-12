"""Look-ahead leakage detection (T019)."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any


class LeakageDetected(Exception):
    """Future data leaked into past window."""


def check_tick_buffer(ticks: list[dict[str, Any]], current_index: int) -> bool:
    current_ts = ticks[current_index]["timestamp"]
    for i in range(current_index + 1):
        if ticks[i]["timestamp"] > current_ts:
            return False
    return True


def check_no_future_leakage(
    ticks: list[dict[str, Any]],
    strategy_fn: Any,
    *,
    injection_index: int | None = None,
) -> dict[str, Any]:
    if not ticks:
        return {"leakage_check_passed": True, "method": "empty_dataset"}

    if injection_index is None:
        injection_index = len(ticks) // 2

    check_range = min(injection_index, len(ticks))

    baseline_signals: list[Any] = []
    for i in range(check_range):
        sig = strategy_fn(ticks[i], ticks[:i + 1])
        baseline_signals.append(sig)

    future_tick = {
        "timestamp": ticks[-1]["timestamp"] + timedelta(hours=1),
        "bid": Decimal("999.99"),
        "ask": Decimal("999.99"),
        "pair": ticks[0].get("pair", ""),
    }

    contaminated = list(ticks)
    contaminated.insert(0, future_tick)

    injected_signals: list[Any] = []
    for i in range(check_range):
        sig = strategy_fn(contaminated[i + 1], contaminated[:i + 2])
        injected_signals.append(sig)

    leaked = baseline_signals != injected_signals
    return {
        "leakage_check_passed": not leaked,
        "method": "future_tick_injection",
        "injection_index": injection_index,
        "signals_changed": leaked,
    }


def check_period_boundary(
    period_a_state: dict[str, Any] | None,
    period_b_initial_state: dict[str, Any] | None,
) -> bool:
    if period_b_initial_state is None:
        return True
    if period_a_state is None:
        return True
    for key in period_a_state:
        if key in period_b_initial_state and period_a_state[key] != period_b_initial_state.get(key):
            return False
    return True
