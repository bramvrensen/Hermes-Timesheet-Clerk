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
    """Perform only the duplicate preflight for a validated persisted plan entry.

    Mapping validity belongs to Generate / Refresh. Booking intentionally does not
    re-fetch assignments, services or hour types; if Simplicate changed after plan
    generation the POST may fail and the entry remains available for re-mapping.
    """
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
    day = str(entry.get("date") or "")[:10]
    booked = client.get_booked_hours(day, day)
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


def _validate_prepared_preview(repo: PlanRepository, plan_id: str, entry_id: str, preview: dict[str, Any]) -> None:
    """Cheaply prove a cached duplicate preflight still matches persisted state."""
    if str(preview.get("plan_id") or "") != plan_id or str(preview.get("entry_id") or "") != entry_id:
        raise StateConflict("Booking preflight does not belong to this task; run preflight again.")
    latest = repo.get_latest(plan_id)
    if int(preview.get("revision") or -1) != int(latest.get("revision") or -2):
        raise StateConflict("This plan changed after booking preflight. Re-open Book task and validate again.")
    current = next((row for row in latest.get("entries") or [] if row.get("entry_id") == entry_id), None)
    if not current:
        raise StateConflict(f"Entry not found: {entry_id}")
    if entry_id in _receipt_entry_ids(repo, plan_id):
        raise StateConflict("This entry already has a Timesheet Clerk booking receipt.")


def execute_single_entry_booking(
    repo: PlanRepository,
    plan_id: str,
    entry_id: str,
    *,
    prepared_preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Book one task using one duplicate preflight plus one post-write readback.

    Generate / Refresh already validated the mapping against its Simplicate
    snapshot. A prepared duplicate preview may therefore be reused after explicit
    confirmation while the persisted revision is unchanged. A later Simplicate
    masterdata change is allowed to fail naturally at POST; no receipt is written
    for a rejected POST and the entry remains reviewable.
    """
    preview = deepcopy(prepared_preview) if prepared_preview is not None else preview_single_entry(repo, plan_id, entry_id)
    if prepared_preview is not None:
        _validate_prepared_preview(repo, plan_id, entry_id, preview)
    if preview["status"] == "already_booked":
        raise StateConflict("This entry already has a Timesheet Clerk booking receipt.")
    if preview["status"] == "possible_duplicate":
        raise StateConflict("A matching Simplicate registration already exists; booking is blocked to prevent a duplicate.")
    if preview["status"] != "ready":
        raise StateConflict("Booking preflight is not ready; run preflight again.")

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
            "success": False, "posted": True, "verified": False, "receipt": str(receipt_path),
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
        "success": True, "posted": True, "verified": True, "plan_id": plan_id,
        "revision": saved["revision"], "entry_id": entry_id,
        "simplicate_booking_id": matches[0].get("id"), "receipt": str(receipt_path),
        "message": "Booked and verified in Simplicate.",
    }
