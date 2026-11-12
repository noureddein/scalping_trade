"""Dataset loading, validation, hashing, and data source evaluation (T003, T005, T006, T007)."""
from __future__ import annotations

import csv
import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


class DataSourceGateError(Exception):
    """Raised when no approved data source exists for a pair."""


class DatasetHashMismatchError(Exception):
    """Raised when dataset file hash doesn't match stored hash."""


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def code_hash(module_paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(module_paths):
        with open(p, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def config_hash(config: dict[str, Any]) -> str:
    canonical = json.dumps(config, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _detect_missing_intervals(
    timestamps: list[datetime], max_gap_seconds: float = 60.0
) -> tuple[int, list[dict[str, str]]]:
    gaps = 0
    quality_flags: list[dict[str, str]] = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds()
        if delta > max_gap_seconds:
            gaps += 1
            quality_flags.append({
                "type": "missing_interval",
                "from": timestamps[i - 1].isoformat(),
                "to": timestamps[i].isoformat(),
                "gap_seconds": str(delta),
            })
    return gaps, quality_flags


def load_dataset(
    file_path: Path,
    source_id: str,
    pair: str,
) -> dict[str, Any]:
    fh = file_hash(file_path)
    timestamps: list[datetime] = []
    tick_count = 0

    with open(file_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if "bid" not in row or "ask" not in row or "timestamp" not in row:
                raise ValueError(f"tick missing required fields (bid, ask, timestamp): {row}")
            ts = datetime.fromisoformat(row["timestamp"])
            timestamps.append(ts)
            tick_count += 1

    if tick_count == 0:
        raise ValueError("dataset contains no ticks")

    missing_count, quality_flags = _detect_missing_intervals(timestamps)

    return {
        "dataset_id": str(uuid.uuid4()),
        "source_id": source_id,
        "file_path": str(file_path),
        "file_hash": fh,
        "pair": pair,
        "start_time": timestamps[0].isoformat(),
        "end_time": timestamps[-1].isoformat(),
        "tick_count": tick_count,
        "missing_intervals": missing_count,
        "quality_flags": quality_flags,
        "loaded_at": datetime.now(timezone.utc).isoformat(),
    }


def verify_dataset_hash(file_path: Path, expected_hash: str) -> None:
    actual = file_hash(file_path)
    if actual != expected_hash:
        raise DatasetHashMismatchError(
            f"hash mismatch: expected {expected_hash}, got {actual}"
        )


class ContractSpecMismatchError(Exception):
    """Contract specs (point, digits, pip_value) don't match approved source."""


def evaluate_data_source(
    file_path: Path,
    *,
    provider: str,
    pair: str,
    licensing_notes: str,
    interval_type: str,
    tz: str,
    point: str | None = None,
    digits: int | None = None,
    pip_value: str | None = None,
) -> dict[str, Any]:
    fh = file_hash(file_path)
    timestamps: list[datetime] = []
    has_bid = False
    has_ask = False
    tick_count = 0

    with open(file_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tick_count += 1
            if "bid" in row:
                has_bid = True
            if "ask" in row:
                has_ask = True
            if "timestamp" in row:
                timestamps.append(datetime.fromisoformat(row["timestamp"]))

    missing_count, _ = _detect_missing_intervals(timestamps)
    bid_ask = "real" if (has_bid and has_ask) else "missing"
    quality_score = Decimal("1.0")
    if not has_bid or not has_ask:
        quality_score -= Decimal("0.3")
    if missing_count > 0:
        quality_score -= Decimal("0.1") * min(missing_count, 5)

    return {
        "provider": provider,
        "pair": pair,
        "licensing_notes": licensing_notes,
        "interval_type": interval_type,
        "timezone": tz,
        "bid_ask_availability": bid_ask,
        "tick_count": tick_count,
        "missing_period_count": missing_count,
        "file_hash": fh,
        "quality_score": str(max(quality_score, Decimal("0"))),
        "contract_specs": {
            "point": point,
            "digits": digits,
            "pip_value": pip_value,
        },
    }


class DataSourceRegistry:
    """In-memory registry of approved data sources (gate entity)."""

    def __init__(self) -> None:
        self._sources: dict[str, dict[str, Any]] = {}

    def approve(self, evaluation: dict[str, Any], *, approved_by: str, notes: str) -> dict[str, Any]:
        record = {
            "source_id": str(uuid.uuid4()),
            "provider": evaluation["provider"],
            "pair": evaluation["pair"],
            "interval_type": evaluation["interval_type"],
            "timezone": evaluation["timezone"],
            "quality_score": evaluation["quality_score"],
            "licensing_notes": evaluation["licensing_notes"],
            "approval_date": datetime.now(timezone.utc).date().isoformat(),
            "approval_notes": notes,
            "approved_by": approved_by,
            "contract_specs": evaluation.get("contract_specs", {}),
        }
        self._sources[evaluation["pair"]] = record
        return record

    def validate_contract_specs(
        self, pair: str, *, point: str | None, digits: int | None, pip_value: str | None
    ) -> None:
        source = self.require(pair)
        approved = source.get("contract_specs", {})
        mismatches: list[str] = []
        for field, given, stored in [
            ("point", point, approved.get("point")),
            ("digits", digits, approved.get("digits")),
            ("pip_value", pip_value, approved.get("pip_value")),
        ]:
            if stored is not None and given is not None and str(given) != str(stored):
                mismatches.append(f"{field}: expected {stored}, got {given}")
        if mismatches:
            raise ContractSpecMismatchError(
                f"contract specification mismatch for {pair}: {'; '.join(mismatches)}"
            )

    def get(self, pair: str) -> dict[str, Any] | None:
        return self._sources.get(pair)

    def require(self, pair: str) -> dict[str, Any]:
        source = self.get(pair)
        if source is None:
            raise DataSourceGateError(f"no approved data source for {pair}")
        return source
