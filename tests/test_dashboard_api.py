"""Dashboard API tests (T009, T012, T021, T026).

Tests for: overview, pairs, positions, history, risk-events, audit-log,
system-logs endpoints.
"""
from __future__ import annotations

import json
import pytest
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from scalping_core.dashboard.api import DashboardApp
from scalping_core.dashboard.event_bus import EventBus


class FakeBackend:
    """Minimal duck-typed backend for dashboard tests."""

    def __init__(self) -> None:
        self._available = True
        self._state: dict[str, Any] = {
            "trading_status": "ACTIVE",
            "broker_name": "TestBroker",
            "account_id": "12345",
            "daily_net_pnl": "5.25",
            "daily_profit_limit": "15",
            "daily_loss_limit": "5",
            "open_positions_count": 1,
            "trades_today": 3,
            "win_count": 2,
            "loss_count": 1,
            "total_spread_costs": "0.50",
            "account_equity": "1000.00",
        }
        self._pairs: list[dict[str, Any]] = [
            {
                "canonical_pair": "EURUSD",
                "broker_symbol": "EURUSD.m",
                "trading_enabled": True,
                "current_spread": "1.2",
                "average_spread": "1.5",
                "maximum_spread": "3.0",
                "spread_status": "NORMAL",
                "active_position": False,
                "trading_permission": True,
            }
        ]
        self._positions: list[dict[str, Any]] = [
            {
                "pair": "EURUSD",
                "direction": "BUY",
                "entry_price": "1.10500",
                "current_price": "1.10550",
                "lot_size": "0.01",
                "floating_pnl": "0.50",
                "stop_loss": "1.10400",
                "take_profit": "1.10700",
                "holding_duration": "00:05:30",
                "strategy": "momentum",
                "exit_status": "OPEN",
            }
        ]
        self._risk_config: dict[str, Any] = {
            "daily_profit_limit": {"value": "15", "editable": True},
            "daily_loss_limit": {"value": "5", "editable": True},
            "max_loss_per_trade": {"value": "0.50", "editable": True},
            "lot_size": {"value": "0.01", "editable": False},
            "take_profit_range": {"value": "20", "editable": True},
            "spread_thresholds": {"value": "3.0", "editable": True},
            "trading_schedule": {"value": "not configured", "editable": False},
            "position_limits": {"value": 1, "editable": True},
        }
        self._history: list[dict[str, Any]] = [
            {"pair": "EURUSD", "direction": "BUY", "realized_pnl": "1.50"}
        ]
        self._risk_events: list[dict[str, Any]] = [
            {"event_type": "LIMIT_TRIGGERED", "detail": "profit locked", "created_at": "2026-11-12T10:00:00Z"},
            {"event_type": "LOCK_RESET", "detail": "daily reset", "created_at": "2026-11-12T06:00:00Z"},
        ]
        self._system_logs: list[dict[str, Any]] = [
            {"level": "INFO", "message": "started", "timestamp": "2026-11-12T06:00:00Z"},
            {"level": "ERROR", "message": "timeout", "timestamp": "2026-11-12T07:00:00Z"},
            {"level": "WARN", "message": "spread spike", "timestamp": "2026-11-12T08:00:00Z"},
        ]
        self._audit_entries: list[dict[str, Any]] = []
        self._emergency_activated = False

    def get_dashboard_state(self) -> dict[str, Any] | None:
        if not self._available:
            return None
        return dict(self._state)

    def get_account_id(self) -> str:
        return "12345"

    def get_pairs(self) -> list[dict[str, Any]]:
        return list(self._pairs)

    def add_pair(self, canonical: str, broker_symbol: str) -> dict[str, Any]:
        for p in self._pairs:
            if p["canonical_pair"] == canonical:
                raise ValueError(f"pair {canonical} already exists")
        pair = {
            "canonical_pair": canonical,
            "broker_symbol": broker_symbol,
            "trading_enabled": True,
            "current_spread": "0",
            "average_spread": "0",
            "maximum_spread": "0",
            "spread_status": "NORMAL",
            "active_position": False,
            "trading_permission": True,
        }
        self._pairs.append(pair)
        return pair

    def set_pair_enabled(self, pair: str, enabled: bool) -> dict[str, Any]:
        for p in self._pairs:
            if p["canonical_pair"] == pair:
                p["trading_enabled"] = enabled
                return dict(p)
        raise KeyError(pair)

    def delete_pair(self, pair: str) -> None:
        for p in self._pairs:
            if p["canonical_pair"] == pair:
                if p.get("active_position"):
                    raise ValueError("pair has active position or unresolved order")
                self._pairs.remove(p)
                return
        raise KeyError(pair)

    def get_spread_monitor(self, pair: str) -> dict[str, Any]:
        for p in self._pairs:
            if p["canonical_pair"] == pair:
                return {
                    "current_spread": p["current_spread"],
                    "average_spread": p["average_spread"],
                    "maximum_spread": p["maximum_spread"],
                    "spread_trend": "STABLE",
                    "spread_volatility": "0.3",
                    "manual_threshold": "5.0",
                    "dynamic_threshold": "3.0",
                    "stability_timer": "NORMAL",
                    "trading_permission": p["trading_permission"],
                }
        raise KeyError(pair)

    def get_risk_config(self) -> dict[str, Any]:
        return dict(self._risk_config)

    def update_risk_config(self, parameter: str, value: Any) -> tuple[Any, Any]:
        entry = self._risk_config.get(parameter)
        if entry is None:
            raise ValueError(f"unknown parameter: {parameter}")
        old = entry["value"]
        entry["value"] = str(value) if not isinstance(value, int) else value
        return old, entry["value"]

    def get_positions(self) -> list[dict[str, Any]]:
        return list(self._positions)

    def get_history(self) -> list[dict[str, Any]]:
        return list(self._history)

    def get_risk_events(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self._risk_events[offset:offset + limit]

    def get_audit_entries(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        entries = list(reversed(self._audit_entries))
        return entries[offset:offset + limit]

    def persist_audit_entry(self, entry: dict[str, Any]) -> None:
        self._audit_entries.append(entry)

    def get_system_logs(self, *, limit: int = 50, level: str | None = None) -> list[dict[str, Any]]:
        logs = self._system_logs
        if level:
            logs = [l for l in logs if l["level"] == level]
        return logs[:limit]

    def get_broker_accounts(self) -> list[dict[str, Any]]:
        return [{"broker_name": "TestBroker", "login": "12345", "server": "Demo", "connected": True}]

    def get_strategy_performance(self) -> list[dict[str, Any]]:
        return [{"strategy": "momentum", "trades": 10, "wins": 7, "losses": 3, "net_pnl": "4.50"}]

    def get_execution_stats(self) -> dict[str, Any]:
        return {"total_orders": 10, "filled": 8, "cancelled": 1, "rejected": 1}

    def emergency_stop(self) -> dict[str, Any]:
        if self._emergency_activated:
            raise ValueError("already DRAINING")
        self._emergency_activated = True
        self._state["trading_status"] = "DRAINING"
        return {"state": "DRAINING", "activated_at": datetime.now(timezone.utc).isoformat()}


@pytest.fixture
def fake_backend():
    return FakeBackend()


@pytest.fixture
def dashboard_app(fake_backend):
    bus = EventBus()
    return DashboardApp(fake_backend, bus)


@pytest.fixture
def client(aiohttp_client, dashboard_app):
    async def _make():
        return await aiohttp_client(dashboard_app.app)
    return _make


# --- T009: Overview tests ---

@pytest.mark.asyncio
async def test_overview_returns_all_fields(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.get("/api/overview")
    assert resp.status == 200
    data = await resp.json()
    expected = [
        "trading_status", "broker_name", "account_id", "daily_net_pnl",
        "daily_profit_limit", "daily_loss_limit", "open_positions_count",
        "trades_today", "win_count", "loss_count", "total_spread_costs",
        "account_equity",
    ]
    for field in expected:
        assert field in data, f"missing field: {field}"


@pytest.mark.asyncio
async def test_overview_503_when_backend_unavailable(aiohttp_client, fake_backend):
    fake_backend._available = False
    app = DashboardApp(fake_backend)
    client = await aiohttp_client(app.app)
    resp = await client.get("/api/overview")
    assert resp.status == 503


@pytest.mark.asyncio
async def test_overview_shows_locked_status(aiohttp_client, fake_backend):
    fake_backend._state["trading_status"] = "PROFIT_LOCKED"
    app = DashboardApp(fake_backend)
    client = await aiohttp_client(app.app)
    resp = await client.get("/api/overview")
    data = await resp.json()
    assert "PROFIT_LOCKED" in data["trading_status"]


@pytest.mark.asyncio
async def test_overview_values_update(aiohttp_client, dashboard_app, fake_backend):
    client = await aiohttp_client(dashboard_app.app)
    resp1 = await client.get("/api/overview")
    data1 = await resp1.json()
    assert data1["trades_today"] == 3
    fake_backend._state["trades_today"] = 4
    fake_backend._state["win_count"] = 3
    resp2 = await client.get("/api/overview")
    data2 = await resp2.json()
    assert data2["trades_today"] == 4
    assert data2["win_count"] == 3


# --- T012: Pairs tests ---

@pytest.mark.asyncio
async def test_pairs_returns_all_fields(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.get("/api/pairs")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) >= 1
    pair = data[0]
    expected = [
        "canonical_pair", "broker_symbol", "trading_enabled", "current_spread",
        "average_spread", "maximum_spread", "spread_status", "active_position",
        "trading_permission",
    ]
    for field in expected:
        assert field in pair, f"missing field: {field}"


@pytest.mark.asyncio
async def test_add_pair_creates_and_logs(aiohttp_client, dashboard_app, fake_backend):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.post("/api/pairs", json={
        "canonical_pair": "GBPUSD", "broker_symbol": "GBPUSD.m"
    })
    assert resp.status == 201
    data = await resp.json()
    assert data["canonical_pair"] == "GBPUSD"
    assert len(fake_backend._audit_entries) == 1


@pytest.mark.asyncio
async def test_enable_disable_pair_logs(aiohttp_client, dashboard_app, fake_backend):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.put("/api/pairs/EURUSD/enabled", json={"enabled": False})
    assert resp.status == 200
    data = await resp.json()
    assert data["trading_enabled"] is False
    assert len(fake_backend._audit_entries) == 1


@pytest.mark.asyncio
async def test_delete_pair_blocked_on_active_position(aiohttp_client, fake_backend):
    fake_backend._pairs[0]["active_position"] = True
    app = DashboardApp(fake_backend)
    client = await aiohttp_client(app.app)
    resp = await client.delete("/api/pairs/EURUSD")
    assert resp.status == 409


@pytest.mark.asyncio
async def test_delete_pair_succeeds_no_position(aiohttp_client, dashboard_app, fake_backend):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.delete("/api/pairs/EURUSD")
    assert resp.status == 204
    assert len(fake_backend._pairs) == 0


# --- T021: Positions tests ---

@pytest.mark.asyncio
async def test_positions_returns_all_fields(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.get("/api/positions")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) == 1
    pos = data[0]
    expected = [
        "pair", "direction", "entry_price", "current_price", "lot_size",
        "floating_pnl", "stop_loss", "take_profit", "holding_duration",
        "strategy", "exit_status",
    ]
    for field in expected:
        assert field in pos, f"missing field: {field}"


@pytest.mark.asyncio
async def test_positions_empty_returns_array(aiohttp_client, fake_backend):
    fake_backend._positions = []
    app = DashboardApp(fake_backend)
    client = await aiohttp_client(app.app)
    resp = await client.get("/api/positions")
    assert resp.status == 200
    data = await resp.json()
    assert data == []


@pytest.mark.asyncio
async def test_positions_pnl_updates(aiohttp_client, dashboard_app, fake_backend):
    client = await aiohttp_client(dashboard_app.app)
    fake_backend._positions[0]["floating_pnl"] = "1.25"
    resp = await client.get("/api/positions")
    data = await resp.json()
    assert data[0]["floating_pnl"] == "1.25"


@pytest.mark.asyncio
async def test_positions_removed_on_close(aiohttp_client, dashboard_app, fake_backend):
    client = await aiohttp_client(dashboard_app.app)
    fake_backend._positions = []
    resp = await client.get("/api/positions")
    data = await resp.json()
    assert data == []


# --- T026: Secondary endpoints ---

@pytest.mark.asyncio
async def test_history_returns_closed_positions(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.get("/api/history")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) >= 1
    assert "realized_pnl" in data[0]


@pytest.mark.asyncio
async def test_risk_events_pagination(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.get("/api/risk-events?limit=1&offset=0")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) == 1
    resp2 = await client.get("/api/risk-events?limit=1&offset=1")
    data2 = await resp2.json()
    assert len(data2) == 1
    assert data[0] != data2[0]


@pytest.mark.asyncio
async def test_audit_log_pagination(aiohttp_client, dashboard_app, fake_backend):
    client = await aiohttp_client(dashboard_app.app)
    # Create some audit entries
    await client.post("/api/pairs", json={"canonical_pair": "GBPUSD", "broker_symbol": "GBPUSD.m"})
    await client.post("/api/pairs", json={"canonical_pair": "USDJPY", "broker_symbol": "USDJPY.m"})
    resp = await client.get("/api/audit-log?limit=1&offset=0")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) == 1


@pytest.mark.asyncio
async def test_system_logs_level_filtering(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.get("/api/system-logs?level=ERROR")
    assert resp.status == 200
    data = await resp.json()
    assert all(l["level"] == "ERROR" for l in data)
    assert len(data) == 1


# --- T031: FR-006 missing endpoints ---

@pytest.mark.asyncio
async def test_broker_accounts_returns_fields(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.get("/api/broker-accounts")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) >= 1
    assert "broker_name" in data[0]
    assert "login" in data[0]


@pytest.mark.asyncio
async def test_strategy_performance_returns_fields(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.get("/api/strategy-performance")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) >= 1
    assert "strategy" in data[0]
    assert "net_pnl" in data[0]


@pytest.mark.asyncio
async def test_execution_stats_returns_fields(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.get("/api/execution-stats")
    assert resp.status == 200
    data = await resp.json()
    assert "total_orders" in data
    assert "filled" in data


# --- T032: Cross-validation max_loss_per_trade ---

@pytest.mark.asyncio
async def test_max_loss_per_trade_rejects_above_daily_loss_limit(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.put("/api/risk-config/max_loss_per_trade", json={"value": 100})
    assert resp.status == 400
    data = await resp.json()
    assert "exceeds" in data["error"]


@pytest.mark.asyncio
async def test_max_loss_per_trade_accepts_within_daily_loss_limit(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app.app)
    resp = await client.put("/api/risk-config/max_loss_per_trade", json={"value": 2})
    assert resp.status == 200
