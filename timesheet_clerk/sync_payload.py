"""Normalize incremental planner payloads against authoritative stored plan metadata."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .storage import PlanNotFound, PlanRepository

_STRUCTURAL_FIELDS = (
    "schema_version",
    "plan_id",
    "revision",
    "status",
    "generated_at",
    "week",
    "contract_hours_default",
    "target_hours",
)


def find_sync_base_plan(repo: PlanRepository, incoming: dict[str, Any]) -> dict[str, Any]:
    """Resolve the existing working plan without trusting LLM-supplied week dates."""
    plan_id = str(incoming.get("plan_id") or "").strip()
    if plan_id:
        try:
            plan = repo.get_latest(plan_id)
            if plan.get("status") in {"DRAFT", "IN_REVIEW"}:
                return plan
        except PlanNotFound:
            pass

    week = incoming.get("week") if isinstance(incoming.get("week"), dict) else {}
    monday = str((week or {}).get("monday") or "").strip()
    sunday = str((week or {}).get("sunday") or "").strip()
    if monday and sunday:
        for summary in repo.list_plans(limit=100):
            stored_week = summary.get("week") or {}
            if str(stored_week.get("monday") or "") == monday and str(stored_week.get("sunday") or "") == sunday:
                plan = repo.get_latest(summary["plan_id"])
                if plan.get("status") in {"DRAFT", "IN_REVIEW"}:
                    return plan

    return repo.get_active()


def normalize_incremental_plan(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Fill structural plan metadata from stored state while preserving delta entries.

    Mapping/planning fields inside ``entries`` remain planner-owned. Week identity,
    revision and other structural fields are storage-owned and therefore copied
    from the existing working plan when missing, blank or malformed in the LLM payload.
    """
    result = deepcopy(incoming)
    for key in _STRUCTURAL_FIELDS:
        value = result.get(key)
        invalid = value is None
        if key in {"plan_id", "status", "generated_at"}:
            invalid = not str(value or "").strip()
        elif key == "week":
            invalid = not isinstance(value, dict) or not str(value.get("monday") or "").strip() or not str(value.get("sunday") or "").strip()
        elif key in {"schema_version", "revision"}:
            invalid = not isinstance(value, int) or value < 1
        elif key in {"contract_hours_default", "target_hours"}:
            invalid = not isinstance(value, (int, float)) or value < 0
        if invalid:
            result[key] = deepcopy(existing.get(key))

    if not isinstance(result.get("entries"), list):
        result["entries"] = []
    return result
