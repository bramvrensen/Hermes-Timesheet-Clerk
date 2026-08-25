"""Working-week synchronization for Timesheet Clerk.

Planner sync payloads are incremental: after a cheap source probe the planner may
return only new/changed/unprocessed Clockify rows. The mutable working week merges
those rows into the existing plan while preserving human review. Approval
snapshots remain immutable and separate from working state.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .contracts import utc_now, validate_plan
from .review import source_fingerprint
from .storage import PlanRepository, StateConflict
from .sync import attach_source_snapshots, covered_source_ids

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

    Existing rows absent from ``incoming`` are preserved. Human-reviewed values on
    matching rows always win over regenerated planner proposals.

    Safety invariant: if the canonical Clockify baseline already contains source
    IDs not represented by the working plan, the incoming planner payload must
    cover every one of those unprocessed IDs. A partial sync is rejected instead
    of silently refreshing the baseline and hiding the omission again.
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

    baseline_ids = set((existing.get("clockify_source_snapshots") or {}).keys())
    already_covered = covered_source_ids(existing)
    required_unprocessed = baseline_ids - already_covered
    incoming_covered = covered_source_ids(candidate)
    omitted = sorted(required_unprocessed - incoming_covered)
    if omitted:
        raise StateConflict(
            "planner sync omitted unprocessed Clockify sources: " + ", ".join(omitted)
        )

    merged = deepcopy(existing)
    merged["source_sync_at"] = utc_now()
    merged["generated_at"] = candidate.get("generated_at") or merged.get("generated_at")
    merged["review_context"] = deepcopy(candidate.get("review_context") or merged.get("review_context") or {})
    merged["target_hours"] = merged.get("target_hours", candidate.get("target_hours"))
    merged["contract_hours_default"] = candidate.get("contract_hours_default", merged.get("contract_hours_default"))

    old_by_key = {_entry_key(row): row for row in merged.get("entries") or []}
    incoming_by_key = {_entry_key(row): row for row in candidate.get("entries") or []}
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
    merged["status"] = "IN_REVIEW"

    raw = (candidate.get("review_context") or {}).get("clockify_entries") or candidate.get("clockify_entries") or []
    if raw:
        merged = attach_source_snapshots(merged, raw)
    elif isinstance(candidate.get("clockify_source_snapshots"), dict):
        merged["clockify_source_snapshots"] = deepcopy(candidate["clockify_source_snapshots"])

    validated = validate_plan(merged)
    return repo.save_revision(validated, expected_revision=int(existing["revision"]), make_active=True)


def _find_working_week(repo: PlanRepository, monday: str, sunday: str) -> dict[str, Any] | None:
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
