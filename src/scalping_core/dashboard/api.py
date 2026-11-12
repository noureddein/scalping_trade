"""Dashboard HTTP API server (T003).

aiohttp application bound to 127.0.0.1. Routes for all dashboard
endpoints from contracts/dashboard-api.md. Returns 503 when backend
state is unavailable. Serves static files from src/static/dashboard/.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from aiohttp import web

from .audit_log import AuditLogger
from .event_bus import EventBus

_LOGGER = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parents[3] / "static" / "dashboard"


class _DecimalEncoder(json.JSONEncoder):
    def default(self, o: object) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, uuid.UUID):
            return str(o)
        return super().default(o)


def _json_response(data: Any, *, status: int = 200) -> web.Response:
    return web.Response(
        text=json.dumps(data, cls=_DecimalEncoder),
        content_type="application/json",
        status=status,
    )


class DashboardApp:
    """Dashboard HTTP API application.

    Accepts a `backend` object that provides access to Phase 2–5 state.
    The backend protocol is duck-typed — any object exposing the expected
    methods works (including test fakes).
    """

    def __init__(self, backend: Any, event_bus: EventBus | None = None) -> None:
        self.backend = backend
        self.bus = event_bus or EventBus()
        self.audit = AuditLogger(backend)
        self.app = web.Application()
        self._register_routes()

    def _register_routes(self) -> None:
        r = self.app.router
        r.add_get("/api/overview", self.get_overview)
        r.add_get("/api/pairs", self.get_pairs)
        r.add_post("/api/pairs", self.add_pair)
        r.add_put("/api/pairs/{pair}/enabled", self.set_pair_enabled)
        r.add_delete("/api/pairs/{pair}", self.delete_pair)
        r.add_get("/api/pairs/{pair}/spread", self.get_pair_spread)
        r.add_get("/api/risk-config", self.get_risk_config)
        r.add_put("/api/risk-config/{parameter}", self.update_risk_config)
        r.add_get("/api/positions", self.get_positions)
        r.add_get("/api/broker-accounts", self.get_broker_accounts)
        r.add_get("/api/strategy-performance", self.get_strategy_performance)
        r.add_get("/api/execution-stats", self.get_execution_stats)
        r.add_get("/api/history", self.get_history)
        r.add_get("/api/risk-events", self.get_risk_events)
        r.add_get("/api/audit-log", self.get_audit_log)
        r.add_get("/api/system-logs", self.get_system_logs)
        r.add_post("/api/emergency-stop", self.emergency_stop)
        r.add_get("/api/stream", self.stream)
        if _STATIC_DIR.is_dir():
            r.add_static("/", _STATIC_DIR, name="static")

    # --- US1: Overview (T006) ---

    async def get_overview(self, request: web.Request) -> web.Response:
        try:
            state = self.backend.get_dashboard_state()
        except Exception:
            _LOGGER.exception("backend unavailable for overview")
            return _json_response({"error": "backend unavailable"}, status=503)
        if state is None:
            return _json_response({"error": "backend unavailable"}, status=503)
        return _json_response(state)

    # --- US2: Pairs (T010) ---

    async def get_pairs(self, request: web.Request) -> web.Response:
        try:
            pairs = self.backend.get_pairs()
        except Exception:
            _LOGGER.exception("backend unavailable for pairs")
            return _json_response({"error": "backend unavailable"}, status=503)
        return _json_response(pairs)

    async def add_pair(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return _json_response({"error": "invalid JSON"}, status=400)
        canonical = body.get("canonical_pair", "").strip().upper()
        broker_sym = body.get("broker_symbol", "").strip()
        if not canonical or not broker_sym:
            return _json_response(
                {"error": "canonical_pair and broker_symbol are required"}, status=400
            )
        try:
            pair_data = self.backend.add_pair(canonical, broker_sym)
        except ValueError as e:
            return _json_response({"error": str(e)}, status=400)
        self.audit.log_change(
            account_id=self.backend.get_account_id(),
            parameter_name=f"pair.{canonical}",
            old_value="null",
            new_value=json.dumps({"canonical_pair": canonical, "broker_symbol": broker_sym}),
        )
        self.bus.publish_to_all("pair-update", pair_data)
        return _json_response(pair_data, status=201)

    async def set_pair_enabled(self, request: web.Request) -> web.Response:
        pair = request.match_info["pair"].upper()
        try:
            body = await request.json()
        except Exception:
            return _json_response({"error": "invalid JSON"}, status=400)
        enabled = body.get("enabled")
        if enabled is None or not isinstance(enabled, bool):
            return _json_response({"error": "enabled (bool) is required"}, status=400)
        try:
            pair_data = self.backend.set_pair_enabled(pair, enabled)
        except KeyError:
            return _json_response({"error": "pair not found"}, status=404)
        self.audit.log_change(
            account_id=self.backend.get_account_id(),
            parameter_name=f"pair.{pair}.trading_enabled",
            old_value=json.dumps(not enabled),
            new_value=json.dumps(enabled),
        )
        self.bus.publish_to_all("pair-update", pair_data)
        return _json_response(pair_data)

    async def delete_pair(self, request: web.Request) -> web.Response:
        pair = request.match_info["pair"].upper()
        try:
            self.backend.delete_pair(pair)
        except KeyError:
            return _json_response({"error": "pair not found"}, status=404)
        except ValueError as e:
            return _json_response({"error": str(e)}, status=409)
        self.audit.log_change(
            account_id=self.backend.get_account_id(),
            parameter_name=f"pair.{pair}",
            old_value=json.dumps({"canonical_pair": pair}),
            new_value="null",
        )
        self.bus.publish_to_all("pair-update", {"canonical_pair": pair, "removed": True})
        return web.Response(status=204)

    # --- US3: Spread (T013) ---

    async def get_pair_spread(self, request: web.Request) -> web.Response:
        pair = request.match_info["pair"].upper()
        try:
            spread = self.backend.get_spread_monitor(pair)
        except KeyError:
            return _json_response({"error": "pair not found"}, status=404)
        except Exception:
            _LOGGER.exception("backend unavailable for spread")
            return _json_response({"error": "backend unavailable"}, status=503)
        return _json_response(spread)

    # --- US4: Risk Config (T016, T017) ---

    async def get_risk_config(self, request: web.Request) -> web.Response:
        try:
            config = self.backend.get_risk_config()
        except Exception:
            _LOGGER.exception("backend unavailable for risk config")
            return _json_response({"error": "backend unavailable"}, status=503)
        return _json_response(config)

    _READ_ONLY_PARAMS = frozenset({"lot_size", "trading_schedule"})

    _VALIDATORS: dict[str, Any] = {
        "daily_profit_limit": lambda v: isinstance(v, (int, float, str)) and Decimal(str(v)) > 0,
        "daily_loss_limit": lambda v: isinstance(v, (int, float, str)) and Decimal(str(v)) > 0,
        "max_loss_per_trade": lambda v: isinstance(v, (int, float, str)) and Decimal(str(v)) > 0,
        "take_profit_range": lambda v: isinstance(v, (int, float, str)) and Decimal(str(v)) > 0,
        "spread_thresholds": lambda v: isinstance(v, (int, float, str)) and Decimal(str(v)) > 0,
        "position_limits": lambda v: isinstance(v, int) and v >= 1,
    }

    async def update_risk_config(self, request: web.Request) -> web.Response:
        parameter = request.match_info["parameter"]
        if parameter in self._READ_ONLY_PARAMS:
            return _json_response(
                {"error": f"{parameter} is read-only"}, status=403
            )
        try:
            body = await request.json()
        except Exception:
            return _json_response({"error": "invalid JSON"}, status=400)
        value = body.get("value")
        if value is None:
            return _json_response({"error": "value is required"}, status=400)
        validator = self._VALIDATORS.get(parameter)
        if validator is None:
            return _json_response({"error": f"unknown parameter: {parameter}"}, status=400)
        try:
            valid = validator(value)
        except Exception:
            valid = False
        if not valid:
            return _json_response(
                {"error": f"invalid value for {parameter}: {value}"}, status=400
            )
        if parameter == "max_loss_per_trade":
            try:
                config = self.backend.get_risk_config()
                limit = abs(Decimal(str(config["daily_loss_limit"]["value"])))
                if Decimal(str(value)) > limit:
                    return _json_response(
                        {"error": f"max_loss_per_trade ({value}) exceeds daily_loss_limit ({limit})"},
                        status=400,
                    )
            except (KeyError, TypeError):
                pass
        account_id = self.backend.get_account_id()
        if hasattr(self.backend, "update_risk_config_with_audit"):
            try:
                old_value, new_value = self.backend.update_risk_config_with_audit(
                    parameter, value, account_id=account_id, operator_id="operator",
                )
            except ValueError as e:
                return _json_response({"error": str(e)}, status=400)
            except Exception:
                _LOGGER.exception("failed to update risk config (atomic)")
                return _json_response({"error": "backend unavailable"}, status=503)
        else:
            try:
                old_value, new_value = self.backend.update_risk_config(parameter, value)
            except ValueError as e:
                return _json_response({"error": str(e)}, status=400)
            except Exception:
                _LOGGER.exception("failed to update risk config")
                return _json_response({"error": "backend unavailable"}, status=503)
            self.audit.log_change(
                account_id=account_id,
                parameter_name=parameter,
                old_value=json.dumps(old_value, cls=_DecimalEncoder),
                new_value=json.dumps(new_value, cls=_DecimalEncoder),
            )
        return _json_response({
            "parameter": parameter,
            "old_value": old_value,
            "new_value": new_value,
            "applied": True,
        })

    # --- US5: Positions (T019) ---

    async def get_positions(self, request: web.Request) -> web.Response:
        try:
            positions = self.backend.get_positions()
        except Exception:
            _LOGGER.exception("backend unavailable for positions")
            return _json_response({"error": "backend unavailable"}, status=503)
        return _json_response(positions)

    # --- FR-006: Broker accounts, strategy performance, execution stats (T031) ---

    async def get_broker_accounts(self, request: web.Request) -> web.Response:
        try:
            accounts = self.backend.get_broker_accounts()
        except Exception:
            return _json_response({"error": "backend unavailable"}, status=503)
        return _json_response(accounts)

    async def get_strategy_performance(self, request: web.Request) -> web.Response:
        try:
            perf = self.backend.get_strategy_performance()
        except Exception:
            return _json_response({"error": "backend unavailable"}, status=503)
        return _json_response(perf)

    async def get_execution_stats(self, request: web.Request) -> web.Response:
        try:
            stats = self.backend.get_execution_stats()
        except Exception:
            return _json_response({"error": "backend unavailable"}, status=503)
        return _json_response(stats)

    # --- US6: Secondary modules (T023) ---

    async def get_history(self, request: web.Request) -> web.Response:
        try:
            history = self.backend.get_history()
        except Exception:
            return _json_response({"error": "backend unavailable"}, status=503)
        return _json_response(history)

    async def get_risk_events(self, request: web.Request) -> web.Response:
        limit = int(request.query.get("limit", "50"))
        offset = int(request.query.get("offset", "0"))
        try:
            events = self.backend.get_risk_events(limit=limit, offset=offset)
        except Exception:
            return _json_response({"error": "backend unavailable"}, status=503)
        return _json_response(events)

    async def get_audit_log(self, request: web.Request) -> web.Response:
        limit = int(request.query.get("limit", "50"))
        offset = int(request.query.get("offset", "0"))
        try:
            entries = self.audit.get_entries(limit=limit, offset=offset)
        except Exception:
            return _json_response({"error": "backend unavailable"}, status=503)
        return _json_response(entries)

    async def get_system_logs(self, request: web.Request) -> web.Response:
        limit = int(request.query.get("limit", "50"))
        level = request.query.get("level")
        try:
            logs = self.backend.get_system_logs(limit=limit, level=level)
        except Exception:
            return _json_response({"error": "backend unavailable"}, status=503)
        return _json_response(logs)

    # --- US6: Emergency stop (T022, delegated to emergency.py) ---

    async def emergency_stop(self, request: web.Request) -> web.Response:
        from .emergency import handle_emergency_stop
        return await handle_emergency_stop(request, self.backend, self.bus)

    # --- SSE stream (T004, delegated to live_feed.py) ---

    async def stream(self, request: web.Request) -> web.StreamResponse:
        from .live_feed import handle_stream
        return await handle_stream(request, self.bus, self.backend)


def create_app(backend: Any, event_bus: EventBus | None = None) -> DashboardApp:
    return DashboardApp(backend, event_bus)


def run_dashboard(backend: Any, *, host: str = "127.0.0.1", port: int = 8080) -> None:
    dashboard = create_app(backend)
    web.run_app(dashboard.app, host=host, port=port)
