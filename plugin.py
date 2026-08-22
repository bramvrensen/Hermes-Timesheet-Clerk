"""HERMES plugin implementation for Timesheet Clerk."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .timesheet_clerk.clockify import ClockifyClient
from .timesheet_clerk.config import ClockifyConfig, ConfigError, SimplicateConfig
from .timesheet_clerk.http import IntegrationError
from .timesheet_clerk.runtime import ensure_runtime_skill, read_config
from .timesheet_clerk.simplicate import SimplicateClient
from .timesheet_clerk.storage import PlanRepository
from .timesheet_clerk.sync import plan_summary, source_delta
from .timesheet_clerk.working import sync_week_plan

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
    try: return _ok(call())
    except Exception as exc: return _error(exc)


def handle_clockify_entries(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs; return _safe(lambda: ClockifyClient(ClockifyConfig.from_env()).get_time_entries(params["start"], params["end"]))


def handle_sync_probe(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    def run() -> dict[str, Any]:
        repo = PlanRepository()
        try: plan = repo.get_active()
        except Exception: plan = None
        entries = ClockifyClient(ClockifyConfig.from_env()).get_time_entries(params["start"], params["end"])
        delta = source_delta(plan, entries)
        return {
            "plan_exists": plan is not None,
            "has_changes": delta["has_changes"],
            "source_delta": delta,
            "summary": plan_summary(plan, source_delta=delta) if plan else None,
        }
    return _safe(run)


def handle_simplicate_context(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs; return _safe(lambda: SimplicateClient(SimplicateConfig.from_env()).get_context(params["start_date"], params["end_date"]))


def handle_simplicate_assignments(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs; return _safe(lambda: SimplicateClient(SimplicateConfig.from_env()).get_planned_assignments(params["start_date"], params["end_date"]))


def handle_simplicate_booking_assignments(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs; return _safe(lambda: SimplicateClient(SimplicateConfig.from_env()).get_booking_assignments(params["start_date"], params["end_date"]))


def handle_simplicate_available_assignments(params: dict[str, Any], **kwargs: Any) -> str:
    return handle_simplicate_booking_assignments(params, **kwargs)


def handle_simplicate_debug_assignments(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs; return _safe(lambda: SimplicateClient(SimplicateConfig.from_env()).debug_assignment_shapes(int(params.get("limit", 3))))


def handle_simplicate_booked_hours(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs; return _safe(lambda: SimplicateClient(SimplicateConfig.from_env()).get_booked_hours(params["start_date"], params["end_date"]))


def handle_plan_create(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs; return _safe(lambda: PlanRepository().create(params["plan"], make_active=True))


def handle_plan_sync(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    def run() -> dict[str, Any]:
        saved = sync_week_plan(PlanRepository(), params["plan"])
        return {"plan": saved, "summary": plan_summary(saved)}
    return _safe(run)


def handle_plan_active(params: dict[str, Any], **kwargs: Any) -> str:
    del params, kwargs; return _safe(lambda: PlanRepository().get_active())


def handle_plan_summary(params: dict[str, Any], **kwargs: Any) -> str:
    del params, kwargs; return _safe(lambda: plan_summary(PlanRepository().get_active()))


def handle_plan_list(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs; return _safe(lambda: PlanRepository().list_plans(limit=int(params.get("limit", 20))))


def handle_config_get(params: dict[str, Any], **kwargs: Any) -> str:
    del params, kwargs; return _safe(read_config)


def handle_learning_context(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs; repo = PlanRepository()
    return _safe(lambda: {"feedback_events": repo.feedback(limit=int(params.get("feedback_limit", 200))), "rules": repo.read_rules()})


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": required}}


def _date_range_properties() -> dict[str, Any]:
    return {"start_date": {"type": "string", "description": "YYYY-MM-DD"}, "end_date": {"type": "string", "description": "YYYY-MM-DD"}}


def register(ctx) -> None:
    runtime_skill = ensure_runtime_skill(DEFAULT_TIMESHEET_SKILL)
    ctx.register_skill("timesheet-clerk", runtime_skill, "Prepare, reconcile and review weekly timesheet booking plans from Clockify and Simplicate.")
    ctx.register_tool(name="timesheet_config_get", toolset=TOOLSET, schema=_schema("timesheet_config_get", "Read active Timesheet Clerk runtime policy.", {}, []), handler=handle_config_get)
    ctx.register_tool(name="timesheet_clockify_entries", toolset=TOOLSET, schema=_schema("timesheet_clockify_entries", "Read normalized Clockify time entries for an ISO-8601 interval.", {"start": {"type": "string"}, "end": {"type": "string"}}, ["start", "end"]), handler=handle_clockify_entries)
    ctx.register_tool(name="timesheet_sync_probe", toolset=TOOLSET, schema=_schema("timesheet_sync_probe", "Cheap first sync step: compare current Clockify source state with the active plan. If has_changes is false, stop without loading Simplicate or learning context. Returns only source deltas plus deterministic plan summary.", {"start": {"type": "string"}, "end": {"type": "string"}}, ["start", "end"]), handler=handle_sync_probe)
    ctx.register_tool(name="timesheet_simplicate_context", toolset=TOOLSET, schema=_schema("timesheet_simplicate_context", "Read Simplicate masterdata, planned assignments and booking candidates.", _date_range_properties(), ["start_date", "end_date"]), handler=handle_simplicate_context)
    ctx.register_tool(name="timesheet_simplicate_assignments", toolset=TOOLSET, schema=_schema("timesheet_simplicate_assignments", "Read actual planned Simplicate assignments.", _date_range_properties(), ["start_date", "end_date"]), handler=handle_simplicate_assignments)
    ctx.register_tool(name="timesheet_simplicate_booking_assignments", toolset=TOOLSET, schema=_schema("timesheet_simplicate_booking_assignments", "Read credible assignment booking targets.", _date_range_properties(), ["start_date", "end_date"]), handler=handle_simplicate_booking_assignments)
    ctx.register_tool(name="timesheet_simplicate_available_assignments", toolset=TOOLSET, schema=_schema("timesheet_simplicate_available_assignments", "DEPRECATED alias for booking assignments.", _date_range_properties(), ["start_date", "end_date"]), handler=handle_simplicate_available_assignments)
    ctx.register_tool(name="timesheet_simplicate_debug_assignments", toolset=TOOLSET, schema=_schema("timesheet_simplicate_debug_assignments", "Diagnostic assignment projection.", {"limit": {"type": "integer", "minimum": 1, "maximum": 10}}, []), handler=handle_simplicate_debug_assignments)
    ctx.register_tool(name="timesheet_simplicate_booked_hours", toolset=TOOLSET, schema=_schema("timesheet_simplicate_booked_hours", "Read already booked Simplicate hours.", _date_range_properties(), ["start_date", "end_date"]), handler=handle_simplicate_booked_hours)
    ctx.register_tool(name="timesheet_plan_create", toolset=TOOLSET, schema=_schema("timesheet_plan_create", "Create a brand-new plan only when no open week plan exists.", {"plan": {"type": "object"}}, ["plan"]), handler=handle_plan_create)
    ctx.register_tool(name="timesheet_plan_sync", toolset=TOOLSET, schema=_schema("timesheet_plan_sync", "Synchronize an open week plan and return the saved plan plus deterministic summary.", {"plan": {"type": "object"}}, ["plan"]), handler=handle_plan_sync)
    ctx.register_tool(name="timesheet_plan_active", toolset=TOOLSET, schema=_schema("timesheet_plan_active", "Read the active booking plan.", {}, []), handler=handle_plan_active)
    ctx.register_tool(name="timesheet_plan_summary", toolset=TOOLSET, schema=_schema("timesheet_plan_summary", "Read deterministic totals and counts for the active plan. Present these values; do not recalculate them.", {}, []), handler=handle_plan_summary)
    ctx.register_tool(name="timesheet_plan_list", toolset=TOOLSET, schema=_schema("timesheet_plan_list", "List recent Timesheet Clerk plans.", {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}, []), handler=handle_plan_list)
    ctx.register_tool(name="timesheet_learning_context", toolset=TOOLSET, schema=_schema("timesheet_learning_context", "Read feedback and learned rules only when source changes require planning.", {"feedback_limit": {"type": "integer", "minimum": 1, "maximum": 1000}}, []), handler=handle_learning_context)
