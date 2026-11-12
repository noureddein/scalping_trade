"""Deterministic tick replay engine (T004, T011, T012, T017, T026)."""
from __future__ import annotations

import csv
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .dataset import (
    DataSourceGateError,
    DataSourceRegistry,
    code_hash,
    config_hash,
    file_hash,
    verify_dataset_hash,
)


class GateError(Exception):
    """A prerequisite gate is not satisfied."""


class ReplayClock:
    """Deterministic clock driven by tick timestamps — no system clock."""

    def __init__(self) -> None:
        self._now: datetime | None = None

    @property
    def now(self) -> datetime:
        if self._now is None:
            raise RuntimeError("replay clock not set")
        return self._now

    def set(self, ts: datetime) -> None:
        self._now = ts


class GateValidator:
    """Validates all prerequisites before replay begins."""

    def __init__(
        self,
        data_source_registry: DataSourceRegistry,
        cost_model_configs: dict[str, Any],
        exit_policy_version: str | None,
        acceptance_criteria: dict[str, Any] | None,
    ) -> None:
        self._sources = data_source_registry
        self._cost_models = cost_model_configs
        self._exit_policy = exit_policy_version
        self._criteria = acceptance_criteria

    def validate_replay(self, pair: str) -> list[str]:
        errors: list[str] = []
        try:
            self._sources.require(pair)
        except DataSourceGateError as e:
            errors.append(str(e))
        if pair not in self._cost_models:
            errors.append(f"no cost model config for {pair}")
        if not self._exit_policy:
            errors.append("exit policy not approved (§19#18)")
        return errors

    def validate_strategy_evaluation(self, pair: str) -> list[str]:
        errors = self.validate_replay(pair)
        if self._criteria is None:
            errors.append("no acceptance criteria defined (FR-012)")
        return errors


def _load_ticks(file_path: Path) -> list[dict[str, Any]]:
    ticks: list[dict[str, Any]] = []
    with open(file_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticks.append({
                "timestamp": datetime.fromisoformat(row["timestamp"]),
                "bid": Decimal(row["bid"]),
                "ask": Decimal(row["ask"]),
                "pair": row.get("pair", ""),
            })
    ticks.sort(key=lambda t: t["timestamp"])
    return ticks


class ReplayEngine:
    """Deterministic replay through Phase 3–5 pipeline."""

    def __init__(
        self,
        *,
        gate_validator: GateValidator,
        spread_engine: Any = None,
        strategy_engine: Any = None,
        risk_gate: Any = None,
        cost_model: Any = None,
    ) -> None:
        self._gates = gate_validator
        self._spread = spread_engine
        self._strategy = strategy_engine
        self._risk = risk_gate
        self._cost_model = cost_model
        self.clock = ReplayClock()

    def replay(
        self,
        *,
        dataset_path: Path,
        dataset_hash_expected: str,
        pair: str,
        strategy_name: str,
        configuration: dict[str, Any],
        exit_policy_version: str,
        code_module_paths: list[Path] | None = None,
        window_type: str = "full",
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> dict[str, Any]:
        errors = self._gates.validate_replay(pair)
        if errors:
            raise GateError("; ".join(errors))

        verify_dataset_hash(dataset_path, dataset_hash_expected)

        d_hash = dataset_hash_expected
        c_hash = config_hash(configuration)
        co_hash = code_hash(code_module_paths) if code_module_paths else "no-code-modules"

        ticks = _load_ticks(dataset_path)

        if window_start and window_end:
            ticks = [t for t in ticks if window_start <= t["timestamp"] <= window_end]

        trades: list[dict[str, Any]] = []
        gross_pnl = Decimal("0")
        total_costs = Decimal("0")
        max_drawdown = Decimal("0")
        peak_pnl = Decimal("0")
        running_pnl = Decimal("0")
        quality_flags: list[dict[str, str]] = []
        lookback_ticks: list[dict[str, Any]] = []
        insufficient_history = False

        for i, tick in enumerate(ticks):
            self.clock.set(tick["timestamp"])

            if i > 0:
                gap = (tick["timestamp"] - ticks[i - 1]["timestamp"]).total_seconds()
                if gap > 60.0:
                    quality_flags.append({
                        "type": "missing_interval",
                        "at": tick["timestamp"].isoformat(),
                        "gap_seconds": str(gap),
                    })
                    lookback_window = configuration.get("lookback_window", 100)
                    if len(lookback_ticks) < lookback_window:
                        insufficient_history = True

            lookback_ticks.append(tick)

            spread_result = None
            if self._spread:
                spread_result = self._spread.feed(tick)

            signal = None
            if self._strategy and not insufficient_history:
                signal = self._strategy.evaluate(tick, spread_result)

            if insufficient_history and len(lookback_ticks) >= configuration.get("lookback_window", 100):
                insufficient_history = False

            if signal and self._risk:
                approved = self._risk.check(signal)
                if approved and self._cost_model:
                    trade = self._cost_model.simulate_fill(tick, signal)
                    if trade:
                        trades.append(trade)
                        trade_pnl = Decimal(str(trade.get("net_pnl", 0)))
                        gross_pnl += Decimal(str(trade.get("gross_pnl", 0)))
                        total_costs += Decimal(str(trade.get("costs", 0)))
                        running_pnl += trade_pnl
                        if running_pnl > peak_pnl:
                            peak_pnl = running_pnl
                        dd = peak_pnl - running_pnl
                        if dd > max_drawdown:
                            max_drawdown = dd

        net_pnl = gross_pnl - total_costs
        actual_start = ticks[0]["timestamp"] if ticks else (window_start or datetime.now(timezone.utc))
        actual_end = ticks[-1]["timestamp"] if ticks else (window_end or datetime.now(timezone.utc))

        return {
            "run_id": str(uuid.uuid4()),
            "dataset_hash": d_hash,
            "code_hash": co_hash,
            "configuration_hash": c_hash,
            "strategy_name": strategy_name,
            "exit_policy_version": exit_policy_version,
            "window_type": window_type,
            "window_start": actual_start.isoformat(),
            "window_end": actual_end.isoformat(),
            "total_trades": len(trades),
            "net_pnl": str(net_pnl),
            "gross_pnl": str(gross_pnl),
            "total_costs": str(total_costs),
            "max_drawdown": str(max_drawdown),
            "trades": trades,
            "quality_flags": quality_flags,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
