"""HERMES plugin implementation for Timesheet Clerk."""
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
from .timesheet_clerk.contracts import utc_now, validate_plan
from .timesheet_clerk.http import IntegrationError
from .timesheet_clerk.runtime import (
    ensure_profile_skill_registration,
    ensure_runtime_skill,
    read_config,
)
from .timesheet_clerk.simplicate import SimplicateClient
from .timesheet_clerk.storage import PlanNotFound, PlanRepository, _atomic_write_json
from .timesheet_clerk.sync import attach_source_snapshots, plan_summary, source_delta
from .timesheet_clerk.working import sync_week_plan

PLUGIN_ROOT = Path(__file__).resolve().parent
DEFAULT_TIMESHEET_SKILL = PLUGIN_ROOT / "skills" / "productivity" / "timesheet-clerk" / "SKILL.md"
TOOLSET = "timesheet_clerk"


def _ok(data: Any) -> str:
    return json.dumps({"success": True, "data": data}, ensure_ascii=False, default=str)


def _error(exc: Exception) -> str:
    if isinstance(exc, IntegrationError):
        payload = exc.as_dict()
        payload["success"] = False
        return json.dumps(payload, ensure_ascii=False, default=str)
    if isinstance(exc, ConfigError):
        return json.dumps({"success": False, "error_type": "configuration_error", "message": str(exc), "retryable": False})
    return json.dumps({"success": False, "error_type": "unexpected_error", "message": str(exc), "retryable": False})


def _safe(call: Callable[[], Any]) -> str:
    try:
        return _ok(call())
    except Exception as exc:
        return _error(exc)


def _iso_date(value: str) -> date:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def _plan_for_interval(repo: PlanRepository, start: str, end: str) -> dict[str, Any] | None:
    """Resolve the open/stored plan that covers the requested Clockify interval."""
    start_day = _iso_date(start)
    end_day = _iso_date(end)
    for summary in repo.list_plans(limit=100):
        week = summary.get("week") or {}
        try:
            monday = date.fromisoformat(str(week.get("monday") or ""))
            sunday = date.fromisoformat(str(week.get("sunday") or ""))
        except ValueError:
            continue
        if monday <= start_day <= sunday and monday <= end_day <= sunday:
            return repo.get_latest(summary["plan_id"])
    try:
        return repo.get_active()
    except PlanNotFound:
        return None


def _clockify_interval_for_plan(plan: dict[str, Any]) -> tuple[str, str]:
    week = plan.get("week") or {}
    monday = str(week.get("monday") or "")
    sunday = str(week.get("sunday") or "")
    tz = ZoneInfo(os.environ.get("TZ") or "Europe/Amsterdam")
    start = datetime.combine(date.fromisoformat(monday), time.min, tzinfo=tz)
    end = datetime.combine(date.fromisoformat(sunday), time(23, 59, 59), tzinfo=tz)
    return start.isoformat(), end.isoformat()


def _persist_source_baseline(repo: PlanRepository, plan: dict[str, Any], entries: list[dict[str, Any]], *, make_active: bool = True) -> dict[str, Any]:
    updated = attach_source_snapshots(plan, entries)
    updated["source_sync_at"] = utc_now()
    updated = validate_plan(updated)
    path = repo._revision_path(updated["plan_id"], int(updated["revision"]))
    _atomic_write_json(path, updated, root=repo.root)
    if make_active:
        repo._write_active_pointer(updated)
    return updated


def handle_clockify_entries(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _safe(lambda: ClockifyClient(ClockifyConfig.from_env()).get_time_entries(params["start"], params["end"]))


def handle_sync_probe(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs

    def run() -> dict[str, Any]:
        repo = PlanRepository()
        plan = _plan_for_interval(repo, params["start"], params["end"])
        entries = ClockifyClient(ClockifyConfig.from_env()).get_time_entries(params["start"], params["end"])
        delta = source_delta(plan, entries)
        return {
            "plan_exists": plan is not None,
            "plan_id": plan.get("plan_id") if plan else None,
            "has_changes": delta["has_changes"],
            "source_delta": delta,
            "summary": plan_summary(plan, source_delta=delta) if plan else None,
        }

    return _safe(run)


def handle_source_rebaseline(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs

    def run() -> dict[str, Any]:
        repo = PlanRepository()
        plan = _plan_for_interval(repo, params["start"], params["end"])
        if plan is None:
            raise PlanNotFound("no plan exists for requested interval")
        entries = ClockifyClient(ClockifyConfig.from_env()).get_time_entries(params["start"], params["end"])
        saved = _persist_source_baseline(repo, plan, entries, make_active=True)
        return {
            "plan_id": saved["plan_id"],
            "baseline_count": len(entries),
            "summary": plan_summary(saved),
            "message": "Clockify source baseline refreshed without changing human review values.",
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


def handle_plan_create(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs

    def run() -> dict[str, Any]:
        repo = PlanRepository()
        saved = repo.create(params["plan"], make_active=True)
        start, end = _clockify_interval_for_plan(saved)
        entries = ClockifyClient(ClockifyConfig.from_env()).get_time_entries(start, end)
        return _persist_source_baseline(repo, saved, entries)

    return _safe(run)


def handle_plan_sync(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs

    def run() -> dict[str, Any]:
        repo = PlanRepository()
        saved = sync_week_plan(repo, params["plan"])
        start, end = _clockify_interval_for_plan(saved)
        entries = ClockifyClient(ClockifyConfig.from_env()).get_time_entries(start, end)
        saved = _persist_source_baseline(repo, saved, entries)
        return {"plan": saved, "summary": plan_summary(saved)}

    return _safe(run)


def handle_plan_active(params: dict[str, Any], **kwargs: Any) -> str:
    del params, kwargs
    return _safe(lambda: PlanRepository().get_active())


def handle_plan_summary(params: dict[str, Any], **kwargs: Any) -> str:
    del params, kwargs
    return _safe(lambda: plan_summary(PlanRepository().get_active()))


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
    """Ask Hermes' supervised gateway to restart after the current turn."""
    try:
        from gateway.restart import is_gateway_supervisor_process
    except Exception as exc:
        raise RuntimeError(f"Hermes gateway restart helper unavailable: {exc}") from exc
    if not is_gateway_supervisor_process():
        raise RuntimeError("timesheet_update must run inside the supervised Hermes gateway")

    def request() -> None:
        os.kill(os.getpid(), signal.SIGUSR1)

    timer = threading.Timer(delay, request)
    timer.daemon = True
    timer.start()


def _git(*args: str, timeout: int = 30, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["git", "-c", f"safe.directory={PLUGIN_ROOT}", "-C", str(PLUGIN_ROOT), *args]
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=check)


def _self_update_smoke_test() -> dict[str, Any]:
    compile_result = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", str(PLUGIN_ROOT)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if compile_result.returncode != 0:
        raise RuntimeError(compile_result.stderr.strip() or "compileall failed")

    uv = shutil.which("uv")
    if not uv:
        return {"compileall": "passed", "pytest": "skipped (uv not available)"}
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PLUGIN_ROOT)
    test_result = subprocess.run(
        [
            uv,
            "run",
            "--with",
            "pytest",
            "pytest",
            "--rootdir=tests",
            "--import-mode=importlib",
            "-q",
            "tests",
        ],
        cwd=str(PLUGIN_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if test_result.returncode != 0:
        raise RuntimeError(f"updated code failed tests; gateway restart cancelled:\n{test_result.stdout[-4000:]}\n{test_result.stderr[-4000:]}")
    return {"compileall": "passed", "pytest": test_result.stdout.strip()}


def handle_update(params: dict[str, Any], **kwargs: Any) -> str:
    del params, kwargs

    def run() -> dict[str, Any]:
        if not (PLUGIN_ROOT / ".git").exists():
            raise RuntimeError("Timesheet Clerk is not installed as a Git checkout; self-update is unavailable")
        dirty = _git("status", "--porcelain").stdout.strip()
        if dirty:
            raise RuntimeError("Timesheet Clerk checkout has local changes; refusing to pull over them")
        before = _git("rev-parse", "HEAD").stdout.strip()
        pull = _git("pull", "--ff-only", timeout=120, check=False)
        if pull.returncode != 0:
            raise RuntimeError(pull.stderr.strip() or pull.stdout.strip() or f"git pull exited {pull.returncode}")
        after = _git("rev-parse", "HEAD").stdout.strip()
        tests = _self_update_smoke_test()
        cfg = read_config()
        profile = str(cfg.get("planner_profile") or "atlas")
        ensure_profile_skill_registration(profile)
        ensure_runtime_skill(DEFAULT_TIMESHEET_SKILL)
        _schedule_gateway_restart()
        return {
            "before_commit": before,
            "after_commit": after,
            "updated": before != after,
            "git_output": pull.stdout.strip(),
            "smoke_test": tests,
            "planner_profile": profile,
            "gateway_restart_scheduled": True,
            "note": "Gateway will restart gracefully after this turn; a fresh session will use the updated plugin.",
        }

    return _safe(run)


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": required}}


def _date_range_properties() -> dict[str, Any]:
    return {"start_date": {"type": "string", "description": "YYYY-MM-DD"}, "end_date": {"type": "string", "description": "YYYY-MM-DD"}}


def register(ctx) -> None:
    runtime_skill = ensure_runtime_skill(DEFAULT_TIMESHEET_SKILL)
    try:
        ensure_profile_skill_registration(str(read_config().get("planner_profile") or "atlas"))
    except Exception:
        pass
    ctx.register_skill("timesheet-clerk", runtime_skill, "Prepare, reconcile and review weekly timesheet booking plans from Clockify and Simplicate.")
    ctx.register_tool(name="timesheet_config_get", toolset=TOOLSET, schema=_schema("timesheet_config_get", "Read active Timesheet Clerk runtime policy.", {}, []), handler=handle_config_get)
    ctx.register_tool(name="timesheet_clockify_entries", toolset=TOOLSET, schema=_schema("timesheet_clockify_entries", "Read normalized Clockify time entries for an ISO-8601 interval.", {"start": {"type": "string"}, "end": {"type": "string"}}, ["start", "end"]), handler=handle_clockify_entries)
    ctx.register_tool(name="timesheet_sync_probe", toolset=TOOLSET, schema=_schema("timesheet_sync_probe", "Cheap first sync step: compare Clockify with immutable source snapshots for the requested week. If has_changes is false, stop. If requires_rebaseline is true, call timesheet_source_rebaseline rather than treating legacy plan fields as changes.", {"start": {"type": "string"}, "end": {"type": "string"}}, ["start", "end"]), handler=handle_sync_probe)
    ctx.register_tool(name="timesheet_source_rebaseline", toolset=TOOLSET, schema=_schema("timesheet_source_rebaseline", "Refresh immutable Clockify source snapshots for the requested week's plan while preserving all human review and booking values. Use only when sync_probe reports requires_rebaseline.", {"start": {"type": "string"}, "end": {"type": "string"}}, ["start", "end"]), handler=handle_source_rebaseline)
    ctx.register_tool(name="timesheet_simplicate_context", toolset=TOOLSET, schema=_schema("timesheet_simplicate_context", "Read Simplicate masterdata, planned assignments and booking candidates.", _date_range_properties(), ["start_date", "end_date"]), handler=handle_simplicate_context)
    ctx.register_tool(name="timesheet_simplicate_assignments", toolset=TOOLSET, schema=_schema("timesheet_simplicate_assignments", "Read actual planned Simplicate assignments.", _date_range_properties(), ["start_date", "end_date"]), handler=handle_simplicate_assignments)
    ctx.register_tool(name="timesheet_simplicate_booking_assignments", toolset=TOOLSET, schema=_schema("timesheet_simplicate_booking_assignments", "Read credible assignment booking targets.", _date_range_properties(), ["start_date", "end_date"]), handler=handle_simplicate_booking_assignments)
    ctx.register_tool(name="timesheet_simplicate_available_assignments", toolset=TOOLSET, schema=_schema("timesheet_simplicate_available_assignments", "DEPRECATED alias for booking assignments.", _date_range_properties(), ["start_date", "end_date"]), handler=handle_simplicate_available_assignments)
    ctx.register_tool(name="timesheet_simplicate_debug_assignments", toolset=TOOLSET, schema=_schema("timesheet_simplicate_debug_assignments", "Diagnostic assignment projection.", {"limit": {"type": "integer", "minimum": 1, "maximum": 10}}, []), handler=handle_simplicate_debug_assignments)
    ctx.register_tool(name="timesheet_simplicate_booked_hours", toolset=TOOLSET, schema=_schema("timesheet_simplicate_booked_hours", "Read already booked Simplicate hours.", _date_range_properties(), ["start_date", "end_date"]), handler=handle_simplicate_booked_hours)
    ctx.register_tool(name="timesheet_plan_create", toolset=TOOLSET, schema=_schema("timesheet_plan_create", "Create a brand-new plan only when no open week plan exists.", {"plan": {"type": "object"}}, ["plan"]), handler=handle_plan_create)
    ctx.register_tool(name="timesheet_plan_sync", toolset=TOOLSET, schema=_schema("timesheet_plan_sync", "Synchronize an open week plan, preserve human review state, refresh source snapshots and return deterministic summary.", {"plan": {"type": "object"}}, ["plan"]), handler=handle_plan_sync)
    ctx.register_tool(name="timesheet_plan_active", toolset=TOOLSET, schema=_schema("timesheet_plan_active", "Read the active booking plan.", {}, []), handler=handle_plan_active)
    ctx.register_tool(name="timesheet_plan_summary", toolset=TOOLSET, schema=_schema("timesheet_plan_summary", "Read deterministic totals and counts for the active plan. Present these values; do not recalculate them.", {}, []), handler=handle_plan_summary)
    ctx.register_tool(name="timesheet_plan_list", toolset=TOOLSET, schema=_schema("timesheet_plan_list", "List recent Timesheet Clerk plans.", {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}, []), handler=handle_plan_list)
    ctx.register_tool(name="timesheet_learning_context", toolset=TOOLSET, schema=_schema("timesheet_learning_context", "Read feedback and learned rules only when source changes require planning.", {"feedback_limit": {"type": "integer", "minimum": 1, "maximum": 1000}}, []), handler=handle_learning_context)
    ctx.register_tool(name="timesheet_update", toolset=TOOLSET, schema=_schema("timesheet_update", "Fast-forward update the fixed Timesheet Clerk Git checkout, run compile/tests, preserve shared skill/profile wiring and schedule a Hermes-native supervised gateway restart so new plugin code/tools load without Docker or frontend intervention.", {}, []), handler=handle_update)
