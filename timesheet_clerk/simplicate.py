"""Simplicate REST client.

This module owns Simplicate transport quirks. Callers receive normalized domain
objects and never need to know API ID prefixes or query syntax.
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
        return request_json(
            "GET",
            f"{self.config.base_url}/{path.lstrip('/')}",
            headers=self.headers,
            params=params,
        )

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
        return self._paged("projects/project")

    def get_services(self) -> list[dict[str, Any]]:
        return self._paged("projects/service")

    def get_hour_types(self) -> list[dict[str, Any]]:
        return self._paged("hours/hourstype")

    def get_assignments(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        raw = self._paged("projects/assignment")
        employee = _plain_id(self.config.employee_id)
        result: list[dict[str, Any]] = []
        for assignment in raw:
            employee_id = _nested_id(assignment, "employee") or _plain_id(assignment.get("employee_id"))
            if employee_id and employee_id != employee:
                continue
            if assignment.get("blocked") is True:
                continue
            start = assignment.get("start_date") or assignment.get("start")
            end = assignment.get("end_date") or assignment.get("end")
            if start and start > end_date:
                continue
            if end and end < start_date:
                continue
            result.append(_normalize_assignment(assignment))
        return result

    def get_booked_hours(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        return self._paged(
            "hours/hours",
            {
                "q[employee.id]": _plain_id(self.config.employee_id),
                "q[start_date][ge]": start_date,
                "q[start_date][le]": end_date,
            },
        )

    def get_context(self, start_date: str, end_date: str) -> dict[str, Any]:
        return {
            "projects": self.get_projects(),
            "services": self.get_services(),
            "hour_types": self.get_hour_types(),
            "assignments": self.get_assignments(start_date, end_date),
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


def _nested_id(item: dict[str, Any], key: str) -> str | None:
    value = item.get(key)
    return _plain_id(value)


def _normalize_assignment(item: dict[str, Any]) -> dict[str, Any]:
    project = item.get("project") or {}
    service = item.get("projectservice") or item.get("service") or {}
    hour_type = item.get("type") or item.get("hourstype") or {}
    organization = item.get("organization") or item.get("customer") or {}
    return {
        "id": _plain_id(item.get("id")),
        "name": item.get("name") or item.get("title") or service.get("name"),
        "customer": {"id": _plain_id(organization), "name": organization.get("name")} if isinstance(organization, dict) else None,
        "project": {"id": _plain_id(project), "name": project.get("name")} if isinstance(project, dict) else None,
        "task": {"id": _plain_id(service), "name": service.get("name")} if isinstance(service, dict) else None,
        "hour_type": {"id": _plain_id(hour_type), "name": hour_type.get("name")} if isinstance(hour_type, dict) else None,
        "start_date": item.get("start_date") or item.get("start"),
        "end_date": item.get("end_date") or item.get("end"),
        "planned_hours": item.get("hours") or item.get("planned_hours"),
    }
