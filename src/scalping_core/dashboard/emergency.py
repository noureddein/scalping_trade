"""Emergency stop handler (T022).

POST /api/emergency-stop: transitions system to DRAINING via
existing Phase 5 daily risk state machine (FR-007). Requires
{"confirm": true}. Returns 409 if already DRAINING or DISABLED.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from aiohttp import web

from .event_bus import EventBus

_LOGGER = logging.getLogger(__name__)


class _Encoder(json.JSONEncoder):
    def default(self, o: object) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, UUID):
            return str(o)
        return super().default(o)


def _json_response(data: Any, *, status: int = 200) -> web.Response:
    return web.Response(
        text=json.dumps(data, cls=_Encoder),
        content_type="application/json",
        status=status,
    )


async def handle_emergency_stop(
    request: web.Request, backend: Any, bus: EventBus
) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return _json_response({"error": "invalid JSON"}, status=400)

    if body.get("confirm") is not True:
        return _json_response(
            {"error": "confirm must be true"}, status=400
        )

    try:
        result = backend.emergency_stop()
    except ValueError as e:
        return _json_response({"error": str(e)}, status=409)
    except Exception:
        _LOGGER.exception("emergency stop failed")
        return _json_response({"error": "backend unavailable"}, status=503)

    bus.publish_to_all("risk-state", result)
    return _json_response(result)
