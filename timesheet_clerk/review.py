"""Deterministic review helpers used by Streamlit.

No mapping or autonomy decisions are made here. The helpers only compare user
review state with the agent proposal and maintain the same-day sequential
planned timeline after duration edits.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

from .contracts import utc_now

_REVIEW_FIELDS = (
    "planned_duration_seconds",
    "planned_start",
    "planned_end",
    "booking_mode",
    "assignment",
    "direct_mapping",
    "ignored",
)


def source_fingerprint(entry: dict[str, Any]) -> str:
    payload = {
        "clockify_source_ids": entry.get("clockify_source_ids") or [],
        "date": entry.get("date"),
        "source": entry.get("source") or {},
        "original_duration_seconds": entry.get("original_duration_seconds"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def changed_fields(proposal: dict[str, Any], reviewed: dict[str, Any]) -> list[str]:
    return [field for field in _REVIEW_FIELDS if proposal.get(field) != reviewed.get(field)]


def feedback_event(
    *,
    plan_id: str,
    proposal: dict[str, Any],
    reviewed: dict[str, Any],
    reason: str = "",
    outcome: str | None = None,
) -> dict[str, Any]:
    changes = changed_fields(proposal, reviewed)
    resolved_outcome = outcome or ("corrected" if changes else "confirmed")
    if reviewed.get("ignored"):
        resolved_outcome = "skipped"
    return {
        "event_id": str(uuid.uuid4()),
        "timestamp": utc_now(),
        "plan_id": plan_id,
        "entry_id": reviewed["entry_id"],
        "source_fingerprint": source_fingerprint(proposal),
        "agent_proposal": _review_projection(proposal),
        "reviewed_values": _review_projection(reviewed),
        "changed_fields": changes,
        "reason": reason.strip(),
        "original_mapping_source": deepcopy(proposal.get("mapping_source")),
        "original_tiers": deepcopy(proposal.get("field_tiers") or {"overall": proposal.get("tier") or proposal.get("overall_tier")}),
        "outcome": resolved_outcome,
    }


def apply_review(plan: dict[str, Any], entry_id: str, reviewed_values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return updated plan, original proposal and reviewed entry.

    A duration change shifts only later entries on the same calendar day.
    """
    updated = deepcopy(plan)
    index = next((i for i, row in enumerate(updated["entries"]) if row.get("entry_id") == entry_id), None)
    if index is None:
        raise KeyError(entry_id)
    original = deepcopy(updated["entries"][index])
    entry = updated["entries"][index]
    for key in _REVIEW_FIELDS:
        if key in reviewed_values:
            entry[key] = deepcopy(reviewed_values[key])
    entry["review_state"] = "skipped" if entry.get("ignored") else ("corrected" if changed_fields(original, entry) else "confirmed")
    updated["status"] = "IN_REVIEW"
    if entry.get("planned_duration_seconds") != original.get("planned_duration_seconds"):
        _reflow_day(updated["entries"], index)
    return updated, original, deepcopy(entry)


def _reflow_day(entries: list[dict[str, Any]], changed_index: int) -> None:
    changed = entries[changed_index]
    day = changed.get("date")
    changed_start = _parse_datetime(changed.get("planned_start"))
    if not day or changed_start is None:
        return
    duration = float(changed.get("planned_duration_seconds") or 0)
    changed_end = changed_start + timedelta(seconds=duration)
    changed["planned_end"] = _format_like(changed_end, changed.get("planned_start"))
    cursor = changed_end
    for row in entries[changed_index + 1 :]:
        if row.get("date") != day:
            continue
        old_start = _parse_datetime(row.get("planned_start"))
        old_end = _parse_datetime(row.get("planned_end"))
        if old_start is None:
            continue
        row_duration = float(row.get("planned_duration_seconds") or 0)
        if row_duration <= 0 and old_end is not None:
            row_duration = max(0.0, (old_end - old_start).total_seconds())
        row["planned_start"] = _format_like(cursor, row.get("planned_start"))
        cursor = cursor + timedelta(seconds=row_duration)
        row["planned_end"] = _format_like(cursor, row.get("planned_end") or row.get("planned_start"))


def _review_projection(entry: dict[str, Any]) -> dict[str, Any]:
    keys = ("entry_id",) + _REVIEW_FIELDS
    return {key: deepcopy(entry.get(key)) for key in keys if key in entry}


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_like(value: datetime, example: Any) -> str:
    result = value.isoformat()
    if str(example or "").endswith("Z"):
        return result.replace("+00:00", "Z")
    return result
