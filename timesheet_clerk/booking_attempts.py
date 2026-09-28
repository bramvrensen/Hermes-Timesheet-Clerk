"""Persist intent before POST so a restart cannot silently retry an uncertain booking."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Callable, Any

from .http import IntegrationError
from .storage import PlanRepository, StateConflict, _atomic_write_json, _read_json


def guarded_post(repo: PlanRepository, plan_id: str, entry_id: str, payload: dict, post: Callable[[], Any], *, source_ids: list[str] | None = None) -> Any:
    key = sha256(f"{plan_id}\0{entry_id}".encode()).hexdigest()
    path = repo.root / "booking_attempts" / f"{key}.json"
    if path.exists() and _read_json(path).get("state") != "REJECTED":
        raise StateConflict("An earlier Timesheet Clerk booking attempt may have reached Simplicate. "
                            "Check Simplicate and the saved booking attempt before retrying.")
    sources = set(source_ids or [])
    if sources:
        for prior in (repo.root / "booking_attempts").glob("*.json"):
            recorded = _read_json(prior)
            if recorded.get("state") != "REJECTED" and sources.intersection(recorded.get("clockify_source_ids") or []):
                raise StateConflict("These Clockify sources already have a Timesheet Clerk booking attempt. "
                                    "Rebuilding a plan does not authorize another POST.")
    attempt = {"plan_id": plan_id, "entry_id": entry_id, "payload": payload, "state": "PENDING",
               "clockify_source_ids": sorted(sources),
               "timestamp": datetime.now(timezone.utc).isoformat()}
    _atomic_write_json(path, attempt, root=repo.root)
    try:
        response = post()
    except Exception as exc:
        # Only explicit rejection proves there was no booking. Timeouts/5xx are ambiguous.
        rejected = isinstance(exc, IntegrationError) and exc.status_code in {400, 401, 403, 422}
        attempt.update(state="REJECTED" if rejected else "UNKNOWN", message=str(exc))
        _atomic_write_json(path, attempt, root=repo.root)
        raise
    attempt.update(state="ACCEPTED", response=response)
    _atomic_write_json(path, attempt, root=repo.root)
    return response
