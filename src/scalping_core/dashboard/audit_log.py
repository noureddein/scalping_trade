"""Audit logging for configuration changes (T005).

Persists AuditLogEntry atomically with every config change (FR-008).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

_LOGGER = logging.getLogger(__name__)

_DEFAULT_OPERATOR = "operator"


class _Encoder(json.JSONEncoder):
    def default(self, o: object) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, uuid.UUID):
            return str(o)
        return super().default(o)


class AuditLogger:
    """Writes audit log entries to the backend store."""

    def __init__(self, backend: Any) -> None:
        self._backend = backend
        self._entries: list[dict[str, Any]] = []

    def log_change(
        self,
        *,
        account_id: str,
        parameter_name: str,
        old_value: str,
        new_value: str,
        change_source: str = "dashboard",
        operator_id: str = _DEFAULT_OPERATOR,
    ) -> dict[str, Any]:
        entry = {
            "entry_id": str(uuid.uuid4()),
            "account_id": account_id,
            "parameter_name": parameter_name,
            "old_value": old_value,
            "new_value": new_value,
            "change_source": change_source,
            "operator_id": operator_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._entries.append(entry)
        try:
            if hasattr(self._backend, "persist_audit_entry"):
                self._backend.persist_audit_entry(entry)
        except Exception:
            _LOGGER.exception("failed to persist audit entry to DB")
        return entry

    def get_entries(
        self, *, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        if hasattr(self._backend, "get_audit_entries"):
            try:
                return self._backend.get_audit_entries(limit=limit, offset=offset)
            except Exception:
                _LOGGER.exception("failed to read audit entries from DB")
        start = max(0, len(self._entries) - offset - limit)
        end = len(self._entries) - offset
        return list(reversed(self._entries[max(0, start):max(0, end)]))
