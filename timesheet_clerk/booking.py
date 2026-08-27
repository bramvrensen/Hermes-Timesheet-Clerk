"""Deterministic Simplicate booking preview and guarded write pipeline."""
from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .config import SimplicateConfig
from .http import request_json
from .simplicate import SimplicateClient
from .storage import PlanRepository, StateConflict

WRITE_ENV = "TIMESHEET_CLERK_SIMPLICATE_WRITE_ENABLED"
CONFIRMATION_TEXT = "BOOK APPROVED HOURS"
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def latest_approved_snapshot(repo: PlanRepository, plan_id: str | None = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in repo.approvals_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("status") != "APPROVED":
            continue
        if plan_id and payload.get("plan_id") != plan_id:
            continue
        payload["_approval_file"] = str(path)
        rows.append(payload)
    if not rows:
        raise StateConflict("No approved Timesheet Clerk snapshot is available for booking")
    rows.sort(key=lambda row: (str(row.get("approved_at") or ""), int(row.get("revision") or 0)))
    return deepcopy(rows[-1])


def build_booking_rows(snapshot: dict[str, Any], employee_id: str) -> list[dict[str, Any]]:
    if snapshot.get("status") != "APPROVED":
        raise StateConflict("Booking only accepts an immutable APPROVED snapshot")
    result: list[dict[str, Any]] = []
    for entry in snapshot.get("entries") or []:
        if entry.get("ignored") or entry.get("review_state") == "skipped":
            continue
        payload = _entry_payload(entry, employee_id)
        result.append({
            "plan_id": snapshot["plan_id"],
            "revision": snapshot["revision"],
            "entry_id": entry["entry_id"],
            "clockify_source_ids": list(entry.get("clockify_source_ids") or []),
            "description": str((entry.get("source") or {}).get("description") or entry.get("description") or ""),
            "payload": payload,
        })
    return result


def preview_booking(repo: PlanRepository, snapshot: dict[str, Any], client: SimplicateClient) -> dict[str, Any]:
    week = snapshot.get("week") or {}
    start_date, end_date = str(week.get("monday") or ""), str(week.get("sunday") or "")
    rows = build_booking_rows(snapshot, client.config.employee_id)
    booked = client.get_booked_hours(start_date, end_date)
    receipt_entries = _receipt_entry_ids(repo, snapshot["plan_id"])
    for row in rows:
        row["already_receipted"] = row["entry_id"] in receipt_entries
        row["possible_existing_matches"] = [
            _existing_projection(item)
            for item in booked
            if _looks_like_same_registration(row["payload"], item)
        ]
        row["preflight_status"] = (
            "already_booked" if row["already_receipted"] else
            "possible_duplicate" if row["possible_existing_matches"] else
            "ready"
        )
    ready = sum(1 for row in rows if row["preflight_status"] == "ready")
    return {
        "plan_id": snapshot["plan_id"],
        "revision": snapshot["revision"],
        "approved_at": snapshot.get("approved_at"),
        "week": deepcopy(week),
        "write_enabled": write_enabled(),
        "entry_count": len(rows),
        "ready_count": ready,
        "already_booked_count": sum(1 for row in rows if row["preflight_status"] == "already_booked"),
        "possible_duplicate_count": sum(1 for row in rows if row["preflight_status"] == "possible_duplicate"),
        "rows": rows,
    }


def execute_booking(repo: PlanRepository, snapshot: dict[str, Any], client: SimplicateClient, confirmation: str) -> dict[str, Any]:
    if not write_enabled():
        raise StateConflict(f"Live Simplicate writes are disabled. Set {WRITE_ENV}=true only after preview validation.")
    if confirmation.strip() != CONFIRMATION_TEXT:
        raise StateConflict(f"Typed confirmation must exactly equal: {CONFIRMATION_TEXT}")
    preview = preview_booking(repo, snapshot, client)
    blocked = [row for row in preview["rows"] if row["preflight_status"] == "possible_duplicate"]
    if blocked:
        raise StateConflict(f"Refusing live booking: {len(blocked)} row(s) have possible existing Simplicate matches")

    booked_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    for row in preview["rows"]:
        if row["preflight_status"] == "already_booked":
            skipped_rows.append({"entry_id": row["entry_id"], "reason": "receipt_exists"})
            continue
        response = _post_hours(client.config, row["payload"])
        receipt = {
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "plan_id": row["plan_id"],
            "revision": row["revision"],
            "entry_id": row["entry_id"],
            "clockify_source_ids": row["clockify_source_ids"],
            "simplicate_payload": deepcopy(row["payload"]),
            "simplicate_response": deepcopy(response),
        }
        path = repo.write_receipt(receipt)
        booked_rows.append({"entry_id": row["entry_id"], "receipt": str(path), "response": response})
    return {
        "plan_id": snapshot["plan_id"],
        "revision": snapshot["revision"],
        "booked_count": len(booked_rows),
        "skipped_count": len(skipped_rows),
        "booked": booked_rows,
        "skipped": skipped_rows,
    }


def write_enabled() -> bool:
    return str(os.environ.get(WRITE_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}


def _direct_target_ids(mapping: dict[str, Any]) -> tuple[Any, Any, Any]:
    """Return stable direct-target IDs across planner/UI/API naming variants.

    The canonical working-plan contract uses project_id/service_id/hour_type_id.
    Older state and Simplicate-shaped rows may instead carry projectservice_id or
    type_id, or nested project/service/hour_type objects. Booking accepts those
    aliases but always emits the canonical Simplicate payload fields.
    """
    project = mapping.get("project") or {}
    service = mapping.get("service") or mapping.get("projectservice") or mapping.get("task") or {}
    hour_type = mapping.get("hour_type") or mapping.get("type") or {}
    project_id = mapping.get("project_id") or _plain_id(project)
    service_id = mapping.get("service_id") or mapping.get("projectservice_id") or _plain_id(service)
    hour_type_id = mapping.get("hour_type_id") or mapping.get("type_id") or _plain_id(hour_type)
    return project_id, service_id, hour_type_id


def _entry_payload(entry: dict[str, Any], employee_id: str) -> dict[str, Any]:
    mode = entry.get("booking_mode")
    if mode == "assignment":
        assignment = entry.get("assignment") or {}
        project = assignment.get("project") or {}
        task = assignment.get("task") or assignment.get("projectservice") or {}
        hour_type = assignment.get("hour_type") or assignment.get("projecthourstype") or assignment.get("hours_type") or {}
        assignment_id = assignment.get("id")
        project_id = project.get("id") or assignment.get("project_id")
        service_id = task.get("id") or assignment.get("service_id") or assignment.get("projectservice_id")
        hour_type_id = hour_type.get("id") or assignment.get("hour_type_id") or assignment.get("type_id")
        _validate_assignment_date(entry, assignment)
    elif mode == "direct":
        mapping = entry.get("direct_mapping") or {}
        assignment_id = None
        project_id, service_id, hour_type_id = _direct_target_ids(mapping)
    else:
        raise StateConflict(f"Entry {entry.get('entry_id')} has unsupported booking mode {mode!r}")

    missing = [name for name, value in (("project", project_id), ("project service", service_id), ("hour type", hour_type_id)) if not str(value or "").strip()]
    if missing:
        raise StateConflict(f"Entry {entry.get('entry_id')} is missing booking target fields: {', '.join(missing)}")
    seconds = float(entry.get("planned_duration_seconds") or 0)
    if seconds <= 0:
        raise StateConflict(f"Entry {entry.get('entry_id')} has no positive bookable duration")

    payload: dict[str, Any] = {
        "employee_id": _api_id("employee", employee_id),
        "project_id": _api_id("project", project_id),
        "projectservice_id": _api_id("projectservice", service_id),
        "type_id": _api_id("hourstype", hour_type_id),
        "start_date": _simplicate_datetime(entry.get("planned_start"), entry.get("date")),
        "end_date": _simplicate_datetime(entry.get("planned_end"), entry.get("date")),
        "hours": round(seconds / 3600.0, 4),
        "note": str((entry.get("source") or {}).get("description") or entry.get("description") or "").strip(),
    }
    if assignment_id:
        payload["assignment_id"] = _api_id("assignment", assignment_id)
    return payload


def _post_hours(config: SimplicateConfig, payload: dict[str, Any]) -> Any:
    headers = {
        "Authentication-Key": config.api_key,
        "Authentication-Secret": config.api_secret,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    return request_json(
        "POST",
        f"{config.base_url.rstrip('/')}/hours/hours",
        headers=headers,
        json=payload,
        max_attempts=1,
    )


def _validate_assignment_date(entry: dict[str, Any], assignment: dict[str, Any]) -> None:
    day = str(entry.get("date") or "")[:10]
    start = str(assignment.get("start_date") or "")[:10]
    end = str(assignment.get("end_date") or "")[:10]
    if start and day < start:
        raise StateConflict(f"Entry {entry.get('entry_id')} date {day} precedes assignment start {start}")
    if end and day > end:
        raise StateConflict(f"Entry {entry.get('entry_id')} date {day} exceeds assignment end {end}")


def _api_id(prefix: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if ":" in text or _UUID_RE.match(text):
        return text
    return f"{prefix}:{text}"


def _plain_id(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("id")
    text = str(value or "")
    return text.split(":", 1)[1] if ":" in text else text


def _simplicate_datetime(value: Any, fallback_date: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return f"{str(fallback_date)[:10]} 00:00:00"
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        if "T" in text:
            return text.replace("T", " ")[:19]
        return text[:19]


def _receipt_entry_ids(repo: PlanRepository, plan_id: str) -> set[str]:
    result: set[str] = set()
    for path in repo.receipts_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("plan_id") == plan_id and payload.get("entry_id"):
            result.add(str(payload["entry_id"]))
    return result


def _looks_like_same_registration(payload: dict[str, Any], item: dict[str, Any]) -> bool:
    item_project = _plain_id(item.get("project") or item.get("project_id"))
    item_service = _plain_id(item.get("projectservice") or item.get("projectservice_id"))
    item_type = _plain_id(item.get("type") or item.get("type_id"))
    item_assignment = _plain_id(item.get("assignment") or item.get("assignment_id"))
    expected_assignment = _plain_id(payload.get("assignment_id"))
    item_day = str(item.get("start_date") or "")[:10]
    expected_day = str(payload.get("start_date") or "")[:10]
    try:
        item_hours = float(item.get("hours") or 0)
    except (TypeError, ValueError):
        item_hours = 0.0
    return (
        item_project == _plain_id(payload.get("project_id")) and
        item_service == _plain_id(payload.get("projectservice_id")) and
        item_type == _plain_id(payload.get("type_id")) and
        item_day == expected_day and
        abs(item_hours - float(payload.get("hours") or 0)) < 0.001 and
        (not expected_assignment or item_assignment == expected_assignment)
    )


def _existing_projection(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "start_date": item.get("start_date"),
        "hours": item.get("hours"),
        "project_id": _plain_id(item.get("project") or item.get("project_id")),
        "projectservice_id": _plain_id(item.get("projectservice") or item.get("projectservice_id")),
        "type_id": _plain_id(item.get("type") or item.get("type_id")),
        "assignment_id": _plain_id(item.get("assignment") or item.get("assignment_id")),
        "note": item.get("note"),
    }
