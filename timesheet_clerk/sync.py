"""Deterministic source-delta and plan-summary helpers.

Source comparison is deliberately based on immutable per-Clockify snapshots,
not on planner/booking fields. Plan coverage is tracked separately: a source can
already exist in the canonical baseline while still not be represented by any
working-plan entry.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

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
        if bool(e.get("billable", mapping.get("billable", True))): billable += float(e.get("planned_duration_seconds") or 0)
    pending = sum(1 for e in entries if not e.get("ignored") and (e.get("tier") or e.get("overall_tier")) in {"PROPOSE", "ASK"} and e.get("review_state") not in {"confirmed", "corrected", "skipped"})
    delta = source_delta or {}
    return {
        "plan_id": plan.get("plan_id"), "revision": plan.get("revision"), "status": plan.get("status"),
        "source_sync_at": plan.get("source_sync_at"), "clocked_hours": hours(clocked), "workable_hours": hours(workable),
        "billable_hours": hours(billable), "booked_hours": hours(booked), "open_hours": hours(max(0.0, workable-booked)),
        "ignored_count": sum(1 for e in entries if e.get("ignored")), "pending_review_count": pending,
        "entry_count": len(entries), "new_source_count": int(delta.get("new_count",0)),
        "changed_source_count": int(delta.get("changed_count",0)), "missing_source_count": int(delta.get("missing_count",0)),
        "unprocessed_source_count": int(delta.get("unprocessed_count",0)),
    }


def source_snapshot(source: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(source.get("id") or ""), **{key: deepcopy(source.get(key)) for key in _SOURCE_FIELDS}}


def source_snapshots(clockify_entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["id"]): source_snapshot(row) for row in clockify_entries if row.get("id")}


def covered_source_ids(plan: dict[str, Any] | None) -> set[str]:
    covered=set()
    for entry in (plan or {}).get("entries") or []:
        for source_id in entry.get("clockify_source_ids") or []:
            value=str(source_id or "").strip()
            if value: covered.add(value)
    return covered


def attach_source_snapshots(plan: dict[str, Any], clockify_entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Advance source baseline only after every source has working-plan coverage."""
    result=deepcopy(plan)
    entries=result.setdefault("entries",[])
    covered=covered_source_ids(result)
    tz=ZoneInfo("Europe/Amsterdam")
    for source in clockify_entries:
        source_id=str(source.get("id") or "").strip()
        if not source_id or source_id in covered: continue
        start=source.get("start"); end=source.get("end"); duration=float(source.get("duration_seconds") or 0)
        try: day=datetime.fromisoformat(str(start).replace("Z","+00:00")).astimezone(tz).date().isoformat()
        except ValueError: day=str(start or "")[:10]
        entries.append({
            "entry_id": f"clockify-{source_id}", "clockify_source_ids":[source_id], "date":day,
            "source":{"description":source.get("description") or "","client":deepcopy(source.get("client")),"project":deepcopy(source.get("project")),"tags":deepcopy(source.get("tags") or []),"start":start,"end":end,"duration_seconds":source.get("duration_seconds")},
            "original_duration_seconds":duration,"planned_duration_seconds":duration,"planned_start":start,"planned_end":end,
            "booking_mode":"direct","direct_mapping":{},"tier":"ASK",
            "why_not_auto":"Clockify source ingested; Simplicate mapping still requires resolution.",
        })
        covered.add(source_id)
    entries.sort(key=lambda row:(str(row.get("date") or ""),str(row.get("planned_start") or ""),str(row.get("entry_id") or "")))
    result["clockify_source_snapshots"]=source_snapshots(clockify_entries)
    return result


def source_delta(plan: dict[str, Any] | None, clockify_entries: list[dict[str, Any]]) -> dict[str, Any]:
    incoming=source_snapshots(clockify_entries); stored=(plan or {}).get("clockify_source_snapshots")
    if plan is not None and not isinstance(stored,dict):
        return {"has_changes":True,"requires_rebaseline":True,"new_count":0,"changed_count":0,"missing_count":0,"unchanged_count":0,"unprocessed_count":0,"new_entries":[],"changed_entries":[],"unprocessed_entries":[],"missing_source_ids":[]}
    stored=stored or {}; incoming_ids=set(incoming); stored_ids=set(stored)
    new_ids=sorted(incoming_ids-stored_ids); missing_ids=sorted(stored_ids-incoming_ids); common_ids=sorted(incoming_ids&stored_ids)
    changed_ids=[i for i in common_ids if stored[i]!=incoming[i]]; changed_set=set(changed_ids); unchanged_ids=[i for i in common_ids if i not in changed_set]
    covered_ids=covered_source_ids(plan); unprocessed_ids=sorted((incoming_ids&stored_ids)-covered_ids)
    by_id={str(row.get("id")):row for row in clockify_entries if row.get("id")}
    return {
        "has_changes":bool(new_ids or changed_ids or missing_ids or unprocessed_ids),"requires_rebaseline":False,
        "new_count":len(new_ids),"changed_count":len(changed_ids),"missing_count":len(missing_ids),"unchanged_count":len(unchanged_ids),
        "unprocessed_count":len(unprocessed_ids),"covered_count":len(covered_ids&incoming_ids),
        "new_entries":[by_id[i] for i in new_ids],"changed_entries":[by_id[i] for i in changed_ids],
        "unprocessed_entries":[by_id[i] for i in unprocessed_ids],"missing_source_ids":missing_ids,
    }
