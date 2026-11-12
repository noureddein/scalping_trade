"""Dataset loading, hashing, and data source tests (T008)."""
from __future__ import annotations

import csv
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from scalping_core.backtest.dataset import (
    DataSourceGateError,
    DataSourceRegistry,
    DatasetHashMismatchError,
    config_hash,
    evaluate_data_source,
    file_hash,
    load_dataset,
    verify_dataset_hash,
)


def _write_tick_csv(path: Path, ticks: list[dict]) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "bid", "ask", "pair"])
        writer.writeheader()
        for t in ticks:
            writer.writerow(t)


@pytest.fixture
def sample_ticks():
    return [
        {"timestamp": "2026-01-01T10:00:00", "bid": "1.10500", "ask": "1.10520", "pair": "EURUSD"},
        {"timestamp": "2026-01-01T10:00:01", "bid": "1.10510", "ask": "1.10530", "pair": "EURUSD"},
        {"timestamp": "2026-01-01T10:00:02", "bid": "1.10505", "ask": "1.10525", "pair": "EURUSD"},
    ]


@pytest.fixture
def tick_file(tmp_path, sample_ticks):
    path = tmp_path / "ticks.csv"
    _write_tick_csv(path, sample_ticks)
    return path


def test_file_hash_deterministic(tick_file):
    h1 = file_hash(tick_file)
    h2 = file_hash(tick_file)
    assert h1 == h2
    assert len(h1) == 64


def test_config_hash_sorted():
    h1 = config_hash({"b": 2, "a": 1})
    h2 = config_hash({"a": 1, "b": 2})
    assert h1 == h2


def test_load_dataset_returns_all_fields(tick_file):
    ds = load_dataset(tick_file, source_id="src-1", pair="EURUSD")
    assert ds["tick_count"] == 3
    assert ds["pair"] == "EURUSD"
    assert ds["file_hash"]
    assert ds["missing_intervals"] == 0
    assert ds["quality_flags"] == []


def test_load_dataset_detects_missing_intervals(tmp_path):
    ticks = [
        {"timestamp": "2026-01-01T10:00:00", "bid": "1.1", "ask": "1.2", "pair": "EURUSD"},
        {"timestamp": "2026-01-01T10:05:00", "bid": "1.1", "ask": "1.2", "pair": "EURUSD"},
    ]
    path = tmp_path / "gap.csv"
    _write_tick_csv(path, ticks)
    ds = load_dataset(path, source_id="src-1", pair="EURUSD")
    assert ds["missing_intervals"] == 1
    assert ds["quality_flags"][0]["type"] == "missing_interval"


def test_verify_hash_mismatch(tick_file):
    with pytest.raises(DatasetHashMismatchError, match="mismatch"):
        verify_dataset_hash(tick_file, "wrong_hash")


def test_verify_hash_correct(tick_file):
    h = file_hash(tick_file)
    verify_dataset_hash(tick_file, h)


def test_evaluate_data_source_report(tick_file):
    report = evaluate_data_source(
        tick_file,
        provider="TestProvider",
        pair="EURUSD",
        licensing_notes="test license",
        interval_type="real_tick",
        tz="UTC",
    )
    assert report["provider"] == "TestProvider"
    assert report["pair"] == "EURUSD"
    assert report["licensing_notes"] == "test license"
    assert report["interval_type"] == "real_tick"
    assert report["timezone"] == "UTC"
    assert report["bid_ask_availability"] == "real"
    assert report["tick_count"] == 3
    assert report["missing_period_count"] == 0
    assert "quality_score" in report


def test_data_source_gate_refuses_without_approval():
    reg = DataSourceRegistry()
    with pytest.raises(DataSourceGateError, match="no approved data source"):
        reg.require("EURUSD")


def test_data_source_gate_passes_after_approval(tick_file):
    reg = DataSourceRegistry()
    evaluation = evaluate_data_source(
        tick_file, provider="P", pair="EURUSD",
        licensing_notes="ok", interval_type="real_tick", tz="UTC",
    )
    reg.approve(evaluation, approved_by="owner", notes="approved")
    source = reg.require("EURUSD")
    assert source["pair"] == "EURUSD"
    assert source["approved_by"] == "owner"


def test_approval_stores_all_metadata(tick_file):
    reg = DataSourceRegistry()
    evaluation = evaluate_data_source(
        tick_file, provider="TickData", pair="GBPUSD",
        licensing_notes="commercial", interval_type="generated", tz="US/Eastern",
    )
    record = reg.approve(evaluation, approved_by="owner", notes="good enough")
    assert record["provider"] == "TickData"
    assert record["pair"] == "GBPUSD"
    assert record["interval_type"] == "generated"
    assert record["timezone"] == "US/Eastern"
    assert record["approval_notes"] == "good enough"
    assert "source_id" in record
    assert "approval_date" in record
