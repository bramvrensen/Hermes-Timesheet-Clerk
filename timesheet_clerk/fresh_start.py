"""Removed destructive Fresh Start API.

0.6 rebuilds a week by creating and validating a replacement plan before moving
the active pointer. This compatibility module intentionally cannot delete state.
"""
from __future__ import annotations

from .storage import PlanRepository, StateConflict


def fresh_start_week(repo: PlanRepository, *, monday: str, sunday: str) -> dict:
    del repo, monday, sunday
    raise StateConflict(
        "destructive fresh_start_week was removed in Timesheet Clerk 0.6; use the safe rebuild workflow"
    )
