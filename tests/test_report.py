"""Report generation tests (T023, T025)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from scalping_core.backtest.report import generate_report
from scalping_core.backtest.slippage import (
    analyze_asymmetric_slippage,
    find_break_even_friction,
    generate_slippage_grid,
)


@pytest.fixture
def run_result():
    return {
        "run_id": "run-1",
        "dataset_hash": "dh123",
        "code_hash": "ch456",
        "configuration_hash": "cf789",
        "total_trades": 10,
        "net_pnl": "5.0",
        "gross_pnl": "12.0",
        "total_costs": "7.0",
        "max_drawdown": "2.5",
        "window_type": "full",
    }


def test_report_includes_all_three_hashes(run_result):
    report = generate_report(run_result=run_result, leakage_check_passed=True)
    assert report["dataset_hash"] == "dh123"
    assert report["code_hash"] == "ch456"
    assert report["configuration_hash"] == "cf789"


def test_no_trade_benchmark_included(run_result):
    report = generate_report(
        run_result=run_result,
        no_trade_benchmark_pnl=Decimal("0"),
        leakage_check_passed=True,
    )
    assert report["no_trade_benchmark_pnl"] == "0"


def test_parameter_sensitivity_included(run_result):
    sensitivity = [{"param": "x", "values": [1, 2, 3], "results": ["1.0", "2.0", "1.5"]}]
    report = generate_report(
        run_result=run_result,
        parameter_sensitivity=sensitivity,
        leakage_check_passed=True,
    )
    assert len(report["parameter_sensitivity"]) == 1


def test_ledger_entry_fields(run_result):
    report = generate_report(run_result=run_result, leakage_check_passed=True)
    assert "run_id" in report
    assert "generated_at" in report
    assert "drawdown_analysis" in report
    assert "trade_count_analysis" in report


def test_zero_trade_no_performance_claims():
    result = {
        "run_id": "run-2",
        "dataset_hash": "d",
        "code_hash": "c",
        "configuration_hash": "cf",
        "total_trades": 0,
        "net_pnl": "0",
        "gross_pnl": "0",
        "total_costs": "0",
        "max_drawdown": "0",
        "window_type": "test",
    }
    report = generate_report(run_result=result, leakage_check_passed=True)
    assert report["trade_count_analysis"]["total_trades"] == 0
    assert "no performance claims" in report["trade_count_analysis"]["note"]


def test_acceptance_evaluation_in_report(run_result):
    evaluation = {
        "meets_criteria": True,
        "criteria_version": "1.0.0",
        "criteria_hash": "abc",
        "authorization_note": "does NOT authorize",
    }
    report = generate_report(
        run_result=run_result,
        leakage_check_passed=True,
        acceptance_evaluation=evaluation,
    )
    assert report["meets_acceptance_criteria"] is True
    assert report["criteria_version"] == "1.0.0"


# --- T025: Slippage tests ---

def test_slippage_results_labeled_scenario_analysis():
    scenarios = [
        {"label": "low", "pips": "0.5"},
        {"label": "high", "pips": "2.0"},
    ]
    grid = generate_slippage_grid(
        base_net_pnl=Decimal("5.0"),
        total_trades=10,
        scenarios=scenarios,
    )
    assert len(grid) == 2
    for entry in grid:
        assert entry["result_type"] == "scenario_analysis"


def test_break_even_labeled_diagnostic():
    result = find_break_even_friction(
        base_net_pnl=Decimal("5.0"),
        total_trades=10,
    )
    assert result["label"] == "diagnostic_estimate"
    assert "not an acceptance criterion" in result["note"]


def test_multiple_scenarios_in_grid():
    scenarios = [
        {"label": "0x", "pips": "0"},
        {"label": "0.5x", "pips": "0.5"},
        {"label": "1x", "pips": "1.0"},
        {"label": "2x", "pips": "2.0"},
    ]
    grid = generate_slippage_grid(
        base_net_pnl=Decimal("10.0"),
        total_trades=5,
        scenarios=scenarios,
    )
    assert len(grid) == 4


def test_zero_trades_break_even():
    result = find_break_even_friction(
        base_net_pnl=Decimal("0"),
        total_trades=0,
    )
    assert result["break_even_pips"] == "N/A"


# --- T030: Asymmetric slippage per session ---

def test_asymmetric_slippage_no_trades():
    result = analyze_asymmetric_slippage(
        trades=[],
        scenarios=[{"label": "low", "pips": "0.5"}],
    )
    assert result["session_analysis_available"] is False
    assert result["result_type"] == "scenario_analysis"


def test_asymmetric_slippage_insufficient_sessions():
    trades = [
        {"timestamp": "2026-01-01T10:00:00", "net_pnl": "1.0"},
        {"timestamp": "2026-01-01T10:05:00", "net_pnl": "2.0"},
    ]
    result = analyze_asymmetric_slippage(
        trades=trades,
        scenarios=[{"label": "low", "pips": "0.5"}],
    )
    assert result["session_analysis_available"] is False
    assert "insufficient session diversity" in result["note"]


def test_asymmetric_slippage_multi_session():
    trades = [
        {"timestamp": "2026-01-01T03:00:00", "net_pnl": "1.0"},
        {"timestamp": "2026-01-01T04:00:00", "net_pnl": "2.0"},
        {"timestamp": "2026-01-01T10:00:00", "net_pnl": "3.0"},
        {"timestamp": "2026-01-01T11:00:00", "net_pnl": "4.0"},
    ]
    result = analyze_asymmetric_slippage(
        trades=trades,
        scenarios=[{"label": "low", "pips": "0.5"}],
    )
    assert result["session_analysis_available"] is True
    assert result["result_type"] == "scenario_analysis"
    assert len(result["sessions"]) == 2
