"""Deterministic source-delta and plan-summary helpers.

Source comparison is deliberately based on immutable per-Clockify snapshots,
not on planner/booking fields. A plan entry may aggregate several Clockify rows;
comparing every source row to the aggregate caused false-positive deltas.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

_SOURCE_FIELDS = ("description", "client", "project", "start", "end", "duration_seconds")


def plan_summary(plan: dict[str, Any], *, source_delta: dict[str, Any] | None = None) -> dict[str, Any]:
    entries = plan.get("entries") or []
    def hours(total: float) -> float: return round(total / 3600.0, 2)
    clocked = sum(float(e.get("original_duration_seconds") or 0) for e in entries)
    workable = sum(float(e.get("planned_duration_seconds") or 0) for e in entries if not e.get("ignored"))
    booked = sum(float(e.get("planned_duration_seconds") or 0) for e in entries if not e.get("ignored") and e.get("reconciliation_state") == "BOOKED")
    billable = 0.0
    for e in entries:
        if e.get("ignored"): continue
        mapping = e.get("direct_mapping") or {}
        if bool(e.get("billable", mapping.get("billable", True))):
            billable += float(e.get("planned_duration_seconds") or 0)
    pending = sum(1 for e in entries if not e.get("ignored") and (e.get("tier") or e.get("overall_tier")) in {"PROPOSE", "ASK"} and e.get("review_state") not in {"confirmed", "corrected", "skipped"})
    delta = source_delta or {}
    return {
        "plan_id": plan.get("plan_id"), "revision": plan.get("revision"), "status": plan.get("status"),
        "source_sync_at": plan.get("source_sync_at"), "clocked_hours": hours(clocked),
        "workable_hours": hours(workable), "billable_hours": hours(billable), "booked_hours": hours(booked),
        "open_hours": hours(max(0.0, workable - booked)),
        "ignored_count": sum(1 for e in entries if e.get("ignored")), "pending_review_count": pending,
        "entry_count": len(entries), "new_source_count": int(delta.get("new_count", 0)),
        "changed_source_count": int(delta.get("changed_count", 0)), "missing_source_count": int(delta.get("missing_count", 0)),
    }


def source_snapshot(source: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical source facts used for delta detection."""
    return {"id": str(source.get("id") or ""), **{key: deepcopy(source.get(key)) for key in _SOURCE_FIELDS}}


def source_snapshots(clockify_entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["id"]): source_snapshot(row) for row in clockify_entries if row.get("id")}


def attach_source_snapshots(plan: dict[str, Any], clockify_entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Persist canonical raw-source facts without touching review/planning fields."""
    result = deepcopy(plan)
    result["clockify_source_snapshots"] = source_snapshots(clockify_entries)
    return result


def source_delta(plan: dict[str, Any] | None, clockify_entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare Clockify rows to canonical per-source snapshots.

    Legacy plans without snapshots are intentionally reported as requiring a
    rebaseline. Guessing from aggregated plan entries is unsafe because one plan
    entry can represent multiple source rows.
    """
    incoming = source_snapshots(clockify_entries)
    stored = (plan or {}).get("clockify_source_snapshots")
    if plan is not None and not isinstance(stored, dict):
        return {
            "has_changes": True, "requires_rebaseline": True,
            "new_count": 0, "changed_count": 0, "missing_count": 0, "unchanged_count": 0,
            "new_entries": [], "changed_entries": [], "missing_source_ids": [],
        }
    stored = stored or {}
    new_ids = sorted(set(incoming) - set(stored))
    missing_ids = sorted(set(stored) - set(incoming))
    common_ids = sorted(set(incoming) & set(stored))
    changed_ids = [source_id for source_id in common_ids if stored[source_id] != incoming[source_id]]
    unchanged_ids = [source_id for source_id in common_ids if source_id not in set(changed_ids)]
    by_id = {str(row.get("id")): row for row in clockify_entries if row.get("id")}
    return {
        "has_changes": bool(new_ids or changed_ids or missing_ids), "requires_rebaseline": False,
        "new_count": len(new_ids), "changed_count": len(changed_ids), "missing_count": len(missing_ids),
        "unchanged_count": len(unchanged_ids), "new_entries": [by_id[i] for i in new_ids],
        "changed_entries": [by_id[i] for i in changed_ids], "missing_source_ids": missing_ids,
    }
