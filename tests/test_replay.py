"""Replay engine tests (T013, T027)."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from scalping_core.backtest.cost_model import CostModel
from scalping_core.backtest.dataset import (
    ContractSpecMismatchError,
    DataSourceRegistry,
    evaluate_data_source,
    file_hash,
)
from scalping_core.backtest.replay import GateError, GateValidator, ReplayClock, ReplayEngine


def _write_ticks(path: Path, ticks: list[dict]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "bid", "ask", "pair"])
        w.writeheader()
        for t in ticks:
            w.writerow(t)


TICKS = [
    {"timestamp": "2026-01-01T10:00:00", "bid": "1.10500", "ask": "1.10520", "pair": "EURUSD"},
    {"timestamp": "2026-01-01T10:00:01", "bid": "1.10510", "ask": "1.10530", "pair": "EURUSD"},
    {"timestamp": "2026-01-01T10:00:02", "bid": "1.10505", "ask": "1.10525", "pair": "EURUSD"},
    {"timestamp": "2026-01-01T10:00:03", "bid": "1.10520", "ask": "1.10540", "pair": "EURUSD"},
    {"timestamp": "2026-01-01T10:00:04", "bid": "1.10530", "ask": "1.10550", "pair": "EURUSD"},
]


@pytest.fixture
def tick_file(tmp_path):
    path = tmp_path / "ticks.csv"
    _write_ticks(path, TICKS)
    return path


@pytest.fixture
def registry(tick_file):
    reg = DataSourceRegistry()
    ev = evaluate_data_source(
        tick_file, provider="Test", pair="EURUSD",
        licensing_notes="test", interval_type="real_tick", tz="UTC",
    )
    reg.approve(ev, approved_by="owner", notes="ok")
    return reg


@pytest.fixture
def cost_config():
    return {
        "commission_per_lot": "7.0",
        "swap_long_per_lot": "0.5",
        "swap_short_per_lot": "-0.3",
        "rollover_time": "00:00",
        "slippage_scenarios": [],
        "source_notes": "test",
    }


@pytest.fixture
def gate_validator(registry, cost_config):
    return GateValidator(
        data_source_registry=registry,
        cost_model_configs={"EURUSD": cost_config},
        exit_policy_version="v1",
        acceptance_criteria={"criteria_version": "1.0.0"},
    )


@pytest.fixture
def engine(gate_validator, cost_config):
    return ReplayEngine(
        gate_validator=gate_validator,
        cost_model=CostModel(cost_config),
    )


def test_replay_strict_chronological(engine, tick_file):
    h = file_hash(tick_file)
    result = engine.replay(
        dataset_path=tick_file,
        dataset_hash_expected=h,
        pair="EURUSD",
        strategy_name="momentum",
        configuration={},
        exit_policy_version="v1",
    )
    assert result["strategy_name"] == "momentum"
    assert result["dataset_hash"] == h


def test_determinism_two_runs_identical(engine, tick_file):
    h = file_hash(tick_file)
    kwargs = dict(
        dataset_path=tick_file,
        dataset_hash_expected=h,
        pair="EURUSD",
        strategy_name="momentum",
        configuration={"lookback_window": 2},
        exit_policy_version="v1",
    )
    r1 = engine.replay(**kwargs)
    r2 = engine.replay(**kwargs)
    assert r1["dataset_hash"] == r2["dataset_hash"]
    assert r1["configuration_hash"] == r2["configuration_hash"]
    assert r1["total_trades"] == r2["total_trades"]
    assert r1["net_pnl"] == r2["net_pnl"]


def test_missing_intervals_flagged_not_filled(tmp_path, gate_validator, cost_config):
    ticks = [
        {"timestamp": "2026-01-01T10:00:00", "bid": "1.1", "ask": "1.2", "pair": "EURUSD"},
        {"timestamp": "2026-01-01T10:05:00", "bid": "1.1", "ask": "1.2", "pair": "EURUSD"},
    ]
    path = tmp_path / "gap.csv"
    _write_ticks(path, ticks)
    h = file_hash(path)
    eng = ReplayEngine(gate_validator=gate_validator, cost_model=CostModel(cost_config))
    result = eng.replay(
        dataset_path=path,
        dataset_hash_expected=h,
        pair="EURUSD",
        strategy_name="test",
        configuration={},
        exit_policy_version="v1",
    )
    assert len(result["quality_flags"]) >= 1
    assert result["quality_flags"][0]["type"] == "missing_interval"


def test_replay_clock_no_system_clock():
    clock = ReplayClock()
    with pytest.raises(RuntimeError, match="not set"):
        _ = clock.now
    ts = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    clock.set(ts)
    assert clock.now == ts


def test_gate_refuses_without_data_source():
    reg = DataSourceRegistry()
    gv = GateValidator(
        data_source_registry=reg,
        cost_model_configs={},
        exit_policy_version=None,
        acceptance_criteria=None,
    )
    errors = gv.validate_replay("EURUSD")
    assert any("no approved data source" in e for e in errors)


def test_gate_refuses_without_exit_policy(registry):
    gv = GateValidator(
        data_source_registry=registry,
        cost_model_configs={"EURUSD": {}},
        exit_policy_version=None,
        acceptance_criteria=None,
    )
    errors = gv.validate_replay("EURUSD")
    assert any("exit policy" in e for e in errors)


def test_gate_refuses_strategy_eval_without_criteria(registry):
    gv = GateValidator(
        data_source_registry=registry,
        cost_model_configs={"EURUSD": {}},
        exit_policy_version="v1",
        acceptance_criteria=None,
    )
    errors = gv.validate_strategy_evaluation("EURUSD")
    assert any("acceptance criteria" in e for e in errors)


def test_full_pipeline_gate_error(tick_file):
    reg = DataSourceRegistry()
    gv = GateValidator(
        data_source_registry=reg,
        cost_model_configs={},
        exit_policy_version=None,
        acceptance_criteria=None,
    )
    eng = ReplayEngine(gate_validator=gv)
    with pytest.raises(GateError):
        eng.replay(
            dataset_path=tick_file,
            dataset_hash_expected="any",
            pair="EURUSD",
            strategy_name="test",
            configuration={},
            exit_policy_version="v1",
        )


def test_contract_spec_mismatch_rejected(tick_file):
    reg = DataSourceRegistry()
    ev = evaluate_data_source(
        tick_file, provider="Test", pair="EURUSD",
        licensing_notes="test", interval_type="real_tick", tz="UTC",
        point="0.00001", digits=5, pip_value="10.0",
    )
    reg.approve(ev, approved_by="owner", notes="ok")
    with pytest.raises(ContractSpecMismatchError, match="digits"):
        reg.validate_contract_specs("EURUSD", point="0.00001", digits=4, pip_value="10.0")


def test_contract_spec_match_passes(tick_file):
    reg = DataSourceRegistry()
    ev = evaluate_data_source(
        tick_file, provider="Test", pair="EURUSD",
        licensing_notes="test", interval_type="real_tick", tz="UTC",
        point="0.00001", digits=5, pip_value="10.0",
    )
    reg.approve(ev, approved_by="owner", notes="ok")
    reg.validate_contract_specs("EURUSD", point="0.00001", digits=5, pip_value="10.0")
