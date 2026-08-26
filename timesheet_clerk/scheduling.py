"""Deterministic Timesheet Clerk day scheduling.

Planning time is presentation/booking state, not Clockify source truth. Every
non-ignored workday is normalized to a stable sequence starting at 09:00, with
non-billable/internal work before billable work.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time, timedelta
from typing import Any


def reflow_plan_days(plan: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(plan)
    entries = result.get("entries") or []
    days = sorted({str(row.get("date") or "") for row in entries if row.get("date")})
    for day in days:
        reflow_day(entries, day)
    # Keep repository/UI order aligned with the canonical day schedule while
    # leaving ignored rows visible after bookable rows for that day.
    entries.sort(key=lambda row: (
        str(row.get("date") or ""),
        1 if row.get("ignored") else 0,
        str(row.get("planned_start") or ""),
        str(row.get("entry_id") or ""),
    ))
    result["entries"] = entries
    return result


def reflow_day(entries: list[dict[str, Any]], day: str) -> None:
    indexed = [(index, row) for index, row in enumerate(entries) if str(row.get("date") or "") == day and not row.get("ignored")]
    if not indexed:
        return

    # Stable sort inside both groups: prior planned order first, then original
    # source order/entry id as deterministic tie breakers.
    indexed.sort(key=lambda item: (
        1 if _is_billable(item[1]) else 0,
        str(item[1].get("planned_start") or (item[1].get("source") or {}).get("start") or ""),
        item[0],
        str(item[1].get("entry_id") or ""),
    ))

    first_example = indexed[0][1].get("planned_start") or (indexed[0][1].get("source") or {}).get("start")
    cursor = _day_start(day, first_example)
    for _, row in indexed:
        duration = max(0.0, float(row.get("planned_duration_seconds") or 0))
        row["planned_start"] = _format_like(cursor, row.get("planned_start") or (row.get("source") or {}).get("start"))
        cursor = cursor + timedelta(seconds=duration)
        row["planned_end"] = _format_like(cursor, row.get("planned_end") or row.get("planned_start"))


def _is_billable(entry: dict[str, Any]) -> bool:
    if entry.get("billable") is False:
        return False
    mapping = entry.get("direct_mapping") or {}
    if isinstance(mapping, dict) and mapping.get("billable") is False:
        return False
    return True


def _day_start(day: str, example: Any) -> datetime:
    parsed = _parse_datetime(example)
    tz = parsed.tzinfo if parsed is not None else None
    date_part = datetime.fromisoformat(day).date()
    return datetime.combine(date_part, time(9, 0), tzinfo=tz)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_like(value: datetime, example: Any) -> str:
    result = value.isoformat()
    return result.replace("+00:00", "Z") if str(example or "").endswith("Z") else result
