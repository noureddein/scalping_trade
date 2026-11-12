"""Acceptance criteria and tried-configuration ledger tests (T010, T023 partial)."""
from __future__ import annotations

import pytest

from scalping_core.backtest.ledger import (
    AcceptanceCriteriaStore,
    NoCriteriaError,
    TriedConfigurationLedger,
)


def test_refuses_parameter_selection_without_criteria():
    store = AcceptanceCriteriaStore()
    with pytest.raises(NoCriteriaError, match="no acceptance criteria"):
        store.require()


def test_meets_criteria_recorded_with_version_hash():
    store = AcceptanceCriteriaStore()
    store.define(
        criteria_version="1.0.0",
        criteria={"min_net_pnl": 5, "max_drawdown": 10},
        approved_by="owner",
    )
    result = store.evaluate({"min_net_pnl": 6, "max_drawdown": 12})
    assert result["meets_criteria"] is True
    assert result["criteria_version"] == "1.0.0"
    assert result["criteria_hash"]


def test_result_states_no_authorization():
    store = AcceptanceCriteriaStore()
    store.define(criteria_version="1.0.0", criteria={"min_net_pnl": 5}, approved_by="owner")
    result = store.evaluate({"min_net_pnl": 10})
    assert "does NOT authorize" in result["authorization_note"]
    assert "Strategy Tester" in result["authorization_note"]
    assert "Demo" in result["authorization_note"]
    assert "live trading" in result["authorization_note"]


def test_criteria_version_uniqueness():
    store = AcceptanceCriteriaStore()
    store.define(criteria_version="1.0.0", criteria={"x": 1}, approved_by="owner")
    with pytest.raises(ValueError, match="already exists"):
        store.define(criteria_version="1.0.0", criteria={"x": 2}, approved_by="owner")


def test_fails_criteria_when_below_threshold():
    store = AcceptanceCriteriaStore()
    store.define(criteria_version="1.0.0", criteria={"min_net_pnl": 10}, approved_by="owner")
    result = store.evaluate({"min_net_pnl": 3})
    assert result["meets_criteria"] is False


def test_ledger_records_entry():
    ledger = TriedConfigurationLedger()
    entry = ledger.record(
        run_id="run-1",
        dataset_hash="dh",
        code_hash="ch",
        configuration_hash="cfh",
        configuration_json={"param": "value"},
        strategy_name="momentum",
        summary_result={"trades": 5, "pnl": "1.0"},
    )
    assert entry["run_id"] == "run-1"
    assert entry["strategy_name"] == "momentum"
    assert "entry_id" in entry
    assert "created_at" in entry
    assert len(ledger.entries) == 1


def test_ledger_append_only():
    ledger = TriedConfigurationLedger()
    ledger.record(
        run_id="r1", dataset_hash="d", code_hash="c",
        configuration_hash="cf", configuration_json={},
        strategy_name="s", summary_result={},
    )
    ledger.record(
        run_id="r2", dataset_hash="d", code_hash="c",
        configuration_hash="cf2", configuration_json={"changed": True},
        strategy_name="s", summary_result={},
    )
    assert len(ledger.entries) == 2


def test_ledger_non_comparable_on_hash_change():
    ledger = TriedConfigurationLedger()
    assert ledger.is_non_comparable("hash_new", "hash_old") is True
    assert ledger.is_non_comparable("same", "same") is False
