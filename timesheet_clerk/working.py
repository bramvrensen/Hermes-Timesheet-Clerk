"""Working-week synchronization for Timesheet Clerk.

Planner sync payloads are incremental: after a cheap source probe the planner may
return only new/changed Clockify rows. The mutable working week therefore merges
those rows into the existing plan. Approval snapshots are immutable and live in
a separate store; approving a revision never closes the working week.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .contracts import utc_now, validate_plan
from .review import source_fingerprint
from .storage import PlanRepository
from .sync import attach_source_snapshots

_REVIEW_FIELDS = (
    "planned_duration_seconds",
    "planned_start",
    "planned_end",
    "booking_mode",
    "assignment",
    "direct_mapping",
    "ignored",
    "review_state",
)


def sync_week_plan(repo: PlanRepository, incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge an incremental planner result into the mutable working week.

    Existing rows absent from ``incoming`` are preserved. Source disappearance is
    determined by ``timesheet_sync_probe``/the canonical Clockify baseline, not by
    omission from the planner's delta payload. Human-reviewed values on matching
    rows always win over regenerated planner proposals.
    """
    candidate = validate_plan(incoming)
    monday = str((candidate.get("week") or {}).get("monday") or "")
    sunday = str((candidate.get("week") or {}).get("sunday") or "")
    existing = _find_working_week(repo, monday, sunday)

    if existing is None:
        candidate["revision"] = 1
        candidate["status"] = "DRAFT"
        candidate["source_sync_at"] = utc_now()
        return repo.create(candidate, make_active=True)

    merged = deepcopy(existing)
    merged["source_sync_at"] = utc_now()
    merged["generated_at"] = candidate.get("generated_at") or merged.get("generated_at")
    merged["review_context"] = deepcopy(candidate.get("review_context") or merged.get("review_context") or {})
    merged["target_hours"] = merged.get("target_hours", candidate.get("target_hours"))
    merged["contract_hours_default"] = candidate.get("contract_hours_default", merged.get("contract_hours_default"))

    old_by_key = {_entry_key(row): row for row in merged.get("entries") or []}
    incoming_by_key = {_entry_key(row): row for row in candidate.get("entries") or []}

    # Start from the complete working plan. The planner normally receives only
    # source deltas, so omission from its response must never delete/mark an old
    # row as missing.
    output_by_key = {key: deepcopy(row) for key, row in old_by_key.items()}
    for key, fresh in incoming_by_key.items():
        prior = old_by_key.get(key)
        if prior is None:
            row = deepcopy(fresh)
            row["last_seen_at"] = merged["source_sync_at"]
            row["source_fingerprint"] = source_fingerprint(row)
            output_by_key[key] = row
            continue

        row = deepcopy(fresh)
        row["entry_id"] = prior.get("entry_id") or fresh.get("entry_id")
        row["last_seen_at"] = merged["source_sync_at"]
        row["source_fingerprint"] = source_fingerprint(row)
        row.pop("source_missing", None)
        row.pop("source_missing_since", None)
        if prior.get("review_state") in {"confirmed", "corrected", "skipped"}:
            for field in _REVIEW_FIELDS:
                if field in prior:
                    row[field] = deepcopy(prior[field])
            row["review_preserved_on_sync"] = True
        output_by_key[key] = row

    output = list(output_by_key.values())
    output.sort(key=lambda row: (
        str(row.get("date") or ""),
        str(row.get("planned_start") or ""),
        str(row.get("entry_id") or ""),
    ))
    merged["entries"] = output
    # A fresh source delta means the mutable week is open for review again.
    # Any APPROVED snapshots remain untouched in approvals/.
    merged["status"] = "IN_REVIEW"

    # Planner payloads may include canonical raw Clockify rows. Persist them when
    # present, but the plugin refreshes the full source baseline after this merge.
    raw = (candidate.get("review_context") or {}).get("clockify_entries") or candidate.get("clockify_entries") or []
    if raw:
        merged = attach_source_snapshots(merged, raw)
    elif isinstance(candidate.get("clockify_source_snapshots"), dict):
        merged["clockify_source_snapshots"] = deepcopy(candidate["clockify_source_snapshots"])

    validated = validate_plan(merged)
    return repo.save_revision(validated, expected_revision=int(existing["revision"]), make_active=True)


def _find_working_week(repo: PlanRepository, monday: str, sunday: str) -> dict[str, Any] | None:
    """Find the mutable week independently of immutable approval snapshots."""
    for summary in repo.list_plans(limit=100):
        week = summary.get("week") or {}
        if str(week.get("monday") or "") != monday or str(week.get("sunday") or "") != sunday:
            continue
        plan = repo.get_latest(summary["plan_id"])
        if plan.get("status") in {"DRAFT", "IN_REVIEW"}:
            return plan
    return None


def _entry_key(entry: dict[str, Any]) -> str:
    ids = sorted(str(value) for value in (entry.get("clockify_source_ids") or []) if value)
    return "clockify:" + "|".join(ids) if ids else "fingerprint:" + source_fingerprint(entry)
