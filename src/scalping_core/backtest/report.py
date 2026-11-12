"""Structured report generation (T021)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


def generate_report(
    *,
    run_result: dict[str, Any],
    no_trade_benchmark_pnl: Decimal = Decimal("0"),
    parameter_sensitivity: list[dict[str, Any]] | None = None,
    uncertainty_range: dict[str, Any] | None = None,
    slippage_sensitivity: list[dict[str, Any]] | None = None,
    leakage_check_passed: bool,
    acceptance_evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trades = run_result.get("total_trades", 0)

    if trades == 0:
        trade_count_analysis = {
            "total_trades": 0,
            "note": "zero trades — no performance claims",
        }
    else:
        trade_count_analysis = {
            "total_trades": trades,
            "net_pnl": run_result.get("net_pnl", "0"),
            "gross_pnl": run_result.get("gross_pnl", "0"),
            "total_costs": run_result.get("total_costs", "0"),
        }

    drawdown_analysis = {
        "max_drawdown": run_result.get("max_drawdown", "0"),
        "window_type": run_result.get("window_type", "full"),
    }

    report = {
        "report_id": str(uuid.uuid4()),
        "run_id": run_result["run_id"],
        "dataset_hash": run_result["dataset_hash"],
        "code_hash": run_result["code_hash"],
        "configuration_hash": run_result["configuration_hash"],
        "no_trade_benchmark_pnl": str(no_trade_benchmark_pnl),
        "parameter_sensitivity": parameter_sensitivity or [],
        "uncertainty_range": uncertainty_range or {"note": "not computed"},
        "drawdown_analysis": drawdown_analysis,
        "trade_count_analysis": trade_count_analysis,
        "slippage_sensitivity": slippage_sensitivity,
        "leakage_check_passed": leakage_check_passed,
        "meets_acceptance_criteria": None,
        "criteria_version": None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    if acceptance_evaluation:
        report["meets_acceptance_criteria"] = acceptance_evaluation.get("meets_criteria")
        report["criteria_version"] = acceptance_evaluation.get("criteria_version")
        report["authorization_note"] = acceptance_evaluation.get("authorization_note")

    return report
