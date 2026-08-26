"""Deterministic recovery for a missing/stale active-plan pointer."""
from __future__ import annotations

from typing import Any

from .storage import PlanNotFound, PlanRepository


def ensure_active_plan(repo: PlanRepository) -> dict[str, Any]:
    """Return active plan, or promote newest stored plan when only the pointer is missing."""
    try:
        return repo.get_active()
    except (PlanNotFound, KeyError, ValueError):
        rows = repo.list_plans(limit=200)
        if not rows:
            raise PlanNotFound("no stored plans")
        plan = repo.get_latest(rows[0]["plan_id"])
        repo._write_active_pointer(plan)
        return plan
