"""Consolidate same-day booking rows without losing Clockify source coverage."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


_REVIEWED = {"confirmed", "corrected"}
_TIER_RANK = {"AUTO": 0, "PROPOSE": 1, "ASK": 2}


def consolidate_reviewed_entries(plan: dict[str, Any], *, preferred_entry_id: str | None = None, auto_only: bool = False, reflow: bool = True) -> dict[str, Any]:
    """Merge same-day rows that resolve to the exact same Simplicate target."""
    result = deepcopy(plan)
    entries = list(result.get("entries") or [])
    entries.sort(key=lambda row: (
        str(row.get("date") or ""),
        1 if row.get("ignored") else 0,
        str(row.get("planned_start") or ""),
        str(row.get("entry_id") or ""),
    ))

    merged: list[dict[str, Any]] = []
    positions: dict[tuple[Any, ...], int] = {}
    for row in entries:
        current = deepcopy(row)
        key = _merge_key(current, auto_only=auto_only)
        if key is not None and key in positions:
            idx = positions[key]
            merged[idx] = _merge_pair(merged[idx], current, preferred_entry_id=preferred_entry_id)
            continue
        if key is not None:
            positions[key] = len(merged)
        merged.append(current)

    result["entries"] = merged
    if reflow and len(merged) != len(entries):
        from .scheduling import reflow_plan_days
        result = reflow_plan_days(result, consolidate_auto=False)
    return result


def _merge_key(entry: dict[str, Any], *, auto_only: bool) -> tuple[Any, ...] | None:
    if not _merge_eligible(entry, auto_only=auto_only):
        return None
    return (str(entry.get("date") or ""),) + _booking_signature(entry)


def _merge_eligible(entry: dict[str, Any], *, auto_only: bool) -> bool:
    if entry.get("ignored") or entry.get("review_state") == "skipped":
        return False
    if entry.get("reconciliation_state") == "BOOKED":
        return False
    if entry.get("mapping_state") != "RESOLVED":
        return False
    tier = str(entry.get("tier") or entry.get("overall_tier") or "ASK").upper()
    if tier == "AUTO":
        return True
    if auto_only:
        return False
    return entry.get("review_state") in _REVIEWED


def _merge_pair(left: dict[str, Any], right: dict[str, Any], *, preferred_entry_id: str | None) -> dict[str, Any]:
    preferred = None
    if preferred_entry_id and preferred_entry_id in {left.get("entry_id"), right.get("entry_id")}:
        preferred = right if right.get("entry_id") == preferred_entry_id else left
    base = deepcopy(preferred or left)

    source_ids: list[str] = []
    for row in (left, right):
        for source_id in row.get("clockify_source_ids") or []:
            value = str(source_id)
            if value and value not in source_ids:
                source_ids.append(value)

    base["clockify_source_ids"] = source_ids
    base["original_duration_seconds"] = float(left.get("original_duration_seconds") or 0) + float(right.get("original_duration_seconds") or 0)
    base["planned_duration_seconds"] = float(left.get("planned_duration_seconds") or 0) + float(right.get("planned_duration_seconds") or 0)
    base["review_state"] = _merged_review_state(left, right)
    base["tier"] = _stricter_tier(left, right)
    base["overall_tier"] = base["tier"]
    base["consolidated"] = True
    base["consolidated_entry_ids"] = _unique_strings(
        list(left.get("consolidated_entry_ids") or [left.get("entry_id")])
        + list(right.get("consolidated_entry_ids") or [right.get("entry_id")])
    )
    base["source"] = _merged_source(left, right, base.get("source") or {})
    base["source_fingerprint"] = _fingerprint(base)
    return base


def _merged_review_state(left: dict[str, Any], right: dict[str, Any]) -> str | None:
    states = {left.get("review_state"), right.get("review_state")}
    if "corrected" in states:
        return "corrected"
    if "confirmed" in states:
        return "confirmed"
    return None


def _merged_source(left: dict[str, Any], right: dict[str, Any], base_source: dict[str, Any]) -> dict[str, Any]:
    source = deepcopy(base_source)
    descriptions: list[str] = []
    for row in (left, right):
        text = str((row.get("source") or {}).get("description") or "").strip()
        if text and text not in descriptions:
            descriptions.append(text)
    if descriptions:
        source["description"] = " + ".join(descriptions)
    return source


def _booking_signature(entry: dict[str, Any]) -> tuple[Any, ...]:
    mode = str(entry.get("booking_mode") or "")
    billable = _is_billable(entry)
    if mode == "assignment":
        assignment = entry.get("assignment") or {}
        return (mode, _plain_id(assignment), billable)
    mapping = entry.get("direct_mapping") or {}
    return (
        mode,
        _plain_id(mapping.get("customer_id")),
        _plain_id(mapping.get("project_id")),
        _plain_id(mapping.get("service_id")),
        _plain_id(mapping.get("hour_type_id")),
        billable,
    )


def _is_billable(entry: dict[str, Any]) -> bool:
    if entry.get("billable") is False:
        return False
    mapping = entry.get("direct_mapping") or {}
    return mapping.get("billable") is not False


def _stricter_tier(left: dict[str, Any], right: dict[str, Any]) -> str:
    values = [str(left.get("tier") or left.get("overall_tier") or "ASK").upper(), str(right.get("tier") or right.get("overall_tier") or "ASK").upper()]
    return max(values, key=lambda value: _TIER_RANK.get(value, 2))


def _fingerprint(entry: dict[str, Any]) -> str:
    payload = {
        "clockify_source_ids": entry.get("clockify_source_ids") or [],
        "date": entry.get("date"),
        "source": entry.get("source") or {},
        "original_duration_seconds": entry.get("original_duration_seconds"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _plain_id(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("id")
    text = str(value or "")
    return text.split(":", 1)[1] if ":" in text else text


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "")
        if text and text not in result:
            result.append(text)
    return result
