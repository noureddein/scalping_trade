"""Execution cost accounting (T014)."""
from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from typing import Any


class CostModel:
    """Calculates execution costs for simulated trades."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._commission = Decimal(str(config["commission_per_lot"]))
        self._swap_long = Decimal(str(config["swap_long_per_lot"]))
        self._swap_short = Decimal(str(config["swap_short_per_lot"]))
        self._rollover_time = config["rollover_time"]
        if isinstance(self._rollover_time, str):
            parts = self._rollover_time.split(":")
            self._rollover_time = time(int(parts[0]), int(parts[1]))
        self._slippage_scenarios: list[dict[str, Any]] = config.get("slippage_scenarios", [])
        self._source_notes = config.get("source_notes", "")

    def calculate_costs(
        self,
        *,
        lot_size: Decimal,
        direction: str,
        entry_time: datetime,
        exit_time: datetime,
        spread_at_fill: Decimal,
    ) -> dict[str, Any]:
        commission = self._commission * lot_size

        held_overnight = self._crosses_rollover(entry_time, exit_time)
        if held_overnight:
            swap_rate = self._swap_long if direction == "BUY" else self._swap_short
            swap = swap_rate * lot_size
        else:
            swap = Decimal("0")

        known_costs = commission + swap
        # ponytail: spread is the bid/ask gap, not added separately
        total_known = known_costs

        slippage_sensitivity: list[dict[str, Any]] = []
        for scenario in self._slippage_scenarios:
            slip_pips = Decimal(str(scenario["pips"]))
            slippage_sensitivity.append({
                "label": scenario["label"],
                "pips": str(slip_pips),
                "cost": str(slip_pips * lot_size),
                "type": "scenario_analysis",
            })

        unknown_costs: list[dict[str, str]] = []
        if not self._slippage_scenarios:
            unknown_costs.append({
                "component": "slippage",
                "label": "unknown",
                "note": "no slippage scenarios configured — reported as sensitivity range, not zero",
            })

        return {
            "commission": str(commission),
            "swap": str(swap),
            "spread_at_fill": str(spread_at_fill),
            "known_costs": str(total_known),
            "slippage_sensitivity": slippage_sensitivity,
            "unknown_costs": unknown_costs,
            "held_overnight": held_overnight,
        }

    def simulate_fill(self, tick: dict[str, Any], signal: dict[str, Any]) -> dict[str, Any]:
        bid = Decimal(str(tick["bid"]))
        ask = Decimal(str(tick["ask"]))
        spread = ask - bid
        direction = signal.get("direction", "BUY")
        lot_size = Decimal(str(signal.get("lot_size", "0.01")))

        entry_price = ask if direction == "BUY" else bid
        exit_price = signal.get("exit_price")
        if exit_price is None:
            exit_price = bid if direction == "BUY" else ask
        else:
            exit_price = Decimal(str(exit_price))

        if direction == "BUY":
            gross_pnl = (exit_price - entry_price) * lot_size
        else:
            gross_pnl = (entry_price - exit_price) * lot_size

        entry_time = tick["timestamp"]
        exit_time = signal.get("exit_time", entry_time)
        costs = self.calculate_costs(
            lot_size=lot_size,
            direction=direction,
            entry_time=entry_time,
            exit_time=exit_time,
            spread_at_fill=spread,
        )
        known = Decimal(costs["known_costs"])
        net_pnl = gross_pnl - known

        return {
            "direction": direction,
            "entry_price": str(entry_price),
            "exit_price": str(exit_price),
            "lot_size": str(lot_size),
            "gross_pnl": str(gross_pnl),
            "costs": str(known),
            "net_pnl": str(net_pnl),
            "cost_breakdown": costs,
            "timestamp": entry_time.isoformat(),
        }

    def _crosses_rollover(self, entry: datetime, exit: datetime) -> bool:
        if entry.date() == exit.date():
            rt = self._rollover_time
            entry_before = entry.time() < rt
            exit_after = exit.time() >= rt
            return entry_before and exit_after
        return True
