"""Slippage sensitivity grid (T024, T030)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any


def generate_slippage_grid(
    *,
    base_net_pnl: Decimal,
    total_trades: int,
    scenarios: list[dict[str, Any]],
    lot_size: Decimal = Decimal("0.01"),
) -> list[dict[str, Any]]:
    grid: list[dict[str, Any]] = []
    for scenario in scenarios:
        pips = Decimal(str(scenario["pips"]))
        cost_per_trade = pips * lot_size
        total_slippage_cost = cost_per_trade * total_trades
        adjusted_pnl = base_net_pnl - total_slippage_cost
        grid.append({
            "label": scenario["label"],
            "pips": str(pips),
            "cost_per_trade": str(cost_per_trade),
            "total_slippage_cost": str(total_slippage_cost),
            "adjusted_net_pnl": str(adjusted_pnl),
            "result_type": "scenario_analysis",
        })
    return grid


def find_break_even_friction(
    *,
    base_net_pnl: Decimal,
    total_trades: int,
    lot_size: Decimal = Decimal("0.01"),
) -> dict[str, Any]:
    if total_trades == 0:
        return {
            "break_even_pips": "N/A",
            "label": "diagnostic_estimate",
            "note": "zero trades — break-even not applicable",
        }
    cost_per_pip_per_trade = lot_size
    total_cost_per_pip = cost_per_pip_per_trade * total_trades
    if total_cost_per_pip == 0:
        return {
            "break_even_pips": "N/A",
            "label": "diagnostic_estimate",
            "note": "zero lot size",
        }
    break_even = base_net_pnl / total_cost_per_pip
    return {
        "break_even_pips": str(break_even),
        "label": "diagnostic_estimate",
        "note": "This is a diagnostic estimate, not an acceptance criterion.",
    }


SESSION_BOUNDARIES = {
    "asian": (0, 8),
    "london": (8, 16),
    "new_york": (13, 21),
}


def _classify_session(hour: int) -> str:
    for name, (start, end) in SESSION_BOUNDARIES.items():
        if start <= hour < end:
            return name
    return "off_hours"


def analyze_asymmetric_slippage(
    trades: list[dict[str, Any]],
    *,
    scenarios: list[dict[str, Any]],
    lot_size: Decimal = Decimal("0.01"),
) -> dict[str, Any]:
    if not trades:
        return {
            "session_analysis_available": False,
            "note": "no trades — session-dependent slippage analysis not applicable",
            "result_type": "scenario_analysis",
        }

    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        ts = t.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if isinstance(ts, datetime):
            by_session[_classify_session(ts.hour)].append(t)

    sessions_with_data = {s: tl for s, tl in by_session.items() if len(tl) >= 2}
    if len(sessions_with_data) < 2:
        return {
            "session_analysis_available": False,
            "note": "insufficient session diversity — need trades in at least 2 sessions",
            "result_type": "scenario_analysis",
        }

    per_session: list[dict[str, Any]] = []
    for session_name, session_trades in sorted(sessions_with_data.items()):
        session_grid = generate_slippage_grid(
            base_net_pnl=sum(Decimal(str(t.get("net_pnl", 0))) for t in session_trades),
            total_trades=len(session_trades),
            scenarios=scenarios,
            lot_size=lot_size,
        )
        per_session.append({
            "session": session_name,
            "trade_count": len(session_trades),
            "slippage_grid": session_grid,
        })

    return {
        "session_analysis_available": True,
        "sessions": per_session,
        "result_type": "scenario_analysis",
    }
