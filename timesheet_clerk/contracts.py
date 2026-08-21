"""Stable Timesheet Clerk domain contracts.

This module validates structure only. It intentionally contains no mapping,
confidence or autonomy policy; those remain the HERMES skill's responsibility.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

PLAN_SCHEMA_VERSION = 1
PLAN_STATUSES = {
    "GENERATING", "DRAFT", "IN_REVIEW", "APPROVED", "BOOKING", "BOOKED",
    "SUPERSEDED", "FAILED",
}
ENTRY_TIERS = {"AUTO", "PROPOSE", "ASK"}
BOOKING_MODES = {"assignment", "direct"}
REVIEW_OUTCOMES = {"confirmed", "corrected", "skipped"}


class ContractError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise ContractError("plan must be an object")
    result = deepcopy(plan)
    if result.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise ContractError(f"schema_version must be {PLAN_SCHEMA_VERSION}")
    _required_text(result, "plan_id")
    revision = result.get("revision")
    if not isinstance(revision, int) or revision < 1:
        raise ContractError("revision must be an integer >= 1")
    status = result.get("status")
    if status not in PLAN_STATUSES:
        raise ContractError(f"invalid plan status: {status!r}")
    week = result.get("week")
    if not isinstance(week, dict):
        raise ContractError("week must be an object")
    _required_text(week, "monday")
    _required_text(week, "sunday")
    for key in ("contract_hours_default", "target_hours"):
        value = result.get(key)
        if not isinstance(value, (int, float)) or value < 0:
            raise ContractError(f"{key} must be a number >= 0")
    entries = result.get("entries")
    if not isinstance(entries, list):
        raise ContractError("entries must be an array")
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        validate_entry(entry, index=index)
        entry_id = entry["entry_id"]
        if entry_id in seen:
            raise ContractError(f"duplicate entry_id: {entry_id}")
        seen.add(entry_id)
    return result


def validate_entry(entry: dict[str, Any], *, index: int | None = None) -> None:
    prefix = f"entries[{index}]" if index is not None else "entry"
    if not isinstance(entry, dict):
        raise ContractError(f"{prefix} must be an object")
    for key in ("entry_id", "date"):
        if not str(entry.get(key) or "").strip():
            raise ContractError(f"{prefix}.{key} is required")
    source_ids = entry.get("clockify_source_ids")
    if not isinstance(source_ids, list) or not source_ids:
        raise ContractError(f"{prefix}.clockify_source_ids must be a non-empty array")
    duration = entry.get("planned_duration_seconds")
    if not isinstance(duration, (int, float)) or duration < 0:
        raise ContractError(f"{prefix}.planned_duration_seconds must be >= 0")
    mode = entry.get("booking_mode")
    if mode not in BOOKING_MODES:
        raise ContractError(f"{prefix}.booking_mode must be assignment or direct")
    tier = entry.get("tier") or entry.get("overall_tier")
    if tier not in ENTRY_TIERS:
        raise ContractError(f"{prefix}.tier must be AUTO, PROPOSE or ASK")

    # DRAFT/IN_REVIEW plans may deliberately contain unresolved targets for ASK
    # or PROPOSE entries. AUTO entries and reviewed entries must be complete.
    must_be_complete = tier == "AUTO" or entry.get("review_state") in {"confirmed", "corrected"}
    if mode == "assignment":
        target = entry.get("assignment")
        if target is not None and not isinstance(target, dict):
            raise ContractError(f"{prefix}.assignment must be an object")
        if must_be_complete and (not isinstance(target, dict) or not str(target.get("id") or "").strip()):
            raise ContractError(f"{prefix}.assignment.id is required for a resolved assignment entry")
    else:
        target = entry.get("direct_mapping")
        if target is not None and not isinstance(target, dict):
            raise ContractError(f"{prefix}.direct_mapping must be an object")
        if must_be_complete:
            if not isinstance(target, dict):
                raise ContractError(f"{prefix}.direct_mapping is required for a resolved direct entry")
            for key in ("project_id", "service_id", "hour_type_id"):
                if not str(target.get(key) or "").strip():
                    raise ContractError(f"{prefix}.direct_mapping.{key} is required for a resolved direct entry")


def validate_feedback_event(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ContractError("feedback event must be an object")
    result = deepcopy(event)
    for key in ("event_id", "timestamp", "plan_id", "entry_id", "source_fingerprint"):
        _required_text(result, key)
    if result.get("outcome") not in REVIEW_OUTCOMES:
        raise ContractError("feedback outcome must be confirmed, corrected or skipped")
    if not isinstance(result.get("changed_fields", []), list):
        raise ContractError("changed_fields must be an array")
    return result


def new_plan_skeleton(*, plan_id: str, monday: str, sunday: str, target_hours: float = 36.0) -> dict[str, Any]:
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "plan_id": plan_id,
        "revision": 1,
        "status": "DRAFT",
        "generated_at": utc_now(),
        "week": {"monday": monday, "sunday": sunday},
        "contract_hours_default": 36.0,
        "target_hours": float(target_hours),
        "entries": [],
    }


def _required_text(obj: dict[str, Any], key: str) -> None:
    if not str(obj.get(key) or "").strip():
        raise ContractError(f"{key} is required")
