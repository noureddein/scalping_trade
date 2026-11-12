"""Server-Sent Events stream for live dashboard updates (T004).

GET /api/stream — event types: overview, spread, position, risk-state,
pair-update. Each event includes an id field for reconnection.
Heartbeat comment line every 15 seconds.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from aiohttp import web

from .event_bus import EventBus

_LOGGER = logging.getLogger(__name__)
_HEARTBEAT_INTERVAL = 15
# ponytail: bounded replay buffer, increase if clients miss events at scale
_MAX_REPLAY_BUFFER = 500


class _Encoder(json.JSONEncoder):
    def default(self, o: object) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, UUID):
            return str(o)
        return super().default(o)


class ReplayBuffer:
    """Bounded buffer of recent events for Last-Event-ID replay (T027)."""

    def __init__(self, maxlen: int = _MAX_REPLAY_BUFFER) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def append(self, event: dict[str, Any]) -> None:
        self._buffer.append(event)

    def events_after(self, event_id: int) -> list[dict[str, Any]]:
        result = []
        for ev in self._buffer:
            if ev.get("id", 0) > event_id:
                result.append(ev)
        return result

    @property
    def oldest_id(self) -> int:
        if not self._buffer:
            return 0
        return self._buffer[0].get("id", 0)


_replay_buffer = ReplayBuffer()


async def handle_stream(
    request: web.Request, bus: EventBus, backend: Any
) -> web.StreamResponse:
    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await response.prepare(request)

    last_event_id_str = request.headers.get("Last-Event-ID", "0")
    try:
        last_event_id = int(last_event_id_str)
    except (ValueError, TypeError):
        last_event_id = 0

    if last_event_id > 0:
        if last_event_id >= _replay_buffer.oldest_id and _replay_buffer.oldest_id > 0:
            missed = _replay_buffer.events_after(last_event_id)
            for ev in missed:
                await _write_event(response, ev)
        else:
            full_state = _get_full_state(backend)
            if full_state:
                await _write_event(response, full_state)

    q = bus.subscribe_all()
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=_HEARTBEAT_INTERVAL)
                _replay_buffer.append(event)
                await _write_event(response, event)
            except asyncio.TimeoutError:
                try:
                    await response.write(b": heartbeat\n\n")
                except (ConnectionResetError, ConnectionAbortedError):
                    break
            except (ConnectionResetError, ConnectionAbortedError):
                break
    finally:
        bus.unsubscribe("*", q)

    return response


async def _write_event(response: web.StreamResponse, event: dict[str, Any]) -> None:
    event_id = event.get("id", "")
    event_type = event.get("type", "message")
    data = json.dumps(event.get("data", {}), cls=_Encoder)
    msg = f"id: {event_id}\nevent: {event_type}\ndata: {data}\n\n"
    await response.write(msg.encode("utf-8"))


def _get_full_state(backend: Any) -> dict[str, Any] | None:
    try:
        state = backend.get_dashboard_state()
        if state is not None:
            return {"id": 0, "type": "overview", "data": state}
    except Exception:
        _LOGGER.debug("cannot get full state for reconnection")
    return None
