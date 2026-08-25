"""Deterministic Clockify source coverage repair.

This module turns live Clockify sources that are absent from the working plan into
unresolved ASK entries. It makes no Simplicate mapping decisions and therefore
requires no LLM-generated internal plan payload.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .sync import covered_source_ids


def ensure_source_coverage(
    plan: dict[str, Any],
    clockify_entries: list[dict[str, Any]],
    *,
    timezone_name: str = "Europe/Amsterdam",
) -> tuple[dict[str, Any], list[str]]:
    result = deepcopy(plan)
    entries = result.setdefault("entries", [])
    covered = covered_source_ids(result)
    tz = ZoneInfo(timezone_name)
    added: list[str] = []

    for source in clockify_entries:
        source_id = str(source.get("id") or "").strip()
        if not source_id or source_id in covered:
            continue
        start = source.get("start")
        end = source.get("end")
        duration = float(source.get("duration_seconds") or 0)
        entries.append({
            "entry_id": f"clockify-{source_id}",
            "clockify_source_ids": [source_id],
            "date": _local_date(start, tz),
            "source": {
                "description": source.get("description") or "",
                "client": deepcopy(source.get("client")),
                "project": deepcopy(source.get("project")),
                "tags": deepcopy(source.get("tags") or []),
                "start": start,
                "end": end,
                "duration_seconds": source.get("duration_seconds"),
            },
            "original_duration_seconds": duration,
            "planned_duration_seconds": duration,
            "planned_start": start,
            "planned_end": end,
            "booking_mode": "direct",
            "direct_mapping": {},
            "tier": "ASK",
            "why_not_auto": "Clockify source ingested; Simplicate mapping still requires resolution.",
        })
        covered.add(source_id)
        added.append(source_id)

    entries.sort(key=lambda row: (
        str(row.get("date") or ""),
        str(row.get("planned_start") or ""),
        str(row.get("entry_id") or ""),
    ))
    if added:
        result["status"] = "IN_REVIEW"
    return result, added


def _local_date(value: Any, tz: ZoneInfo) -> str:
    text = str(value or "")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(tz).date().isoformat()
    except ValueError:
        return text[:10]
