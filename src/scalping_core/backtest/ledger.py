"""Acceptance criteria management and tried-configuration ledger (T009, T020)."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any


class NoCriteriaError(Exception):
    """No acceptance criteria defined — parameter selection refused."""


class AcceptanceCriteriaStore:
    """Manages owner-defined acceptance criteria (gate entity)."""

    def __init__(self) -> None:
        self._criteria: dict[str, dict[str, Any]] = {}

    def define(
        self,
        *,
        criteria_version: str,
        criteria: dict[str, Any],
        approved_by: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        if criteria_version in self._criteria:
            raise ValueError(f"criteria version {criteria_version} already exists")
        canonical = json.dumps(criteria, sort_keys=True, default=str)
        record = {
            "criteria_id": str(uuid.uuid4()),
            "criteria_version": criteria_version,
            "criteria_hash": hashlib.sha256(canonical.encode()).hexdigest(),
            "criteria_json": criteria,
            "approved_date": datetime.now(timezone.utc).date().isoformat(),
            "approved_by": approved_by,
            "notes": notes,
        }
        self._criteria[criteria_version] = record
        return record

    def get_latest(self) -> dict[str, Any] | None:
        if not self._criteria:
            return None
        return list(self._criteria.values())[-1]

    def require(self) -> dict[str, Any]:
        latest = self.get_latest()
        if latest is None:
            raise NoCriteriaError("no acceptance criteria defined — parameter selection refused (FR-012)")
        return latest

    def evaluate(self, result: dict[str, Any]) -> dict[str, Any]:
        criteria = self.require()
        thresholds = criteria["criteria_json"]
        meets = True
        details: list[dict[str, Any]] = []
        for key, threshold in sorted(thresholds.items()):
            actual = result.get(key)
            passed = actual is not None and float(actual) >= float(threshold)
            if not passed:
                meets = False
            details.append({"criterion": key, "threshold": str(threshold), "actual": str(actual), "passed": passed})
        return {
            "meets_criteria": meets,
            "criteria_version": criteria["criteria_version"],
            "criteria_hash": criteria["criteria_hash"],
            "details": details,
            "authorization_note": "This result does NOT authorize MT5 Strategy Tester, Demo orders, or live trading.",
        }


class TriedConfigurationLedger:
    """Append-only record of every tested parameter combination (T020)."""

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []

    def record(
        self,
        *,
        run_id: str,
        dataset_hash: str,
        code_hash: str,
        configuration_hash: str,
        configuration_json: dict[str, Any],
        strategy_name: str,
        summary_result: dict[str, Any],
    ) -> dict[str, Any]:
        entry = {
            "entry_id": str(uuid.uuid4()),
            "run_id": run_id,
            "dataset_hash": dataset_hash,
            "code_hash": code_hash,
            "configuration_hash": configuration_hash,
            "configuration_json": configuration_json,
            "strategy_name": strategy_name,
            "summary_result": summary_result,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)

    def is_non_comparable(self, dataset_hash: str, previous_dataset_hash: str) -> bool:
        return dataset_hash != previous_dataset_hash
