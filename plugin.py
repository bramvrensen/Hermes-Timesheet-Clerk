"""HERMES Timesheet Clerk 0.6 plugin entrypoint.

0.6 removes LLM-authored plan payloads. Hermes receives deterministic mapping work
and returns mapping decisions; Python owns plan construction, merge, source fidelity,
revisioning and persistence.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .timesheet_clerk.clockify import ClockifyClient
from .timesheet_clerk.config import ClockifyConfig, ConfigError, SimplicateConfig
from .timesheet_clerk.http import IntegrationError
from .timesheet_clerk.orchestration import apply_mapping_decisions, find_working_week, prepare_mapping_work
from .timesheet_clerk.runtime import ensure_profile_skill_registration, ensure_runtime_skill, read_config
from .timesheet_clerk.simplicate import SimplicateClient
from .timesheet_clerk.storage import PlanNotFound, PlanRepository
from .timesheet_clerk.sync import plan_summary, source_delta
from .timesheet_clerk.update_lifecycle import build_update_handler

PLUGIN_ROOT = Path(__file__).resolve().parent
DEFAULT_TIMESHEET_SKILL = PLUGIN_ROOT / "skills" / "productivity" / "timesheet-clerk" / "SKILL.md"
TOOLSET = "timesheet_clerk"


def _ok(data: Any) -> str:
    return json.dumps({"success": True, "data": data}, ensure_ascii=False, default=str)


def _error(exc: Exception) -> str:
    if isinstance(exc, IntegrationError):
        payload = exc.as_dict(); payload["success"] = False
        return json.dumps(payload, ensure_ascii=False, default=str)
    if isinstance(exc, ConfigError):
        return json.dumps({"success": False, "error_type": "configuration_error", "message": str(exc), "retryable": False})
    return json.dumps({"success": False, "error_type": "unexpected_error", "message": str(exc), "retryable": False})


def _safe(call: Callable[[], Any]) -> str:
    try:
        return _ok(call())
    except Exception as exc:
        return _error(exc)


def _clockify_interval(monday: str, sunday: str) -> tuple[str, str]:
    start_day = date.fromisoformat(monday)
    end_day = date.fromisoformat(sunday)
    if start_day.weekday() != 0 or end_day < start_day:
        raise ValueError("invalid week boundaries")
    tz = ZoneInfo(os.environ.get("TZ") or "Europe/Amsterdam")
    return (
        datetime.combine(start_day, time.min, tzinfo=tz).isoformat(),
        datetime.combine(end_day, time(23, 59, 59), tzinfo=tz).isoformat(),
    )


def _live_clockify_week(monday: str, sunday: str) -> list[dict[str, Any]]:
    start, end = _clockify_interval(monday, sunday)
    return ClockifyClient(ClockifyConfig.from_env()).get_time_entries(start, end)


def handle_mapping_prepare(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    def run() -> dict[str, Any]:
        monday, sunday = str(params["monday"]), str(params["sunday"])
        sources = _live_clockify_week(monday, sunday)
        return prepare_mapping_work(
            PlanRepository(), sources, monday=monday, sunday=sunday, rebuild=bool(params.get("rebuild", False))
        )
    return _safe(run)


def handle_mapping_apply(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    def run() -> dict[str, Any]:
        monday, sunday = str(params["monday"]), str(params["sunday"])
        sources = _live_clockify_week(monday, sunday)
        return apply_mapping_decisions(
            PlanRepository(), sources, monday=monday, sunday=sunday,
            decisions=params.get("decisions") or [], rebuild=bool(params.get("rebuild", False)),
        )
    return _safe(run)


def handle_clockify_entries(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _safe(lambda: ClockifyClient(ClockifyConfig.from_env()).get_time_entries(params["start"], params["end"]))


def handle_sync_probe(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    def run() -> dict[str, Any]:
        monday, sunday = str(params["monday"]), str(params["sunday"])
        sources = _live_clockify_week(monday, sunday)
        repo = PlanRepository(); plan = find_working_week(repo, monday, sunday)
        delta = source_delta(plan, sources)
        return {
            "plan_exists": plan is not None,
            "plan_id": plan.get("plan_id") if plan else None,
            "has_changes": delta["has_changes"],
            "source_delta": delta,
            "summary": plan_summary(plan, source_delta=delta) if plan else None,
        }
    return _safe(run)


def handle_simplicate_context(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _safe(lambda: SimplicateClient(SimplicateConfig.from_env()).get_context(params["start_date"], params["end_date"]))


def handle_simplicate_assignments(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _safe(lambda: SimplicateClient(SimplicateConfig.from_env()).get_planned_assignments(params["start_date"], params["end_date"]))


def handle_simplicate_booking_assignments(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _safe(lambda: SimplicateClient(SimplicateConfig.from_env()).get_booking_assignments(params["start_date"], params["end_date"]))


def handle_simplicate_available_assignments(params: dict[str, Any], **kwargs: Any) -> str:
    return handle_simplicate_booking_assignments(params, **kwargs)


def handle_simplicate_debug_assignments(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _safe(lambda: SimplicateClient(SimplicateConfig.from_env()).debug_assignment_shapes(int(params.get("limit", 3))))


def handle_simplicate_booked_hours(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _safe(lambda: SimplicateClient(SimplicateConfig.from_env()).get_booked_hours(params["start_date"], params["end_date"]))


def handle_plan_active(params: dict[str, Any], **kwargs: Any) -> str:
    del params, kwargs
    def run() -> dict[str, Any]:
        repo = PlanRepository()
        try:
            return repo.get_active()
        except PlanNotFound:
            rows = repo.list_plans(limit=100)
            if not rows:
                raise
            return repo.get_latest(rows[0]["plan_id"])
    return _safe(run)


def handle_plan_summary(params: dict[str, Any], **kwargs: Any) -> str:
    del params, kwargs
    def run() -> dict[str, Any]:
        repo = PlanRepository()
        try:
            plan = repo.get_active()
        except PlanNotFound:
            rows = repo.list_plans(limit=100)
            if not rows:
                raise
            plan = repo.get_latest(rows[0]["plan_id"])
        return plan_summary(plan)
    return _safe(run)


def handle_plan_list(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _safe(lambda: PlanRepository().list_plans(limit=int(params.get("limit", 20))))


def handle_config_get(params: dict[str, Any], **kwargs: Any) -> str:
    del params, kwargs
    return _safe(read_config)


def handle_learning_context(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    repo = PlanRepository()
    return _safe(lambda: {"feedback_events": repo.feedback(limit=int(params.get("feedback_limit", 200))), "rules": repo.read_rules()})


def _schedule_gateway_restart(delay: float = 1.5) -> None:
    try:
        from gateway.restart import is_gateway_supervisor_process
    except Exception as exc:
        raise RuntimeError(f"Hermes gateway restart helper unavailable: {exc}") from exc
    if not is_gateway_supervisor_process():
        raise RuntimeError("timesheet_update must run inside the supervised Hermes gateway")
    timer = threading.Timer(delay, lambda: os.kill(os.getpid(), signal.SIGUSR1))
    timer.daemon = True; timer.start()


def _git(*args: str, timeout: int = 30, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", f"safe.directory={PLUGIN_ROOT}", "-C", str(PLUGIN_ROOT), *args],
        capture_output=True, text=True, timeout=timeout, check=check,
    )


def _self_update_smoke_test() -> dict[str, Any]:
    compile_result = subprocess.run([sys.executable, "-m", "compileall", "-q", str(PLUGIN_ROOT)], capture_output=True, text=True, timeout=60)
    if compile_result.returncode != 0:
        raise RuntimeError(compile_result.stderr.strip() or "compileall failed")
    uv = shutil.which("uv")
    if not uv:
        return {"compileall": "passed", "pytest": "skipped (uv not available)"}
    env = os.environ.copy(); env["PYTHONPATH"] = str(PLUGIN_ROOT)
    test_result = subprocess.run(
        [uv, "run", "--with", "pytest", "pytest", "--rootdir=tests", "--import-mode=importlib", "-q", "tests"],
        cwd=str(PLUGIN_ROOT), env=env, capture_output=True, text=True, timeout=180,
    )
    if test_result.returncode != 0:
        raise RuntimeError(f"updated code failed tests; gateway restart cancelled:\n{test_result.stdout[-4000:]}\n{test_result.stderr[-4000:]}")
    return {"compileall": "passed", "pytest": test_result.stdout.strip()}


handle_update = build_update_handler(sys.modules[__name__])


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": required}}


def _date_range_properties() -> dict[str, Any]:
    return {"start_date": {"type": "string", "description": "YYYY-MM-DD"}, "end_date": {"type": "string", "description": "YYYY-MM-DD"}}


def register(ctx) -> None:
    runtime_skill = ensure_runtime_skill(DEFAULT_TIMESHEET_SKILL)
    try: ensure_profile_skill_registration(str(read_config().get("planner_profile") or "atlas"))
    except Exception: pass
    ctx.register_skill("timesheet-clerk", runtime_skill, "Prepare, reconcile and review weekly timesheet booking plans from Clockify and Simplicate.")

    ctx.register_tool(name="timesheet_config_get", toolset=TOOLSET, schema=_schema("timesheet_config_get", "Read active Timesheet Clerk runtime policy.", {}, []), handler=handle_config_get)
    ctx.register_tool(name="timesheet_clockify_entries", toolset=TOOLSET, schema=_schema("timesheet_clockify_entries", "Read normalized Clockify time entries for an ISO-8601 interval.", {"start":{"type":"string"},"end":{"type":"string"}}, ["start","end"]), handler=handle_clockify_entries)
    ctx.register_tool(name="timesheet_sync_probe", toolset=TOOLSET, schema=_schema("timesheet_sync_probe", "Read-only deterministic week delta probe.", {"monday":{"type":"string"},"sunday":{"type":"string"}}, ["monday","sunday"]), handler=handle_sync_probe)
    ctx.register_tool(name="timesheet_mapping_prepare", toolset=TOOLSET, schema=_schema(
        "timesheet_mapping_prepare",
        "Prepare exact Clockify mapping work. The returned work_items are the ONLY records the planner must decide; Python owns the plan itself.",
        {"monday":{"type":"string"},"sunday":{"type":"string"},"rebuild":{"type":"boolean","description":"True only for an explicit full rebuild; existing plan is preserved until replacement succeeds."}},
        ["monday","sunday"],
    ), handler=handle_mapping_prepare)
    ctx.register_tool(name="timesheet_mapping_apply", toolset=TOOLSET, schema=_schema(
        "timesheet_mapping_apply",
        "Apply mapping decisions to deterministic Clerk state. Never accepts a plan payload. Re-fetches Clockify, validates complete decisions and atomically creates or revises the week.",
        {
            "monday":{"type":"string"},"sunday":{"type":"string"},"rebuild":{"type":"boolean"},
            "decisions":{"type":"array","items":{"type":"object","properties":{
                "source_id":{"type":"string"},"tier":{"type":"string","enum":["AUTO","PROPOSE","ASK"]},
                "booking_mode":{"type":"string","enum":["assignment","direct"]},
                "assignment":{"type":"object"},"direct_mapping":{"type":"object"},"ignored":{"type":"boolean"},
                "why":{"type":"string"},"why_not_auto":{"type":"string"},"confidence":{"type":"number"},
                "mapping_source":{},"billable":{"type":"boolean"}
            },"required":["source_id","tier","booking_mode"]}}
        }, ["monday","sunday","decisions"]
    ), handler=handle_mapping_apply)

    ctx.register_tool(name="timesheet_simplicate_context", toolset=TOOLSET, schema=_schema("timesheet_simplicate_context", "Read Simplicate masterdata, planned assignments and booking candidates.", _date_range_properties(), ["start_date","end_date"]), handler=handle_simplicate_context)
    ctx.register_tool(name="timesheet_simplicate_assignments", toolset=TOOLSET, schema=_schema("timesheet_simplicate_assignments", "Read actual planned Simplicate assignments.", _date_range_properties(), ["start_date","end_date"]), handler=handle_simplicate_assignments)
    ctx.register_tool(name="timesheet_simplicate_booking_assignments", toolset=TOOLSET, schema=_schema("timesheet_simplicate_booking_assignments", "Read credible assignment booking targets.", _date_range_properties(), ["start_date","end_date"]), handler=handle_simplicate_booking_assignments)
    ctx.register_tool(name="timesheet_simplicate_available_assignments", toolset=TOOLSET, schema=_schema("timesheet_simplicate_available_assignments", "Compatibility alias for booking assignment targets.", _date_range_properties(), ["start_date","end_date"]), handler=handle_simplicate_available_assignments)
    ctx.register_tool(name="timesheet_simplicate_debug_assignments", toolset=TOOLSET, schema=_schema("timesheet_simplicate_debug_assignments", "Read a small safe projection of assignment shapes for diagnostics.", {"limit":{"type":"integer"}}, []), handler=handle_simplicate_debug_assignments)
    ctx.register_tool(name="timesheet_simplicate_booked_hours", toolset=TOOLSET, schema=_schema("timesheet_simplicate_booked_hours", "Read existing Simplicate booked hours.", _date_range_properties(), ["start_date","end_date"]), handler=handle_simplicate_booked_hours)
    ctx.register_tool(name="timesheet_plan_active", toolset=TOOLSET, schema=_schema("timesheet_plan_active", "Read active plan, falling back to newest stored plan when active pointer is absent.", {}, []), handler=handle_plan_active)
    ctx.register_tool(name="timesheet_plan_summary", toolset=TOOLSET, schema=_schema("timesheet_plan_summary", "Read deterministic summary of active/newest plan.", {}, []), handler=handle_plan_summary)
    ctx.register_tool(name="timesheet_plan_list", toolset=TOOLSET, schema=_schema("timesheet_plan_list", "List stored Timesheet Clerk plans.", {"limit":{"type":"integer"}}, []), handler=handle_plan_list)
    ctx.register_tool(name="timesheet_learning_context", toolset=TOOLSET, schema=_schema("timesheet_learning_context", "Read feedback evidence and learned rules.", {"feedback_limit":{"type":"integer"}}, []), handler=handle_learning_context)
    ctx.register_tool(name="timesheet_update", toolset=TOOLSET, schema=_schema("timesheet_update", "Update Timesheet Clerk from Git, run smoke tests, and request frontend/gateway restart.", {}, []), handler=handle_update)
