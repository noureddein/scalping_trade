"""In-process async event bus for dashboard state notifications.

Backend modules publish events; the SSE live_feed subscribes.
Dict[str, list[asyncio.Queue]] keyed by event type.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EventBus:
    _subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = field(
        default_factory=dict
    )
    _event_counter: int = 0

    def subscribe(self, event_type: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subscribers.setdefault(event_type, []).append(q)
        return q

    def unsubscribe(self, event_type: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        subs = self._subscribers.get(event_type, [])
        try:
            subs.remove(q)
        except ValueError:
            pass

    def publish(self, event_type: str, data: dict[str, Any]) -> int:
        self._event_counter += 1
        event_id = self._event_counter
        payload = {"id": event_id, "type": event_type, "data": data}
        for q in self._subscribers.get(event_type, []):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass
        return event_id

    def subscribe_all(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1024)
        self._subscribers.setdefault("*", []).append(q)
        return q

    def publish_to_all(self, event_type: str, data: dict[str, Any]) -> int:
        event_id = self.publish(event_type, data)
        payload = {"id": event_id, "type": event_type, "data": data}
        for q in self._subscribers.get("*", []):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass
        return event_id
