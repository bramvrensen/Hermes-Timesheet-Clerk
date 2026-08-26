"""HERMES plugin entrypoint for Timesheet Clerk 0.5.14.

0.5.14 keeps the existing workflow, adds deterministic Clockify source hydration
before plan create/sync, and keeps the separate Streamlit frontend in lockstep
with plugin updates.
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
from .timesheet_clerk.update_lifecycle import build_update_handler


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


# The manifest on disk is authoritative for version reporting. This lifecycle
# also requests the managed Streamlit child to restart after a real update.
handle_update = build_update_handler(_legacy)


def register(ctx) -> None:
    # plugin_legacy.register resolves handler globals at call time. Swap only
    # the 0.5.14 overrides, leaving all other behavior unchanged.
    original_create = _legacy.handle_plan_create
    original_sync = _legacy.handle_plan_sync
    original_update = _legacy.handle_update
    _legacy.handle_plan_create = handle_plan_create
    _legacy.handle_plan_sync = handle_plan_sync
    _legacy.handle_update = handle_update
    try:
        _legacy.register(ctx)
    finally:
        _legacy.handle_plan_create = original_create
        _legacy.handle_plan_sync = original_sync
        _legacy.handle_update = original_update

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
