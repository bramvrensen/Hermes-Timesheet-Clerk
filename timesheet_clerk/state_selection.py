"""Deterministic recovery and week selection helpers."""
from __future__ import annotations

from typing import Any

from .storage import PlanNotFound, PlanRepository

_WORKING_STATUSES = {"DRAFT", "IN_REVIEW"}


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


def has_working_week(repo: PlanRepository, monday: str, sunday: str) -> bool:
    """Return True when any mutable working plan exists for the exact week.

    This is intentionally independent from the global active pointer. Historical
    week 34 may remain active while week 35 is absent, and the frontend must still
    offer creation of week 35.
    """
    for summary in repo.list_plans(limit=200):
        week = summary.get("week") or {}
        if str(week.get("monday") or "") != monday or str(week.get("sunday") or "") != sunday:
            continue
        try:
            plan = repo.get_latest(str(summary["plan_id"]))
        except PlanNotFound:
            continue
        if plan.get("status") in _WORKING_STATUSES:
            return True
    return False
