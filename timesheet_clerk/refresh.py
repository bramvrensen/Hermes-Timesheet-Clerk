"""Deterministic Clockify -> working-plan ingestion.

This layer owns source coverage. It never performs Simplicate mapping and never
requires an LLM to construct Timesheet Clerk's internal plan schema.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .contracts import utc_now, validate_plan
from .storage import PlanRepository
from .sync import attach_source_snapshots, source_delta


def refresh_working_plan(
    repo: PlanRepository,
    plan: dict[str, Any],
    clockify_entries: list[dict[str, Any]],
    *,
    timezone_name: str = "Europe/Amsterdam",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Ingest every live Clockify source into the working plan exactly once.

    Missing plan coverage becomes an unresolved ASK entry. Changed source facts
    update their represented plan entry while preserving human-reviewed planning
    decisions. Canonical source snapshots are refreshed only after coverage has
    been established.
    """
    delta = source_delta(plan, clockify_entries)
    if delta.get("requires_rebaseline"):
        # For legacy state, first establish raw source truth. Because coverage is
        # computed independently, all baseline rows absent from the plan will be
        # recoverable on the next refresh rather than disappearing silently.
        rebased = attach_source_snapshots(plan, clockify_entries)
        rebased["source_sync_at"] = utc_now()
        rebased = validate_plan(rebased)
        saved = repo.save_revision(rebased, expected_revision=int(plan["revision"]), make_active=True)
        return saved, {**delta, "rebaseline_performed": True, "ingested_count": 0}

    updated = deepcopy(plan)
    tz = ZoneInfo(timezone_name)
    entries = updated.get("entries") or []
    by_source: dict[str, dict[str, Any]] = {}
    for row in entries:
        for source_id in row.get("clockify_source_ids") or []:
            by_source[str(source_id)] = row

    live_by_id = {str(row.get("id")): row for row in clockify_entries if row.get("id")}
    changed_ids = {str(row.get("id")) for row in delta.get("changed_entries") or [] if row.get("id")}
    ingest_ids = {
        str(row.get("id"))
        for key in ("new_entries", "unprocessed_entries")
        for row in delta.get(key) or []
        if row.get("id")
    }

    for source_id in sorted(changed_ids):
        source = live_by_id[source_id]
        target = by_source.get(source_id)
        if target is None:
            ingest_ids.add(source_id)
            continue
        target["source"] = _source_payload(source)
        target["original_duration_seconds"] = float(source.get("duration_seconds") or 0)
        target["date"] = _local_date(source.get("start"), tz)
        target["source_start"] = source.get("start")
        target["source_end"] = source.get("end")
        if target.get("review_state") not in {"confirmed", "corrected", "skipped"}:
            target["planned_duration_seconds"] = float(source.get("duration_seconds") or 0)
            target["planned_start"] = source.get("start")
            target["planned_end"] = source.get("end")

    for source_id in sorted(ingest_ids):
        source = live_by_id[source_id]
        entries.append(_new_entry(source, tz))

    if not delta.get("has_changes"):
        return plan, {**delta, "rebaseline_performed": False, "ingested_count": 0}

    updated["entries"] = sorted(
        entries,
        key=lambda row: (
            str(row.get("date") or ""),
            str(row.get("planned_start") or ""),
            str(row.get("entry_id") or ""),
        ),
    )
    updated["status"] = "IN_REVIEW"
    updated["source_sync_at"] = utc_now()
    updated = attach_source_snapshots(updated, clockify_entries)
    updated = validate_plan(updated)
    saved = repo.save_revision(updated, expected_revision=int(plan["revision"]), make_active=True)
    return saved, {
        **delta,
        "rebaseline_performed": False,
        "ingested_count": len(ingest_ids),
    }


def _new_entry(source: dict[str, Any], tz: ZoneInfo) -> dict[str, Any]:
    source_id = str(source["id"])
    duration = float(source.get("duration_seconds") or 0)
    return {
        "entry_id": f"clockify-{source_id}",
        "clockify_source_ids": [source_id],
        "date": _local_date(source.get("start"), tz),
        "source": _source_payload(source),
        "source_start": source.get("start"),
        "source_end": source.get("end"),
        "original_duration_seconds": duration,
        "planned_duration_seconds": duration,
        "planned_start": source.get("start"),
        "planned_end": source.get("end"),
        "booking_mode": "direct",
        "direct_mapping": {},
        "tier": "ASK",
        "why_not_auto": "Clockify source ingested; Simplicate mapping still requires resolution.",
    }


def _source_payload(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "description": source.get("description") or "",
        "client": deepcopy(source.get("client")),
        "project": deepcopy(source.get("project")),
        "tags": deepcopy(source.get("tags") or []),
        "start": source.get("start"),
        "end": source.get("end"),
        "duration_seconds": source.get("duration_seconds"),
    }


def _local_date(value: Any, tz: ZoneInfo) -> str:
    text = str(value or "")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(tz).date().isoformat()
    except ValueError:
        return text[:10]
