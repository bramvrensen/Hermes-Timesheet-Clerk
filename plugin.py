"""HERMES plugin entry point for Timesheet Clerk."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from timesheet_clerk.clockify import ClockifyClient
from timesheet_clerk.config import ClockifyConfig, ConfigError, SimplicateConfig
from timesheet_clerk.http import IntegrationError
from timesheet_clerk.simplicate import SimplicateClient


PLUGIN_ROOT = Path(__file__).resolve().parent
TIMESHEET_SKILL = PLUGIN_ROOT / "skills" / "timesheet-clerk" / "SKILL.md"


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, IntegrationError):
        return exc.as_dict()
    if isinstance(exc, ConfigError):
        return {"ok": False, "error_type": "configuration_error", "message": str(exc), "retryable": False}
    return {"ok": False, "error_type": "unexpected_error", "message": str(exc), "retryable": False}


def clockify_time_entries(start: str, end: str) -> dict[str, Any]:
    """Get normalized Clockify entries for an ISO-8601 interval."""
    try:
        return _ok(ClockifyClient(ClockifyConfig.from_env()).get_time_entries(start, end))
    except Exception as exc:  # plugin boundary: always return structured JSON
        return _error(exc)


def simplicate_context(start_date: str, end_date: str) -> dict[str, Any]:
    """Get Simplicate projects, tasks, hour types and employee assignments."""
    try:
        return _ok(SimplicateClient(SimplicateConfig.from_env()).get_context(start_date, end_date))
    except Exception as exc:
        return _error(exc)


def simplicate_assignments(start_date: str, end_date: str) -> dict[str, Any]:
    """Get normalized employee assignments valid for a date interval."""
    try:
        return _ok(SimplicateClient(SimplicateConfig.from_env()).get_assignments(start_date, end_date))
    except Exception as exc:
        return _error(exc)


def simplicate_booked_hours(start_date: str, end_date: str) -> dict[str, Any]:
    """Get existing Simplicate hours for the configured employee."""
    try:
        return _ok(SimplicateClient(SimplicateConfig.from_env()).get_booked_hours(start_date, end_date))
    except Exception as exc:
        return _error(exc)


def register(ctx) -> None:
    """Register Timesheet Clerk skill and read-only tools with HERMES."""
    ctx.register_skill(
        "timesheet-clerk",
        TIMESHEET_SKILL,
        "Prepare, reconcile and review weekly timesheet booking plans from Clockify and Simplicate.",
    )

    ctx.register_tool(
        name="timesheet_clockify_entries",
        description="Read normalized Clockify time entries for a requested interval.",
        handler=clockify_time_entries,
        parameters={
            "type": "object",
            "properties": {
                "start": {"type": "string", "description": "ISO-8601 interval start"},
                "end": {"type": "string", "description": "ISO-8601 interval end"},
            },
            "required": ["start", "end"],
        },
    )
    ctx.register_tool(
        name="timesheet_simplicate_context",
        description="Read Simplicate projects, tasks, hour types and assignments for planning.",
        handler=simplicate_context,
        parameters={
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["start_date", "end_date"],
        },
    )
    ctx.register_tool(
        name="timesheet_simplicate_assignments",
        description="Read valid Simplicate assignments for the configured employee and period.",
        handler=simplicate_assignments,
        parameters={
            "type": "object",
            "properties": {
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
            },
            "required": ["start_date", "end_date"],
        },
    )
    ctx.register_tool(
        name="timesheet_simplicate_booked_hours",
        description="Read already booked Simplicate hours for reconciliation.",
        handler=simplicate_booked_hours,
        parameters={
            "type": "object",
            "properties": {
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
            },
            "required": ["start_date", "end_date"],
        },
    )
