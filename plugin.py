"""HERMES plugin implementation for Timesheet Clerk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from timesheet_clerk.clockify import ClockifyClient
from timesheet_clerk.config import ClockifyConfig, ConfigError, SimplicateConfig
from timesheet_clerk.http import IntegrationError
from timesheet_clerk.simplicate import SimplicateClient


PLUGIN_ROOT = Path(__file__).resolve().parent
TIMESHEET_SKILL = PLUGIN_ROOT / "skills" / "timesheet-clerk" / "SKILL.md"
TOOLSET = "timesheet_clerk"


def _ok(data: Any) -> str:
    return json.dumps({"success": True, "data": data}, ensure_ascii=False, default=str)


def _error(exc: Exception) -> str:
    if isinstance(exc, IntegrationError):
        payload = exc.as_dict()
        payload["success"] = False
        return json.dumps(payload, ensure_ascii=False, default=str)
    if isinstance(exc, ConfigError):
        return json.dumps({
            "success": False,
            "error_type": "configuration_error",
            "message": str(exc),
            "retryable": False,
        })
    return json.dumps({
        "success": False,
        "error_type": "unexpected_error",
        "message": str(exc),
        "retryable": False,
    })


def _safe(call: Callable[[], Any]) -> str:
    try:
        return _ok(call())
    except Exception as exc:
        return _error(exc)


def handle_clockify_entries(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _safe(lambda: ClockifyClient(ClockifyConfig.from_env()).get_time_entries(
        params["start"], params["end"]
    ))


def handle_simplicate_context(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _safe(lambda: SimplicateClient(SimplicateConfig.from_env()).get_context(
        params["start_date"], params["end_date"]
    ))


def handle_simplicate_assignments(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _safe(lambda: SimplicateClient(SimplicateConfig.from_env()).get_assignments(
        params["start_date"], params["end_date"]
    ))


def handle_simplicate_booked_hours(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _safe(lambda: SimplicateClient(SimplicateConfig.from_env()).get_booked_hours(
        params["start_date"], params["end_date"]
    ))


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


def register(ctx) -> None:
    """Register the Timesheet Clerk skill and read-only planning tools."""
    ctx.register_skill(
        "timesheet-clerk",
        TIMESHEET_SKILL,
        "Prepare, reconcile and review weekly timesheet booking plans from Clockify and Simplicate.",
    )

    ctx.register_tool(
        name="timesheet_clockify_entries",
        toolset=TOOLSET,
        schema=_schema(
            "timesheet_clockify_entries",
            "Read normalized Clockify time entries for a requested interval.",
            {
                "start": {"type": "string", "description": "ISO-8601 interval start"},
                "end": {"type": "string", "description": "ISO-8601 interval end"},
            },
            ["start", "end"],
        ),
        handler=handle_clockify_entries,
    )

    ctx.register_tool(
        name="timesheet_simplicate_context",
        toolset=TOOLSET,
        schema=_schema(
            "timesheet_simplicate_context",
            "Read Simplicate projects, tasks, hour types and assignments for planning.",
            {
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            ["start_date", "end_date"],
        ),
        handler=handle_simplicate_context,
    )

    ctx.register_tool(
        name="timesheet_simplicate_assignments",
        toolset=TOOLSET,
        schema=_schema(
            "timesheet_simplicate_assignments",
            "Read valid Simplicate assignments for the configured employee and period.",
            {
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            ["start_date", "end_date"],
        ),
        handler=handle_simplicate_assignments,
    )

    ctx.register_tool(
        name="timesheet_simplicate_booked_hours",
        toolset=TOOLSET,
        schema=_schema(
            "timesheet_simplicate_booked_hours",
            "Read already booked Simplicate hours for reconciliation.",
            {
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            ["start_date", "end_date"],
        ),
        handler=handle_simplicate_booked_hours,
    )
