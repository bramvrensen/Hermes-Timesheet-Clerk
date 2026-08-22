"""Deterministic source-delta and plan-summary helpers.

These helpers keep cheap synchronization and arithmetic out of the planner LLM.
"""
from __future__ import annotations

from typing import Any


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
        "plan_id": plan.get("plan_id"),
        "revision": plan.get("revision"),
        "status": plan.get("status"),
        "source_sync_at": plan.get("source_sync_at"),
        "clocked_hours": hours(clocked),
        "workable_hours": hours(workable),
        "billable_hours": hours(billable),
        "booked_hours": hours(booked),
        "open_hours": hours(max(0.0, workable - booked)),
        "ignored_count": sum(1 for e in entries if e.get("ignored")),
        "pending_review_count": pending,
        "entry_count": len(entries),
        "new_source_count": int(delta.get("new_count", 0)),
        "changed_source_count": int(delta.get("changed_count", 0)),
        "missing_source_count": int(delta.get("missing_count", 0)),
    }


def source_delta(plan: dict[str, Any] | None, clockify_entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare normalized Clockify entries to source facts stored in a plan.

    Matching is by Clockify source id. A record is changed only when a source
    fact that is already represented in the plan differs. This keeps older
    plans compatible when they do not yet contain source start/end timestamps.
    """
    plan_entries = (plan or {}).get("entries") or []
    by_source: dict[str, dict[str, Any]] = {}
    for row in plan_entries:
        for source_id in row.get("clockify_source_ids") or []:
            if source_id: by_source[str(source_id)] = row

    incoming_ids = {str(row.get("id")) for row in clockify_entries if row.get("id")}
    new: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    unchanged: list[str] = []

    for source in clockify_entries:
        source_id = str(source.get("id") or "")
        if not source_id: continue
        prior = by_source.get(source_id)
        if prior is None:
            new.append(source); continue
        if _source_changed(prior, source): changed.append(source)
        else: unchanged.append(source_id)

    missing = sorted(source_id for source_id in by_source if source_id not in incoming_ids)
    return {
        "has_changes": bool(new or changed or missing),
        "new_count": len(new),
        "changed_count": len(changed),
        "missing_count": len(missing),
        "unchanged_count": len(unchanged),
        "new_entries": new,
        "changed_entries": changed,
        "missing_source_ids": missing,
    }


def _source_changed(plan_entry: dict[str, Any], source: dict[str, Any]) -> bool:
    stored = plan_entry.get("source") or {}
    checks = [
        (stored.get("description"), source.get("description")),
        (_nested_name(stored.get("client")), _nested_name(source.get("client"))),
        (_nested_name(stored.get("project")), _nested_name(source.get("project"))),
        (plan_entry.get("original_duration_seconds"), source.get("duration_seconds")),
    ]
    if stored.get("start") is not None: checks.append((stored.get("start"), source.get("start")))
    if stored.get("end") is not None: checks.append((stored.get("end"), source.get("end")))
    return any(a != b for a, b in checks if a is not None)


def _nested_name(value: Any) -> Any:
    return value.get("name") if isinstance(value, dict) else value
