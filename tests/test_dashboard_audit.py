"""Dashboard audit and risk config tests (T018).

Tests for: valid config change, invalid rejection, read-only rejection,
audit log integrity, change takes effect without restart.
"""
from __future__ import annotations

import pytest
from scalping_core.dashboard.api import DashboardApp
from scalping_core.dashboard.event_bus import EventBus

# Reuse FakeBackend from test_dashboard_api
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from test_dashboard_api import FakeBackend


@pytest.fixture
def fake_backend():
    return FakeBackend()


@pytest.fixture
def dashboard_app(fake_backend):
    return DashboardApp(fake_backend, EventBus())


# --- T018: Risk config tests ---

@pytest.mark.asyncio
async def test_valid_config_change_applied_and_logged(aiohttp_client, dashboard_app, fake_backend):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.put("/api/risk-config/daily_profit_limit", json={"value": 20})
    assert resp.status == 200
    data = await resp.json()
    assert data["applied"] is True
    assert data["old_value"] == "15"
    assert str(data["new_value"]) == "20"
    assert len(fake_backend._audit_entries) == 1
    entry = fake_backend._audit_entries[0]
    assert entry["parameter_name"] == "daily_profit_limit"
    assert "created_at" in entry
    assert entry["operator_id"] == "operator"


@pytest.mark.asyncio
async def test_invalid_value_rejected(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.put("/api/risk-config/daily_profit_limit", json={"value": -5})
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_read_only_parameter_rejected(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.put("/api/risk-config/lot_size", json={"value": 0.02})
    assert resp.status == 403
    data = await resp.json()
    assert "read-only" in data["error"]


@pytest.mark.asyncio
async def test_trading_schedule_read_only(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.put("/api/risk-config/trading_schedule", json={"value": "09:00-17:00"})
    assert resp.status == 403


@pytest.mark.asyncio
async def test_audit_log_contains_required_fields(aiohttp_client, dashboard_app, fake_backend):
    client = await aiohttp_client(dashboard_app.app)
    await client.put("/api/risk-config/daily_loss_limit", json={"value": 10})
    assert len(fake_backend._audit_entries) == 1
    entry = fake_backend._audit_entries[0]
    assert "entry_id" in entry
    assert "account_id" in entry
    assert "parameter_name" in entry
    assert "old_value" in entry
    assert "new_value" in entry
    assert "created_at" in entry
    assert "operator_id" in entry
    assert "change_source" in entry


@pytest.mark.asyncio
async def test_config_change_takes_effect_next_cycle(aiohttp_client, dashboard_app, fake_backend):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.get("/api/risk-config")
    before = await resp.json()
    assert before["daily_profit_limit"]["value"] == "15"

    await client.put("/api/risk-config/daily_profit_limit", json={"value": 25})

    resp2 = await client.get("/api/risk-config")
    after = await resp2.json()
    assert str(after["daily_profit_limit"]["value"]) == "25"


@pytest.mark.asyncio
async def test_position_limits_valid(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.put("/api/risk-config/position_limits", json={"value": 3})
    assert resp.status == 200


@pytest.mark.asyncio
async def test_position_limits_invalid_zero(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.put("/api/risk-config/position_limits", json={"value": 0})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_unknown_parameter_rejected(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.put("/api/risk-config/nonexistent", json={"value": 1})
    assert resp.status == 400
