"""Guarded single-entry Simplicate booking for interactive task-by-task validation."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .booking import _entry_payload, _existing_projection, _looks_like_same_registration, _post_hours, _receipt_entry_ids
from .config import SimplicateConfig
from .simplicate import SimplicateClient
from .storage import PlanRepository, StateConflict


def task_booking_ready(entry: dict[str, Any]) -> tuple[bool, str]:
    if entry.get("ignored") or entry.get("review_state") == "skipped":
        return False, "Ignored entries are not bookable."
    if entry.get("reconciliation_state") == "BOOKED":
        return False, "This entry is already booked."
    tier = str(entry.get("tier") or entry.get("overall_tier") or "ASK")
    reviewed = entry.get("review_state") in {"confirmed", "corrected"}
    if tier in {"PROPOSE", "ASK"} and not reviewed:
        return False, "Review this entry before booking."
    try:
        _entry_payload(entry, SimplicateConfig.from_env().employee_id)
    except Exception as exc:
        return False, str(exc)
    return True, "Ready to book."


def preview_single_entry(repo: PlanRepository, plan_id: str, entry_id: str) -> dict[str, Any]:
    plan = repo.get_latest(plan_id)
    entry = next((row for row in plan.get("entries") or [] if row.get("entry_id") == entry_id), None)
    if not entry:
        raise StateConflict(f"Entry not found: {entry_id}")
    ready, reason = task_booking_ready(entry)
    if not ready:
        raise StateConflict(reason)
    client = SimplicateClient(SimplicateConfig.from_env())
    payload = _entry_payload(entry, client.config.employee_id)
    receipted = entry_id in _receipt_entry_ids(repo, plan_id)
    booked = client.get_booked_hours(str(entry.get("date") or "")[:10], str(entry.get("date") or "")[:10])
    matches = [_existing_projection(item) for item in booked if _looks_like_same_registration(payload, item)]
    status = "already_booked" if receipted else "possible_duplicate" if matches else "ready"
    return {
        "plan_id": plan_id,
        "revision": plan["revision"],
        "entry_id": entry_id,
        "entry": deepcopy(entry),
        "payload": payload,
        "status": status,
        "matches": matches,
    }


def execute_single_entry_booking(repo: PlanRepository, plan_id: str, entry_id: str) -> dict[str, Any]:
    """Book exactly one persisted entry and verify it by reading Simplicate back.

    The receipt is written immediately after a successful POST, before readback,
    so a readback/network failure can never cause a second POST on retry.
    """
    preview = preview_single_entry(repo, plan_id, entry_id)
    if preview["status"] == "already_booked":
        raise StateConflict("This entry already has a Timesheet Clerk booking receipt.")
    if preview["status"] == "possible_duplicate":
        raise StateConflict("A matching Simplicate registration already exists; booking is blocked to prevent a duplicate.")

    client = SimplicateClient(SimplicateConfig.from_env())
    response = _post_hours(client.config, preview["payload"])
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    receipt = {
        "timestamp": timestamp,
        "plan_id": plan_id,
        "revision": preview["revision"],
        "entry_id": entry_id,
        "clockify_source_ids": list(preview["entry"].get("clockify_source_ids") or []),
        "simplicate_payload": deepcopy(preview["payload"]),
        "simplicate_response": deepcopy(response),
        "verification_state": "PENDING",
    }
    receipt_path = repo.write_receipt(receipt)

    day = str(preview["entry"].get("date") or "")[:10]
    booked = client.get_booked_hours(day, day)
    matches = [item for item in booked if _looks_like_same_registration(preview["payload"], item)]
    if not matches:
        return {
            "success": False,
            "posted": True,
            "verified": False,
            "receipt": str(receipt_path),
            "message": "Simplicate accepted the POST, but Clerk could not verify it by readback. Receipt preserved; retry is blocked.",
        }

    latest = repo.get_latest(plan_id)
    entry = next((row for row in latest.get("entries") or [] if row.get("entry_id") == entry_id), None)
    if not entry:
        raise StateConflict("Entry disappeared after Simplicate booking; receipt preserved.")
    entry["reconciliation_state"] = "BOOKED"
    entry["booked_at"] = timestamp
    entry["simplicate_booking_id"] = matches[0].get("id")
    entry["booking_receipt"] = str(receipt_path)
    saved = repo.save_revision(latest, expected_revision=int(latest["revision"]))
    return {
        "success": True,
        "posted": True,
        "verified": True,
        "plan_id": plan_id,
        "revision": saved["revision"],
        "entry_id": entry_id,
        "simplicate_booking_id": matches[0].get("id"),
        "receipt": str(receipt_path),
        "message": "Booked and verified in Simplicate.",
    }
