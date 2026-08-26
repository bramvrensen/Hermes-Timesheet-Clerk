"""Explicit fresh-start support for one mutable Timesheet Clerk week.

A fresh start removes only DRAFT/IN_REVIEW working plans for the requested week.
Immutable approvals, receipts, feedback and learned rules are intentionally left
untouched. The caller must rebuild the week from live Clockify and Simplicate data.
"""
from __future__ import annotations

import json
import shutil
from datetime import date
from typing import Any

from .storage import PlanRepository, StateConflict


def fresh_start_week(repo: PlanRepository, *, monday: str, sunday: str) -> dict[str, Any]:
    """Remove mutable plans for exactly one week and clear a stale active pointer."""
    start = date.fromisoformat(monday)
    end = date.fromisoformat(sunday)
    if end < start:
        raise ValueError("sunday must not be before monday")

    removable: list[str] = []
    protected: list[str] = []
    for summary in repo.list_plans(limit=100):
        week = summary.get("week") or {}
        if str(week.get("monday") or "") != monday or str(week.get("sunday") or "") != sunday:
            continue
        plan_id = str(summary.get("plan_id") or "")
        status = str(summary.get("status") or "")
        if status in {"DRAFT", "IN_REVIEW"}:
            removable.append(plan_id)
        else:
            protected.append(f"{plan_id}:{status}")

    if protected:
        raise StateConflict(
            "fresh start refused because immutable/non-working state exists for the week: "
            + ", ".join(protected)
        )

    active_plan_id = None
    if repo.active_file.exists():
        try:
            payload = json.loads(repo.active_file.read_text(encoding="utf-8"))
            active_plan_id = str(payload.get("plan_id") or "")
        except (OSError, json.JSONDecodeError):
            active_plan_id = None

    removed: list[str] = []
    for plan_id in removable:
        directory = repo.plans_dir / plan_id
        if directory.exists():
            shutil.rmtree(directory)
        removed.append(plan_id)

    if active_plan_id in set(removed):
        repo.active_file.unlink(missing_ok=True)

    return {
        "week": {"monday": monday, "sunday": sunday},
        "removed_plan_ids": removed,
        "removed_count": len(removed),
        "active_pointer_cleared": active_plan_id in set(removed),
        "fresh_start_required": True,
        "next_step": (
            "Re-read the complete Clockify week, config, learning context and required Simplicate context; "
            "map every Clockify entry from scratch with the normal AUTO/PROPOSE/ASK policy; then create a brand-new plan "
            "with timesheet_plan_create. Do not use timesheet_plan_sync for this fresh start."
        ),
    }
