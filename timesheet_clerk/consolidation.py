"""Consolidate adjacent reviewed booking rows without losing Clockify source coverage."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from typing import Any


_REVIEWED = {"confirmed", "corrected"}
_TIER_RANK = {"AUTO": 0, "PROPOSE": 1, "ASK": 2}


def consolidate_reviewed_entries(plan: dict[str, Any], *, preferred_entry_id: str | None = None) -> dict[str, Any]:
    """Merge adjacent functionally identical reviewed rows.

    Consolidation is deliberately conservative. Both rows must be reviewed,
    resolved, non-ignored, contiguous in planned time, point at exactly the same
    booking target and represent the same Clockify work context.
    """
    result = deepcopy(plan)
    entries = list(result.get("entries") or [])
    entries.sort(key=lambda row: (
        str(row.get("date") or ""),
        1 if row.get("ignored") else 0,
        str(row.get("planned_start") or ""),
        str(row.get("entry_id") or ""),
    ))

    merged: list[dict[str, Any]] = []
    for row in entries:
        current = deepcopy(row)
        if merged and _can_merge(merged[-1], current):
            merged[-1] = _merge_pair(merged[-1], current, preferred_entry_id=preferred_entry_id)
        else:
            merged.append(current)

    result["entries"] = merged
    return result


def _can_merge(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("ignored") or right.get("ignored"):
        return False
    if left.get("reconciliation_state") == "BOOKED" or right.get("reconciliation_state") == "BOOKED":
        return False
    if left.get("review_state") not in _REVIEWED or right.get("review_state") not in _REVIEWED:
        return False
    if left.get("mapping_state") != "RESOLVED" or right.get("mapping_state") != "RESOLVED":
        return False
    if str(left.get("date") or "") != str(right.get("date") or ""):
        return False
    if _parse(left.get("planned_end")) != _parse(right.get("planned_start")):
        return False
    if _booking_signature(left) != _booking_signature(right):
        return False
    if _source_signature(left) != _source_signature(right):
        return False
    return True


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
    base["planned_start"] = left.get("planned_start")
    base["planned_end"] = right.get("planned_end")
    base["review_state"] = "corrected" if "corrected" in {left.get("review_state"), right.get("review_state")} else "confirmed"
    base["tier"] = _stricter_tier(left, right)
    base["overall_tier"] = base["tier"]
    base["consolidated"] = True
    base["consolidated_entry_ids"] = _unique_strings(
        list(left.get("consolidated_entry_ids") or [left.get("entry_id")])
        + list(right.get("consolidated_entry_ids") or [right.get("entry_id")])
    )
    base["source_fingerprint"] = _fingerprint(base)
    return base


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


def _source_signature(entry: dict[str, Any]) -> tuple[str, str, str]:
    source = entry.get("source") or {}
    description = " ".join(str(source.get("description") or "").casefold().split())
    client = source.get("client") or {}
    project = source.get("project") or {}
    return (description, _plain_id(client) or _name(client), _plain_id(project) or _name(project))


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


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _plain_id(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("id")
    text = str(value or "")
    return text.split(":", 1)[1] if ":" in text else text


def _name(value: Any) -> str:
    if not isinstance(value, dict):
        return str(value or "").casefold()
    return str(value.get("name") or value.get("title") or value.get("label") or "").casefold()


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "")
        if text and text not in result:
            result.append(text)
    return result
