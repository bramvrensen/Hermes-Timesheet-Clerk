"""Deterministic review helpers used by Streamlit."""
from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from typing import Any

from .consolidation import consolidate_reviewed_entries
from .contracts import utc_now, validate_plan
from .scheduling import reflow_plan_days

_REVIEW_FIELDS = (
    "planned_duration_seconds", "planned_start", "planned_end", "booking_mode",
    "assignment", "direct_mapping", "ignored",
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


def feedback_event(*, plan_id: str, proposal: dict[str, Any], reviewed: dict[str, Any], reason: str = "", outcome: str | None = None) -> dict[str, Any]:
    changes = changed_fields(proposal, reviewed)
    resolved = outcome or ("corrected" if changes else "confirmed")
    if reviewed.get("ignored"):
        resolved = "skipped"
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
        "outcome": resolved,
    }


def _target_complete(entry: dict[str, Any]) -> bool:
    if entry.get("ignored"):
        return False
    if entry.get("booking_mode") == "assignment":
        return bool(str((entry.get("assignment") or {}).get("id") or "").strip())
    mapping = entry.get("direct_mapping") or {}
    return all(str(mapping.get(key) or "").strip() for key in ("project_id", "service_id", "hour_type_id"))


def apply_review(plan: dict[str, Any], entry_id: str, reviewed_values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Apply one human edit, repair state, reflow, then consolidate safe peers."""
    updated = deepcopy(plan)
    index = next((i for i, row in enumerate(updated["entries"]) if row.get("entry_id") == entry_id), None)
    if index is None:
        raise KeyError(entry_id)

    original = deepcopy(updated["entries"][index])
    entry = updated["entries"][index]
    was_skipped = bool(original.get("ignored")) or original.get("review_state") == "skipped"

    for key in _REVIEW_FIELDS:
        if key in reviewed_values:
            entry[key] = deepcopy(reviewed_values[key])

    restoring = was_skipped and reviewed_values.get("ignored") is False
    if entry.get("ignored"):
        entry["review_state"] = "skipped"
    elif restoring and not _target_complete(entry):
        entry["tier"] = "ASK"
        entry["overall_tier"] = "ASK"
        entry["mapping_state"] = "PENDING"
        entry["review_state"] = None
        entry["why_not_auto"] = entry.get("why_not_auto") or "Restored entry requires a booking target."
    else:
        changes = changed_fields(original, entry)
        tier = entry.get("tier") or entry.get("overall_tier")
        if tier in {"PROPOSE", "ASK"} and not _target_complete(entry):
            entry["review_state"] = None
            entry["mapping_state"] = "PENDING"
        else:
            entry["review_state"] = "corrected" if changes else "confirmed"
            if _target_complete(entry):
                entry["mapping_state"] = "RESOLVED"

    updated["status"] = "IN_REVIEW"
    updated = reflow_plan_days(updated)
    updated = consolidate_reviewed_entries(updated, preferred_entry_id=entry_id)
    reviewed = next(row for row in updated["entries"] if row.get("entry_id") == entry_id)
    return updated, original, deepcopy(reviewed)


def split_consolidated_entry(plan: dict[str, Any], entry_id: str) -> dict[str, Any]:
    """Split an aggregate entry back into immutable Clockify source rows."""
    updated = deepcopy(plan)
    index = next((i for i, row in enumerate(updated.get("entries") or []) if row.get("entry_id") == entry_id), None)
    if index is None:
        raise KeyError(entry_id)
    original = updated["entries"][index]
    source_ids = [str(value) for value in original.get("clockify_source_ids") or [] if value]
    if len(source_ids) < 2:
        raise ValueError("entry is not consolidated")
    snapshots = updated.get("clockify_source_snapshots") or {}
    missing = [sid for sid in source_ids if sid not in snapshots]
    if missing:
        raise ValueError(f"cannot split without Clockify source snapshots: {', '.join(missing)}")

    split: list[dict[str, Any]] = []
    for position, sid in enumerate(source_ids):
        source = deepcopy(snapshots[sid])
        row = deepcopy(original)
        duration = int(source.get("duration_seconds") or 0)
        row["entry_id"] = entry_id if position == 0 else f"{entry_id}-split-{sid}"
        row["clockify_source_ids"] = [sid]
        row["source"] = {key: deepcopy(source.get(key)) for key in ("description", "client", "project", "start", "end")}
        row["date"] = str(source.get("start") or row.get("date") or "")[:10]
        row["original_duration_seconds"] = duration
        row["planned_duration_seconds"] = duration
        row["planned_start"] = source.get("start")
        row["planned_end"] = source.get("end")
        row["review_state"] = None
        row["tier"] = "PROPOSE"
        row["overall_tier"] = "PROPOSE"
        row["split_from_entry_id"] = entry_id
        row["source_fingerprint"] = source_fingerprint(row)
        row.pop("consolidated", None)
        row.pop("consolidated_entry_ids", None)
        split.append(row)

    updated["entries"][index:index + 1] = split
    updated["status"] = "IN_REVIEW"
    return validate_plan(reflow_plan_days(updated))


def _review_projection(entry: dict[str, Any]) -> dict[str, Any]:
    keys = ("entry_id",) + _REVIEW_FIELDS
    return {key: deepcopy(entry.get(key)) for key in keys if key in entry}
