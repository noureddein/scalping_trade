"""Walk-forward window management (T016)."""
from __future__ import annotations

from datetime import datetime
from typing import Any


class WalkForwardError(Exception):
    """Walk-forward configuration error."""


class WalkForwardWindow:
    """A single dev/validation/test period."""

    def __init__(self, window_type: str, start: datetime, end: datetime) -> None:
        if start >= end:
            raise WalkForwardError(f"{window_type} window: start must be before end")
        self.window_type = window_type
        self.start = start
        self.end = end

    def contains(self, ts: datetime) -> bool:
        return self.start <= ts <= self.end


class WalkForwardManager:
    """Splits dataset into non-overlapping chronological periods."""

    def __init__(
        self,
        *,
        dev_ratio: float = 0.6,
        val_ratio: float = 0.2,
        test_ratio: float = 0.2,
    ) -> None:
        if abs(dev_ratio + val_ratio + test_ratio - 1.0) > 0.01:
            raise WalkForwardError("ratios must sum to 1.0")
        self._dev_ratio = dev_ratio
        self._val_ratio = val_ratio
        self._test_ratio = test_ratio

    def split(
        self, ticks: list[dict[str, Any]]
    ) -> list[WalkForwardWindow]:
        if not ticks:
            raise WalkForwardError("no ticks to split")
        n = len(ticks)
        dev_end = int(n * self._dev_ratio)
        val_end = dev_end + int(n * self._val_ratio)

        if dev_end < 1 or val_end <= dev_end or val_end >= n:
            raise WalkForwardError("dataset too small for walk-forward split")

        windows = [
            WalkForwardWindow("development", ticks[0]["timestamp"], ticks[dev_end - 1]["timestamp"]),
            WalkForwardWindow("validation", ticks[dev_end]["timestamp"], ticks[val_end - 1]["timestamp"]),
            WalkForwardWindow("test", ticks[val_end]["timestamp"], ticks[-1]["timestamp"]),
        ]

        for i in range(1, len(windows)):
            if windows[i].start <= windows[i - 1].end:
                raise WalkForwardError("overlapping periods detected")

        return windows

    def sliding_windows(
        self, ticks: list[dict[str, Any]], *, step_ratio: float = 0.2
    ) -> list[list[WalkForwardWindow]]:
        n = len(ticks)
        step = max(1, int(n * step_ratio))
        results: list[list[WalkForwardWindow]] = []
        offset = 0
        while offset + int(n * 0.5) <= n:
            end = min(offset + n, len(ticks))
            window_ticks = ticks[offset:end]
            if len(window_ticks) < 10:
                break
            try:
                windows = self.split(window_ticks)
                results.append(windows)
            except WalkForwardError:
                break
            offset += step
        return results if results else [self.split(ticks)]
