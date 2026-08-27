"""Simplicate REST client.

This module owns Simplicate transport quirks. Callers receive normalized domain
objects and never need to know API ID prefixes or query syntax.

Where possible the transport behaviour mirrors the previously working
Antigravity implementation, especially around employee IDs, assignments and
booked-hours filtering. Assignment normalization below is based on the live
Simplicate tenant response validated on 2026-08-21 and the hours-write contract
validated during the 0.7.x booking rollout.
"""

from __future__ import annotations

from typing import Any

from .config import SimplicateConfig
from .http import request_json


class SimplicateClient:
    def __init__(self, config: SimplicateConfig):
        self.config = config

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authentication-Key": self.config.api_key,
            "Authentication-Secret": self.config.api_secret,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return request_json("GET", f"{self.config.base_url}/{path.lstrip('/')}", headers=self.headers, params=params)

    @staticmethod
    def _items(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("data", "items", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    def _paged(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        offset = 0
        limit = 100
        while True:
            query = dict(params or {})
            query.update({"limit": limit, "offset": offset})
            batch = self._items(self._get(path, query))
            result.extend(batch)
            if len(batch) < limit:
                return result
            offset += limit

    def get_projects(self) -> list[dict[str, Any]]:
        return [project for project in self._paged("projects/project") if not _project_is_closed(project)]

    def get_services(self) -> list[dict[str, Any]]:
        return self._paged("projects/service")

    def get_hour_types(self) -> list[dict[str, Any]]:
        return self._paged("hours/hourstype")

    def debug_assignment_shapes(self, limit: int = 3) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for assignment in self._employee_assignments(include_done=True)[: max(1, min(limit, 10))]:
            rows.append({
                "id": assignment.get("id"), "name": assignment.get("name") or assignment.get("title"),
                "start_date": assignment.get("start_date"), "end_date": assignment.get("end_date"),
                "hours": assignment.get("hours"), "hours_total": assignment.get("hours_total"),
                "is_planned": assignment.get("is_planned"), "status": assignment.get("status"),
                "employees": assignment.get("employees"), "project": assignment.get("project"),
                "projectservice": assignment.get("projectservice"), "projecthourstype": assignment.get("projecthourstype"),
                "hours_type": assignment.get("hours_type"), "raw_keys": sorted(assignment.keys()),
            })
        return rows

    def _employee_assignments(self, *, include_done: bool = False) -> list[dict[str, Any]]:
        employee = _plain_id(self.config.employee_id)
        relevant: list[dict[str, Any]] = []
        for assignment in self._paged("projects/assignment"):
            employees = assignment.get("employees") or []
            if not any(_plain_id(person.get("id")) == employee for person in employees if isinstance(person, dict)):
                continue
            status = assignment.get("status") or {}
            if status.get("is_blocked", False):
                continue
            if status.get("is_done", False) and not include_done:
                continue
            relevant.append(assignment)
        return relevant

    def get_planned_assignments(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        planned: list[dict[str, Any]] = []
        for assignment in self._employee_assignments():
            assignment_start = _date_part(assignment.get("start_date"))
            assignment_end = _date_part(assignment.get("end_date"))
            if not assignment.get("is_planned", False) or not assignment_start or not assignment_end:
                continue
            if assignment_start > end_date or assignment_end < start_date:
                continue
            normalized = _normalize_assignment(assignment)
            normalized["planning_status"] = "planned"
            planned.append(normalized)
        return planned

    def get_booking_assignments(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        active_projects = {_plain_id(project.get("id")) for project in self.get_projects()}
        candidates: list[dict[str, Any]] = []
        for assignment in self._employee_assignments():
            project = assignment.get("project") or {}
            service = assignment.get("projectservice") or {}
            project_id = _plain_id(project.get("id"))
            if not project_id or project_id not in active_projects:
                continue
            if not isinstance(service, dict) or not service.get("id") or service.get("use_in_resource_planner") is not True:
                continue
            assignment_start = _date_part(assignment.get("start_date"))
            assignment_end = _date_part(assignment.get("end_date"))
            if assignment_start and assignment_start > end_date:
                continue
            if assignment_end and assignment_end < start_date:
                continue
            normalized = _normalize_assignment(assignment)
            normalized["planning_status"] = "planned" if assignment.get("is_planned", False) else "booking_candidate"
            candidates.append(normalized)
        return candidates

    def get_available_assignments(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        return self.get_booking_assignments(start_date, end_date)

    def get_assignments(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        return self.get_planned_assignments(start_date, end_date)

    def get_booked_hours(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        return self._paged("hours/hours", {
            "q[employee.id]": _employee_id(self.config.employee_id),
            "q[start_date][ge]": f"{start_date} 00:00:00",
            "q[start_date][le]": f"{end_date} 23:59:59",
        })

    def get_context(self, start_date: str, end_date: str) -> dict[str, Any]:
        planned = self.get_planned_assignments(start_date, end_date)
        booking = self.get_booking_assignments(start_date, end_date)
        return {
            "projects": self.get_projects(), "services": self.get_services(), "hour_types": self.get_hour_types(),
            "planned_assignments": planned, "booking_assignments": booking,
            "available_assignments": booking, "assignments": planned,
        }


def _plain_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("id")
    if value is None:
        return None
    text = str(value)
    return text.split(":", 1)[1] if ":" in text else text


def _employee_id(value: Any) -> str:
    return f"employee:{_plain_id(value) or ''}"


def _date_part(value: Any) -> str:
    return str(value or "")[:10]


def _project_is_closed(project: dict[str, Any]) -> bool:
    status = project.get("project_status") or project.get("status") or {}
    return status.get("label") == "tab_pclosed" or status.get("is_closed") is True


def _normalize_assignment(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a live assignment without confusing relation IDs with hour types.

    `projecthourstype.id` identifies the project/hour-type relation. The actual
    hours-write target is `projecthourstype.hourstype.id`.
    """
    project = item.get("project") or {}
    organization = project.get("organization") or {}
    service = item.get("projectservice") or {}
    projecthourstype = item.get("projecthourstype") or {}
    nested_hourstype = projecthourstype.get("hourstype") if isinstance(projecthourstype, dict) else None
    hour_type = nested_hourstype or item.get("hours_type") or item.get("hour_type") or {}
    status = item.get("status") or {}

    return {
        "id": _plain_id(item.get("id")),
        "name": item.get("name") or item.get("title") or service.get("name"),
        "customer": {"id": _plain_id(organization.get("id")), "name": organization.get("name")} if isinstance(organization, dict) and organization else None,
        "project": {"id": _plain_id(project.get("id")), "name": project.get("name"), "number": project.get("project_number")} if isinstance(project, dict) and project else None,
        "task": {"id": _plain_id(service.get("id")), "name": service.get("name"), "use_in_resource_planner": service.get("use_in_resource_planner")} if isinstance(service, dict) and service else None,
        "hour_type": {"id": _plain_id(hour_type.get("id")), "name": hour_type.get("name") or hour_type.get("label")} if isinstance(hour_type, dict) and hour_type else None,
        "projecthourstype_id": _plain_id(projecthourstype.get("id")) if isinstance(projecthourstype, dict) else None,
        "start_date": item.get("start_date"), "end_date": item.get("end_date"),
        "assignment_hours": item.get("hours"), "assignment_hours_total": item.get("hours_total"),
        "is_planned": bool(item.get("is_planned", False)),
        "status": {"id": _plain_id(status.get("id")), "name": status.get("name"), "is_done": bool(status.get("is_done", False)), "is_blocked": bool(status.get("is_blocked", False))},
        "display_label": _assignment_display_label(organization, project, item),
    }


def _assignment_display_label(organization: dict[str, Any], project: dict[str, Any], assignment: dict[str, Any]) -> str:
    parts = [organization.get("name") if isinstance(organization, dict) else None, project.get("name") if isinstance(project, dict) else None, assignment.get("name") or assignment.get("title")]
    return " · ".join(str(part) for part in parts if part)
