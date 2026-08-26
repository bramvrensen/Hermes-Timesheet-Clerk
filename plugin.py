"""HERMES plugin entrypoint for Timesheet Clerk 0.5.17.

0.5.17 hardens incremental sync against incomplete planner payload metadata and
removes destructive Fresh Start from the Hermes planner toolset. Fresh Start is
now a frontend-only explicit user action.
"""
from __future__ import annotations

from typing import Any

from . import plugin_legacy as _legacy
from .plugin_legacy import *  # noqa: F401,F403
from .timesheet_clerk.clockify import ClockifyClient
from .timesheet_clerk.config import ClockifyConfig
from .timesheet_clerk.source_hydration import assert_live_week_coverage, hydrate_plan_sources
from .timesheet_clerk.storage import PlanRepository
from .timesheet_clerk.sync_payload import find_sync_base_plan, normalize_incremental_plan
from .timesheet_clerk.update_lifecycle import build_update_handler


def handle_plan_create(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs

    def run() -> dict[str, Any]:
        repo = PlanRepository()
        incoming = _legacy.validate_plan(params["plan"])
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
        raw_incoming = params["plan"]
        existing = find_sync_base_plan(repo, raw_incoming)
        incoming = normalize_incremental_plan(existing, raw_incoming)

        # The stored working week is authoritative for the Clockify interval.
        # Never parse dates from an incomplete LLM delta before normalization.
        start, end = _legacy._clockify_interval_for_plan(existing)
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
    # the safe overrides, leaving all other behavior unchanged.
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

    # Deliberately DO NOT register timesheet_plan_fresh_start here. A background
    # planner must not have access to a destructive week reset as a recovery step.
