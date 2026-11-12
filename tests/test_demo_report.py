"""Tests for Demo forward test report (Phase 8)."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from scalping_core.demo.report import ForwardTestReport, generate_report

_SESSION = uuid.uuid4()


def _sample_trades(n=20, *, pnl_each="1.50"):
    return [
        {
            "pnl": pnl_each,
            "gross_pnl": "2.00",
            "spread_cost": "0.30",
            "commission": "0.07",
            "swap": "0.00",
            "duration_seconds": 45,
            "is_win": Decimal(pnl_each) > 0,
        }
        for _ in range(n)
    ]


def _sample_discrepancies(n=5, *, slippage="0.5"):
    return [{"slippage_pips": slippage} for _ in range(n)]


class TestReportDisclaimers:
    def test_always_includes_no_live_trading_disclaimer(self):
        report = generate_report(
            session_id=_SESSION,
            trades=_sample_trades(50),
            discrepancies=[],
            sample_threshold=30,
        )
        assert "These results do not authorize live trading." in report.statistical_warnings

    def test_insufficient_sample_warning_for_small_sample(self):
        report = generate_report(
            session_id=_SESSION,
            trades=_sample_trades(5),
            discrepancies=[],
            sample_threshold=30,
        )
        assert "Insufficient sample size for statistical inference." in report.statistical_warnings
        assert report.sample_sufficient is False

    def test_sufficient_sample_has_no_insufficient_warning(self):
        report = generate_report(
            session_id=_SESSION,
            trades=_sample_trades(50),
            discrepancies=[],
            sample_threshold=30,
        )
        assert report.sample_sufficient is True
        assert "Insufficient sample size for statistical inference." not in report.statistical_warnings

    def test_empty_warnings_array_never_occurs(self):
        report = generate_report(
            session_id=_SESSION,
            trades=_sample_trades(100),
            discrepancies=[],
            sample_threshold=30,
        )
        assert len(report.statistical_warnings) >= 1

    def test_no_positive_expectancy_claim(self):
        report = generate_report(
            session_id=_SESSION,
            trades=_sample_trades(5),
            discrepancies=[],
        )
        for w in report.statistical_warnings:
            assert "positive expectancy" not in w.lower()


class TestReportContent:
    def test_all_cost_components_in_breakdown(self):
        report = generate_report(
            session_id=_SESSION,
            trades=_sample_trades(10),
            discrepancies=[],
        )
        assert report.total_spread_cost == Decimal("3.0")
        assert report.total_commission == Decimal("0.70")
        assert report.total_swap == Decimal("0")

    def test_avg_slippage_pips_from_discrepancies(self):
        report = generate_report(
            session_id=_SESSION,
            trades=_sample_trades(10),
            discrepancies=_sample_discrepancies(4, slippage="2.0"),
        )
        assert report.avg_slippage_pips == Decimal("2.0")

    def test_max_drawdown_computed(self):
        trades = [
            {"pnl": "5.0", "gross_pnl": "6.0", "spread_cost": "0.5", "commission": "0.5",
             "swap": "0", "duration_seconds": 30, "is_win": True},
            {"pnl": "-3.0", "gross_pnl": "-2.0", "spread_cost": "0.5", "commission": "0.5",
             "swap": "0", "duration_seconds": 30, "is_win": False},
            {"pnl": "-4.0", "gross_pnl": "-3.0", "spread_cost": "0.5", "commission": "0.5",
             "swap": "0", "duration_seconds": 30, "is_win": False},
        ]
        report = generate_report(
            session_id=_SESSION,
            trades=trades,
            discrepancies=[],
        )
        assert report.max_drawdown == Decimal("7.0")

    def test_win_rate_calculation(self):
        trades = _sample_trades(4, pnl_each="1.0") + _sample_trades(1, pnl_each="-1.0")
        report = generate_report(
            session_id=_SESSION,
            trades=trades,
            discrepancies=[],
        )
        assert report.win_rate == Decimal("80")

    def test_empty_trades_report(self):
        report = generate_report(
            session_id=_SESSION,
            trades=[],
            discrepancies=[],
        )
        assert report.sample_size == 0
        assert report.net_pnl == Decimal("0")
        assert len(report.statistical_warnings) >= 2
