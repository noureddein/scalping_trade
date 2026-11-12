"""Cost model tests (T015)."""
from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal

import pytest

from scalping_core.backtest.cost_model import CostModel


@pytest.fixture
def config():
    return {
        "commission_per_lot": "7.0",
        "swap_long_per_lot": "0.5",
        "swap_short_per_lot": "-0.3",
        "rollover_time": "00:00",
        "slippage_scenarios": [
            {"label": "low", "pips": "0.5"},
            {"label": "medium", "pips": "1.0"},
            {"label": "high", "pips": "2.0"},
        ],
        "source_notes": "test config",
    }


@pytest.fixture
def model(config):
    return CostModel(config)


def test_all_cost_components_included(model):
    costs = model.calculate_costs(
        lot_size=Decimal("0.01"),
        direction="BUY",
        entry_time=datetime(2026, 1, 1, 10, 0),
        exit_time=datetime(2026, 1, 1, 10, 5),
        spread_at_fill=Decimal("0.00020"),
    )
    assert "commission" in costs
    assert "swap" in costs
    assert "spread_at_fill" in costs
    assert "known_costs" in costs
    assert "slippage_sensitivity" in costs


def test_no_double_counting_spread(model):
    costs = model.calculate_costs(
        lot_size=Decimal("0.01"),
        direction="BUY",
        entry_time=datetime(2026, 1, 1, 10, 0),
        exit_time=datetime(2026, 1, 1, 10, 5),
        spread_at_fill=Decimal("0.00020"),
    )
    known = Decimal(costs["known_costs"])
    commission = Decimal(costs["commission"])
    swap = Decimal(costs["swap"])
    assert known == commission + swap


def test_unknown_costs_as_sensitivity_range():
    config_no_slip = {
        "commission_per_lot": "7.0",
        "swap_long_per_lot": "0.5",
        "swap_short_per_lot": "-0.3",
        "rollover_time": "00:00",
        "slippage_scenarios": [],
        "source_notes": "test",
    }
    m = CostModel(config_no_slip)
    costs = m.calculate_costs(
        lot_size=Decimal("0.01"),
        direction="BUY",
        entry_time=datetime(2026, 1, 1, 10, 0),
        exit_time=datetime(2026, 1, 1, 10, 5),
        spread_at_fill=Decimal("0.0002"),
    )
    assert len(costs["unknown_costs"]) == 1
    assert costs["unknown_costs"][0]["label"] == "unknown"


def test_swap_zero_same_session(model):
    costs = model.calculate_costs(
        lot_size=Decimal("0.01"),
        direction="BUY",
        entry_time=datetime(2026, 1, 1, 10, 0),
        exit_time=datetime(2026, 1, 1, 10, 5),
        spread_at_fill=Decimal("0.0002"),
    )
    assert Decimal(costs["swap"]) == Decimal("0")


def test_swap_applied_overnight(model):
    costs = model.calculate_costs(
        lot_size=Decimal("0.01"),
        direction="BUY",
        entry_time=datetime(2026, 1, 1, 23, 0),
        exit_time=datetime(2026, 1, 2, 1, 0),
        spread_at_fill=Decimal("0.0002"),
    )
    assert Decimal(costs["swap"]) > Decimal("0")


def test_manual_calculation_match(model):
    lot = Decimal("0.01")
    costs = model.calculate_costs(
        lot_size=lot,
        direction="BUY",
        entry_time=datetime(2026, 1, 1, 10, 0),
        exit_time=datetime(2026, 1, 1, 10, 5),
        spread_at_fill=Decimal("0.0002"),
    )
    expected_commission = Decimal("7.0") * lot
    assert Decimal(costs["commission"]) == expected_commission
    assert Decimal(costs["swap"]) == Decimal("0")
    assert Decimal(costs["known_costs"]) == expected_commission


def test_negative_costs_rebates():
    config_rebate = {
        "commission_per_lot": "-2.0",
        "swap_long_per_lot": "0",
        "swap_short_per_lot": "0",
        "rollover_time": "00:00",
        "slippage_scenarios": [],
        "source_notes": "rebate test",
    }
    m = CostModel(config_rebate)
    costs = m.calculate_costs(
        lot_size=Decimal("0.01"),
        direction="BUY",
        entry_time=datetime(2026, 1, 1, 10, 0),
        exit_time=datetime(2026, 1, 1, 10, 5),
        spread_at_fill=Decimal("0.0002"),
    )
    assert Decimal(costs["commission"]) < Decimal("0")


def test_simulate_fill_produces_trade(model):
    tick = {"timestamp": datetime(2026, 1, 1, 10, 0), "bid": Decimal("1.10500"), "ask": Decimal("1.10520")}
    signal = {"direction": "BUY", "lot_size": "0.01", "exit_price": "1.10550"}
    trade = model.simulate_fill(tick, signal)
    assert "gross_pnl" in trade
    assert "net_pnl" in trade
    assert "costs" in trade
    assert "cost_breakdown" in trade
