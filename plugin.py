"""HERMES plugin entrypoint for Timesheet Clerk 0.5.14.

0.5.14 keeps the existing workflow and adds deterministic Clockify source hydration
before plan create/sync so planner payloads cannot drop source titles or durations.
"""
from __future__ import annotations

from typing import Any

from . import plugin_legacy as _legacy
from .plugin_legacy import *  # noqa: F401,F403
from .timesheet_clerk.clockify import ClockifyClient
from .timesheet_clerk.config import ClockifyConfig
from .timesheet_clerk.fresh_start import fresh_start_week
from .timesheet_clerk.source_hydration import assert_live_week_coverage, hydrate_plan_sources
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


def handle_plan_create(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs

    def run() -> dict[str, Any]:
        repo = PlanRepository()
        incoming = params["plan"]
        start, end = _legacy._clockify_interval_for_plan(incoming)
        sources = ClockifyClient(ClockifyConfig.from_env()).get_time_entries(start, end)
        hydrated = hydrate_plan_sources(incoming, sources, require_full_coverage=True)
        saved = repo.create(hydrated, make_active=True)
        return _legacy._persist_source_baseline(repo, saved, sources)

    return _legacy._safe(run)


def handle_plan_sync(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs

    def run() -> dict[str, Any]:
        repo = PlanRepository()
        incoming = params["plan"]
        start, end = _legacy._clockify_interval_for_plan(incoming)
        sources = ClockifyClient(ClockifyConfig.from_env()).get_time_entries(start, end)
        hydrated = hydrate_plan_sources(incoming, sources, require_full_coverage=False)
        saved = _legacy.sync_week_plan(repo, hydrated)
        assert_live_week_coverage(saved, sources)
        saved = _legacy._persist_source_baseline(repo, saved, sources)
        return {"plan": saved, "summary": _legacy.plan_summary(saved)}

    return _legacy._safe(run)


def register(ctx) -> None:
    # plugin_legacy.register resolves these handler globals at call time. Swap only
    # create/sync so all other 0.5.13 behavior remains untouched.
    original_create = _legacy.handle_plan_create
    original_sync = _legacy.handle_plan_sync
    _legacy.handle_plan_create = handle_plan_create
    _legacy.handle_plan_sync = handle_plan_sync
    try:
        _legacy.register(ctx)
    finally:
        _legacy.handle_plan_create = original_create
        _legacy.handle_plan_sync = original_sync

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
