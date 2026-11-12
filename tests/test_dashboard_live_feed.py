"""Dashboard SSE and live feed tests (T015, T029).

Tests for: spread events, SSE reconnection, heartbeat, dashboard
independence from backend.
"""
from __future__ import annotations

import asyncio
import json
import pytest
from decimal import Decimal
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestClient

from scalping_core.dashboard.api import DashboardApp
from scalping_core.dashboard.event_bus import EventBus
from scalping_core.dashboard.live_feed import ReplayBuffer

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from test_dashboard_api import FakeBackend


@pytest.fixture
def fake_backend():
    return FakeBackend()


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def dashboard_app(fake_backend, event_bus):
    return DashboardApp(fake_backend, event_bus)


# --- T015: Spread event tests ---

def test_spread_event_has_all_fields(fake_backend):
    spread = fake_backend.get_spread_monitor("EURUSD")
    expected = [
        "current_spread", "average_spread", "maximum_spread",
        "spread_trend", "spread_volatility", "manual_threshold",
        "dynamic_threshold", "stability_timer", "trading_permission",
    ]
    for field in expected:
        assert field in spread, f"missing spread field: {field}"


def test_spread_event_emitted_on_publish(event_bus):
    q = event_bus.subscribe("spread")
    event_bus.publish("spread", {"pair": "EURUSD", "current_spread": "1.2"})
    event = q.get_nowait()
    assert event["type"] == "spread"
    assert event["data"]["pair"] == "EURUSD"


def test_pair_update_event_emitted(event_bus):
    q = event_bus.subscribe_all()
    event_bus.publish_to_all("pair-update", {"canonical_pair": "EURUSD", "trading_enabled": False})
    event = q.get_nowait()
    assert event["type"] == "pair-update"


# --- T029: SSE reconnection and replay tests ---

def test_replay_buffer_stores_events():
    buf = ReplayBuffer(maxlen=10)
    buf.append({"id": 1, "type": "overview", "data": {}})
    buf.append({"id": 2, "type": "spread", "data": {}})
    buf.append({"id": 3, "type": "position", "data": {}})
    after = buf.events_after(1)
    assert len(after) == 2
    assert after[0]["id"] == 2
    assert after[1]["id"] == 3


def test_replay_buffer_oldest_id():
    buf = ReplayBuffer(maxlen=3)
    buf.append({"id": 5, "type": "x", "data": {}})
    buf.append({"id": 6, "type": "x", "data": {}})
    buf.append({"id": 7, "type": "x", "data": {}})
    assert buf.oldest_id == 5
    buf.append({"id": 8, "type": "x", "data": {}})
    assert buf.oldest_id == 6


def test_replay_buffer_empty():
    buf = ReplayBuffer()
    assert buf.oldest_id == 0
    assert buf.events_after(0) == []


def test_replay_no_duplicates():
    buf = ReplayBuffer(maxlen=10)
    for i in range(1, 6):
        buf.append({"id": i, "type": "test", "data": {}})
    after = buf.events_after(3)
    ids = [e["id"] for e in after]
    assert ids == [4, 5]
    assert len(ids) == len(set(ids))


# --- Event bus tests ---

def test_event_bus_subscribe_unsubscribe():
    bus = EventBus()
    q = bus.subscribe("overview")
    bus.publish("overview", {"test": True})
    assert not q.empty()
    bus.unsubscribe("overview", q)
    bus.publish("overview", {"test": True})
    assert q.qsize() == 1  # only the first event


def test_event_bus_full_queue_drops_oldest():
    bus = EventBus()
    q = bus.subscribe("x")
    for i in range(300):
        bus.publish("x", {"i": i})
    assert q.qsize() <= 256


def test_event_bus_subscribe_all():
    bus = EventBus()
    q = bus.subscribe_all()
    bus.publish_to_all("overview", {"a": 1})
    bus.publish_to_all("spread", {"b": 2})
    assert q.qsize() == 2


# --- Dashboard independence (SC-007) ---

def test_backend_continues_without_dashboard(fake_backend):
    """Backend state operations work with no dashboard instance."""
    state = fake_backend.get_dashboard_state()
    assert state is not None
    assert state["trading_status"] == "ACTIVE"
    positions = fake_backend.get_positions()
    assert len(positions) == 1
