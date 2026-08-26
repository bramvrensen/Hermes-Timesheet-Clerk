"""HERMES plugin entrypoint for Timesheet Clerk 0.5.13.

0.5.13 deliberately wraps the 0.5.12 implementation and adds only one new
capability: an explicit fresh start for one mutable week.
"""
from __future__ import annotations

from typing import Any

from . import plugin_legacy as _legacy
from .plugin_legacy import *  # noqa: F401,F403
from .timesheet_clerk.fresh_start import fresh_start_week
from .timesheet_clerk.storage import PlanRepository


def handle_plan_fresh_start(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _legacy._safe(
        lambda: fresh_start_week(
            PlanRepository(),
            monday=str(params["monday"]),
            sunday=str(params["sunday"]),
        )
    )


def register(ctx) -> None:
    _legacy.register(ctx)
    ctx.register_tool(
        name="timesheet_plan_fresh_start",
        toolset=_legacy.TOOLSET,
        schema=_legacy._schema(
            "timesheet_plan_fresh_start",
            "Explicitly discard mutable DRAFT/IN_REVIEW Timesheet Clerk plan state for one exact week so the planner can rebuild and remap the entire week from live sources. Never deletes approvals, receipts, feedback or learned rules.",
            {
                "monday": {"type": "string", "description": "Week Monday, YYYY-MM-DD"},
                "sunday": {"type": "string", "description": "Week Sunday, YYYY-MM-DD"},
            },
            ["monday", "sunday"],
        ),
        handler=handle_plan_fresh_start,
    )
