"""UI-facing review context built from the shared Simplicate integration layer.

This module contains presentation normalization only. It does not decide mappings
or autonomy. Streamlit uses it to populate valid review dropdowns without
requiring the agent to duplicate masterdata into booking_plan.json.
"""

from __future__ import annotations

from typing import Any

from .config import SimplicateConfig
from .simplicate import SimplicateClient


def load_review_context(start_date: str, end_date: str) -> dict[str, list[dict[str, Any]]]:
    client = SimplicateClient(SimplicateConfig.from_env())
    projects_raw = client.get_projects()
    services_raw = client.get_services()
    hour_types_raw = client.get_hour_types()
    assignments = client.get_booking_assignments(start_date, end_date)

    projects = [_normalize_project(row) for row in projects_raw if isinstance(row, dict)]
    projects = [row for row in projects if row.get("id")]

    customers_by_id: dict[str, dict[str, Any]] = {}
    for project in projects:
        customer_id = project.get("customer_id")
        if customer_id:
            customers_by_id.setdefault(customer_id, {
                "id": customer_id,
                "name": project.get("customer_name") or customer_id,
            })

    services = [_normalize_service(row) for row in services_raw if isinstance(row, dict)]
    services = [row for row in services if row.get("id")]

    hour_types = [_normalize_hour_type(row) for row in hour_types_raw if isinstance(row, dict)]
    hour_types = [row for row in hour_types if row.get("id")]

    return {
        "customers": sorted(customers_by_id.values(), key=lambda row: _sort_name(row.get("name"))),
        "projects": sorted(projects, key=lambda row: (_sort_name(row.get("customer_name")), _sort_name(row.get("name")))),
        "services": sorted(services, key=lambda row: _sort_name(row.get("name"))),
        "hour_types": sorted(hour_types, key=lambda row: _sort_name(row.get("name"))),
        "booking_assignments": sorted(assignments, key=lambda row: _sort_name(row.get("display_label") or row.get("name"))),
    }


def _normalize_project(row: dict[str, Any]) -> dict[str, Any]:
    organization = row.get("organization") or row.get("customer") or {}
    return {
        "id": _plain_id(row.get("id")),
        "name": row.get("name") or row.get("title") or row.get("project_name"),
        "number": row.get("project_number") or row.get("number"),
        "customer_id": _plain_id(_nested_id(organization) or row.get("organization_id") or row.get("customer_id")),
        "customer_name": _nested_name(organization) or row.get("organization_name") or row.get("customer_name"),
    }


def _normalize_service(row: dict[str, Any]) -> dict[str, Any]:
    project = row.get("project") or {}
    return {
        "id": _plain_id(row.get("id")),
        "name": row.get("name") or row.get("title") or row.get("service_name"),
        "project_id": _plain_id(_nested_id(project) or row.get("project_id")),
        "use_in_resource_planner": row.get("use_in_resource_planner"),
    }


def _normalize_hour_type(row: dict[str, Any]) -> dict[str, Any]:
    service = row.get("projectservice") or row.get("service") or {}
    return {
        "id": _plain_id(row.get("id")),
        "name": row.get("name") or row.get("title") or row.get("label"),
        "service_id": _plain_id(_nested_id(service) or row.get("projectservice_id") or row.get("service_id")),
    }


def _nested_id(value: Any) -> Any:
    return value.get("id") if isinstance(value, dict) else value


def _nested_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("name") or value.get("title")
    return None


def _plain_id(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return text.split(":", 1)[1] if ":" in text else text


def _sort_name(value: Any) -> str:
    return str(value or "").casefold()
