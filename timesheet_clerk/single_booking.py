"""Guarded Simplicate booking for task, day and week review actions."""
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


def _entry_for_id(plan: dict[str, Any], entry_id: str) -> dict[str, Any]:
    entry = next((row for row in plan.get("entries") or [] if row.get("entry_id") == entry_id), None)
    if not entry:
        raise StateConflict(f"Entry not found: {entry_id}")
    return entry


def preview_single_entry(repo: PlanRepository, plan_id: str, entry_id: str) -> dict[str, Any]:
    """Perform only the duplicate preflight for a validated persisted plan entry."""
    plan = repo.get_latest(plan_id)
    entry = _entry_for_id(plan, entry_id)
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


def preview_entry_batch(repo: PlanRepository, plan_id: str, entry_ids: list[str]) -> dict[str, Any]:
    """Preflight a day/week with one Simplicate read for the whole date range."""
    plan = repo.get_latest(plan_id)
    wanted = list(dict.fromkeys(str(value) for value in entry_ids if value))
    if not wanted:
        raise StateConflict("No bookable entries were selected.")
    entries = [_entry_for_id(plan, entry_id) for entry_id in wanted]
    for entry in entries:
        ready, reason = task_booking_ready(entry)
        if not ready:
            raise StateConflict(f"{entry.get('entry_id')}: {reason}")

    client = SimplicateClient(SimplicateConfig.from_env())
    payloads = {str(entry["entry_id"]): _entry_payload(entry, client.config.employee_id) for entry in entries}
    dates = [str(entry.get("date") or "")[:10] for entry in entries]
    booked = client.get_booked_hours(min(dates), max(dates))
    receipted = _receipt_entry_ids(repo, plan_id)
    rows: list[dict[str, Any]] = []
    for entry in entries:
        entry_id = str(entry["entry_id"])
        payload = payloads[entry_id]
        matches = [_existing_projection(item) for item in booked if _looks_like_same_registration(payload, item)]
        status = "already_booked" if entry_id in receipted else "possible_duplicate" if matches else "ready"
        rows.append({"entry_id": entry_id, "entry": deepcopy(entry), "payload": payload, "status": status, "matches": matches})
    return {
        "plan_id": plan_id,
        "revision": plan["revision"],
        "entry_ids": wanted,
        "start_date": min(dates),
        "end_date": max(dates),
        "rows": rows,
        "ready_count": sum(1 for row in rows if row["status"] == "ready"),
        "already_booked_count": sum(1 for row in rows if row["status"] == "already_booked"),
        "possible_duplicate_count": sum(1 for row in rows if row["status"] == "possible_duplicate"),
    }


def _validate_prepared_preview(repo: PlanRepository, plan_id: str, entry_id: str, preview: dict[str, Any]) -> None:
    if str(preview.get("plan_id") or "") != plan_id or str(preview.get("entry_id") or "") != entry_id:
        raise StateConflict("Booking preflight does not belong to this task; run preflight again.")
    latest = repo.get_latest(plan_id)
    if int(preview.get("revision") or -1) != int(latest.get("revision") or -2):
        raise StateConflict("This plan changed after booking preflight. Re-open Book task and validate again.")
    _entry_for_id(latest, entry_id)
    if entry_id in _receipt_entry_ids(repo, plan_id):
        raise StateConflict("This entry already has a Timesheet Clerk booking receipt.")


def _write_and_verify(repo: PlanRepository, plan_id: str, revision: Any, entry: dict[str, Any], payload: dict[str, Any], client: SimplicateClient) -> dict[str, Any]:
    entry_id = str(entry["entry_id"])
    response = _post_hours(client.config, payload)
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    receipt = {
        "timestamp": timestamp, "plan_id": plan_id, "revision": revision, "entry_id": entry_id,
        "clockify_source_ids": list(entry.get("clockify_source_ids") or []),
        "simplicate_payload": deepcopy(payload), "simplicate_response": deepcopy(response), "verification_state": "PENDING",
    }
    receipt_path = repo.write_receipt(receipt)
    day = str(entry.get("date") or "")[:10]
    booked = client.get_booked_hours(day, day)
    matches = [item for item in booked if _looks_like_same_registration(payload, item)]
    if not matches:
        return {"success": False, "posted": True, "verified": False, "entry_id": entry_id, "receipt": str(receipt_path), "message": "Simplicate accepted the POST, but Clerk could not verify it by readback. Receipt preserved; retry is blocked."}

    latest = repo.get_latest(plan_id)
    persisted = _entry_for_id(latest, entry_id)
    persisted["reconciliation_state"] = "BOOKED"
    persisted["booked_at"] = timestamp
    persisted["simplicate_booking_id"] = matches[0].get("id")
    persisted["booking_receipt"] = str(receipt_path)
    saved = repo.save_revision(latest, expected_revision=int(latest["revision"]))
    return {"success": True, "posted": True, "verified": True, "plan_id": plan_id, "revision": saved["revision"], "entry_id": entry_id, "simplicate_booking_id": matches[0].get("id"), "receipt": str(receipt_path), "message": "Booked and verified in Simplicate."}


def execute_single_entry_booking(repo: PlanRepository, plan_id: str, entry_id: str, *, prepared_preview: dict[str, Any] | None = None) -> dict[str, Any]:
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
    return _write_and_verify(repo, plan_id, preview["revision"], preview["entry"], preview["payload"], client)


def execute_entry_batch(repo: PlanRepository, plan_id: str, prepared_preview: dict[str, Any]) -> dict[str, Any]:
    """Book a preflighted day/week sequentially; failures stay reviewable and do not stop later rows."""
    latest = repo.get_latest(plan_id)
    if str(prepared_preview.get("plan_id") or "") != plan_id or int(prepared_preview.get("revision") or -1) != int(latest.get("revision") or -2):
        raise StateConflict("This plan changed after booking preflight. Re-open the batch booking action and validate again.")
    blocked = [row for row in prepared_preview.get("rows") or [] if row.get("status") == "possible_duplicate"]
    if blocked:
        raise StateConflict(f"Booking blocked: {len(blocked)} selected row(s) have possible existing Simplicate registrations.")

    client = SimplicateClient(SimplicateConfig.from_env())
    results: list[dict[str, Any]] = []
    for row in prepared_preview.get("rows") or []:
        if row.get("status") == "already_booked":
            results.append({"entry_id": row["entry_id"], "success": True, "verified": True, "skipped": True, "message": "Already booked."})
            continue
        entry_id = str(row["entry_id"])
        try:
            current = repo.get_latest(plan_id)
            entry = _entry_for_id(current, entry_id)
            if entry.get("reconciliation_state") == "BOOKED" or entry_id in _receipt_entry_ids(repo, plan_id):
                results.append({"entry_id": entry_id, "success": True, "verified": True, "skipped": True, "message": "Already booked."})
                continue
            result = _write_and_verify(repo, plan_id, prepared_preview["revision"], entry, row["payload"], client)
            results.append(result)
        except Exception as exc:
            results.append({"entry_id": entry_id, "success": False, "verified": False, "message": str(exc)})
    return {
        "plan_id": plan_id,
        "requested_count": len(prepared_preview.get("rows") or []),
        "booked_count": sum(1 for row in results if row.get("verified") and not row.get("skipped")),
        "skipped_count": sum(1 for row in results if row.get("skipped")),
        "failed_count": sum(1 for row in results if not row.get("success")),
        "results": results,
    }
