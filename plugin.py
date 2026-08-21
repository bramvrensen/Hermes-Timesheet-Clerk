"""HERMES plugin implementation for Timesheet Clerk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .timesheet_clerk.clockify import ClockifyClient
from .timesheet_clerk.config import ClockifyConfig, ConfigError, SimplicateConfig
from .timesheet_clerk.http import IntegrationError
from .timesheet_clerk.simplicate import SimplicateClient
from .timesheet_clerk.storage import PlanRepository

PLUGIN_ROOT = Path(__file__).resolve().parent
TIMESHEET_SKILL = PLUGIN_ROOT / "skills" / "productivity" / "timesheet-clerk" / "SKILL.md"
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


def handle_clockify_entries(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _safe(lambda: ClockifyClient(ClockifyConfig.from_env()).get_time_entries(params["start"], params["end"]))


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
    limit = int(params.get("limit", 3))
    return _safe(lambda: SimplicateClient(SimplicateConfig.from_env()).debug_assignment_shapes(limit))


def handle_simplicate_booked_hours(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _safe(lambda: SimplicateClient(SimplicateConfig.from_env()).get_booked_hours(params["start_date"], params["end_date"]))


def handle_plan_create(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _safe(lambda: PlanRepository().create(params["plan"], make_active=True))


def handle_plan_active(params: dict[str, Any], **kwargs: Any) -> str:
    del params, kwargs
    return _safe(lambda: PlanRepository().get_active())


def handle_plan_list(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _safe(lambda: PlanRepository().list_plans(limit=int(params.get("limit", 20))))


def handle_learning_context(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    repo = PlanRepository()
    return _safe(lambda: {
        "feedback_events": repo.feedback(limit=int(params.get("feedback_limit", 200))),
        "rules": repo.read_rules(),
    })


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": required}}


def _date_range_properties() -> dict[str, Any]:
    return {
        "start_date": {"type": "string", "description": "YYYY-MM-DD"},
        "end_date": {"type": "string", "description": "YYYY-MM-DD"},
    }


def register(ctx) -> None:
    ctx.register_skill(
        "timesheet-clerk",
        TIMESHEET_SKILL,
        "Prepare, reconcile and review weekly timesheet booking plans from Clockify and Simplicate.",
    )

    ctx.register_tool(
        name="timesheet_clockify_entries", toolset=TOOLSET,
        schema=_schema("timesheet_clockify_entries", "Read normalized Clockify time entries for a requested interval.", {
            "start": {"type": "string", "description": "ISO-8601 interval start"},
            "end": {"type": "string", "description": "ISO-8601 interval end"},
        }, ["start", "end"]), handler=handle_clockify_entries,
    )
    ctx.register_tool(
        name="timesheet_simplicate_context", toolset=TOOLSET,
        schema=_schema("timesheet_simplicate_context", "Read Simplicate masterdata, planned assignments and validated booking assignment candidates for a period.", _date_range_properties(), ["start_date", "end_date"]),
        handler=handle_simplicate_context,
    )
    ctx.register_tool(
        name="timesheet_simplicate_assignments", toolset=TOOLSET,
        schema=_schema("timesheet_simplicate_assignments", "Read actual planned Simplicate assignments for the employee and requested period.", _date_range_properties(), ["start_date", "end_date"]),
        handler=handle_simplicate_assignments,
    )
    ctx.register_tool(
        name="timesheet_simplicate_booking_assignments", toolset=TOOLSET,
        schema=_schema("timesheet_simplicate_booking_assignments", "Read credible Simplicate assignment booking targets for the employee. Undated records are candidates, not planning evidence.", _date_range_properties(), ["start_date", "end_date"]),
        handler=handle_simplicate_booking_assignments,
    )
    ctx.register_tool(
        name="timesheet_simplicate_available_assignments", toolset=TOOLSET,
        schema=_schema("timesheet_simplicate_available_assignments", "DEPRECATED compatibility alias for timesheet_simplicate_booking_assignments.", _date_range_properties(), ["start_date", "end_date"]),
        handler=handle_simplicate_available_assignments,
    )
    ctx.register_tool(
        name="timesheet_simplicate_debug_assignments", toolset=TOOLSET,
        schema=_schema("timesheet_simplicate_debug_assignments", "TEMPORARY DIAGNOSTIC: return a safe projection of a few raw Simplicate assignment records.", {
            "limit": {"type": "integer", "minimum": 1, "maximum": 10, "description": "Number of records, default 3"}
        }, []), handler=handle_simplicate_debug_assignments,
    )
    ctx.register_tool(
        name="timesheet_simplicate_booked_hours", toolset=TOOLSET,
        schema=_schema("timesheet_simplicate_booked_hours", "Read already booked Simplicate hours for reconciliation.", _date_range_properties(), ["start_date", "end_date"]),
        handler=handle_simplicate_booked_hours,
    )
    ctx.register_tool(
        name="timesheet_plan_create", toolset=TOOLSET,
        schema=_schema(
            "timesheet_plan_create",
            "Validate and atomically persist a new revision-1 booking plan as the active plan. The caller supplies all mapping and autonomy decisions; this tool does not infer them.",
            {"plan": {"type": "object", "description": "Complete schema_version=1 booking plan"}},
            ["plan"],
        ), handler=handle_plan_create,
    )
    ctx.register_tool(
        name="timesheet_plan_active", toolset=TOOLSET,
        schema=_schema("timesheet_plan_active", "Read the currently active booking plan and exact revision.", {}, []),
        handler=handle_plan_active,
    )
    ctx.register_tool(
        name="timesheet_plan_list", toolset=TOOLSET,
        schema=_schema("timesheet_plan_list", "List recent Timesheet Clerk plans and lifecycle state.", {
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Maximum plans to return"}
        }, []), handler=handle_plan_list,
    )
    ctx.register_tool(
        name="timesheet_learning_context", toolset=TOOLSET,
        schema=_schema("timesheet_learning_context", "Read append-only review feedback plus current agent-derived rules. Treat them as evidence according to the Timesheet Clerk skill.", {
            "feedback_limit": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "Most recent feedback events to return"}
        }, []), handler=handle_learning_context,
    )
