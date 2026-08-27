"""UI-facing review context built from the shared Simplicate integration layer."""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .config import SimplicateConfig
from .runtime import read_config
from .simplicate import SimplicateClient

_REQUIRED = ("SIMPLICATE_BASE_URL", "SIMPLICATE_API_KEY", "SIMPLICATE_API_SECRET", "SIMPLICATE_EMPLOYEE_ID")
_CACHE_TTL_SECONDS = 1800


def _load_planner_profile_env() -> None:
    if all(str(os.environ.get(key) or "").strip() for key in _REQUIRED):
        return
    profile = str(read_config().get("planner_profile") or "atlas")
    profile_env = Path(os.environ.get("HERMES_PROFILE_ENV") or f"/home/hermes/.hermes/profiles/{profile}/.env")
    if not profile_env.is_file():
        return
    for raw in profile_env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in _REQUIRED or os.environ.get(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def _cache_path(start_date: str, end_date: str) -> Path:
    root = Path(os.environ.get("TIMESHEET_CLERK_STATE_DIR") or Path.home() / ".hermes" / "timesheet-clerk")
    return root / "cache" / f"review-context-v077-{start_date}-{end_date}.json"


def _read_cache(start_date: str, end_date: str) -> dict[str, list[dict[str, Any]]] | None:
    path = _cache_path(start_date, end_date)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(payload.get("fetched_at") or 0) > _CACHE_TTL_SECONDS:
            return None
        context = payload.get("context")
        return context if isinstance(context, dict) else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _write_cache(start_date: str, end_date: str, context: dict[str, list[dict[str, Any]]]) -> None:
    path = _cache_path(start_date, end_date)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps({"fetched_at": time.time(), "context": context}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def load_review_context(start_date: str, end_date: str) -> dict[str, list[dict[str, Any]]]:
    cached = _read_cache(start_date, end_date)
    if cached is not None:
        return cached

    _load_planner_profile_env()
    config = SimplicateConfig.from_env()

    def call(method: str, *args: Any) -> Any:
        client = SimplicateClient(config)
        return getattr(client, method)(*args)

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="timesheet-ui") as pool:
        projects_future = pool.submit(call, "get_projects")
        services_future = pool.submit(call, "get_services")
        hour_types_future = pool.submit(call, "get_hour_types")
        assignments_future = pool.submit(call, "get_booking_assignments", start_date, end_date)
        raw_projects = projects_future.result()
        raw_services = services_future.result()
        raw_hour_types = hour_types_future.result()
        assignments = assignments_future.result()

    projects = [_normalize_project(row) for row in raw_projects if isinstance(row, dict)]
    projects = [row for row in projects if row.get("id")]
    services = [_normalize_service(row) for row in raw_services if isinstance(row, dict)]
    services = [row for row in services if row.get("id")]
    hour_types = [_normalize_hour_type(row) for row in raw_hour_types if isinstance(row, dict)]
    hour_types = [row for row in hour_types if row.get("id")]

    all_hour_types: list[dict[str, Any]] = []
    seen_global: set[str] = set()
    for row in hour_types:
        if row["id"] in seen_global:
            continue
        seen_global.add(row["id"])
        all_hour_types.append({"id": row["id"], "name": row.get("name") or row["id"], "source": "global"})

    hour_type_names = {row["id"]: row.get("name") for row in hour_types if row.get("id") and row.get("name")}
    customers: dict[str, dict[str, str]] = {}
    for project in projects:
        if project.get("customer_id"):
            customers.setdefault(project["customer_id"], {"id": project["customer_id"], "name": project.get("customer_name") or project["customer_id"]})

    scoped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for service in services:
        service_id = str(service.get("id") or "")
        for relation in service.get("hour_types") or []:
            if not isinstance(relation, dict):
                continue
            actual = relation.get("hourstype") or relation.get("hour_type") or relation.get("type") or {}
            hour_type_id = _plain_id(_nested_id(actual) or relation.get("hourstype_id") or relation.get("hourtype_id"))
            if not service_id or not hour_type_id:
                continue
            key = (service_id, hour_type_id)
            if key in seen:
                continue
            seen.add(key)
            scoped.append({
                "id": hour_type_id,
                "name": _nested_name(actual) or relation.get("name") or hour_type_names.get(hour_type_id) or hour_type_id,
                "service_id": service_id,
                "billable": relation.get("billable"),
                "source": "project_service",
            })

    for assignment in assignments:
        task = assignment.get("task") or assignment.get("projectservice") or {}
        hour_type = assignment.get("hour_type") or {}
        service_id = _plain_id(_nested_id(task))
        hour_type_id = _plain_id(_nested_id(hour_type))
        if not service_id or not hour_type_id:
            continue
        key = (service_id, hour_type_id)
        if key in seen:
            continue
        seen.add(key)
        scoped.append({"id": hour_type_id, "name": _nested_name(hour_type) or hour_type_names.get(hour_type_id) or hour_type_id, "service_id": service_id, "source": "assignment"})

    for hour_type in hour_types:
        service_id = hour_type.get("service_id")
        if service_id and (service_id, hour_type["id"]) not in seen:
            scoped.append(hour_type)
            seen.add((service_id, hour_type["id"]))

    context = {
        "customers": sorted(customers.values(), key=lambda row: _sort_name(row.get("name"))),
        "projects": sorted(projects, key=lambda row: (_sort_name(row.get("customer_name")), _sort_name(row.get("name")))),
        "services": sorted(services, key=lambda row: _sort_name(row.get("name"))),
        "hour_types": sorted(scoped, key=lambda row: (_sort_name(row.get("service_id")), _sort_name(row.get("name")))),
        "all_hour_types": sorted(all_hour_types, key=lambda row: _sort_name(row.get("name"))),
        "booking_assignments": sorted(assignments, key=lambda row: _sort_name(row.get("display_label") or row.get("name"))),
    }
    _write_cache(start_date, end_date, context)
    return context


def _normalize_project(row: dict[str, Any]) -> dict[str, Any]:
    organization = row.get("organization") or row.get("customer") or {}
    return {"id": _plain_id(row.get("id")), "name": row.get("name") or row.get("title") or row.get("project_name"), "number": row.get("project_number") or row.get("number"), "customer_id": _plain_id(_nested_id(organization) or row.get("organization_id") or row.get("customer_id")), "customer_name": _nested_name(organization) or row.get("organization_name") or row.get("customer_name")}


def _normalize_service(row: dict[str, Any]) -> dict[str, Any]:
    project = row.get("project") or {}
    raw_hour_types = row.get("hour_types") or []
    return {
        "id": _plain_id(row.get("id")),
        "name": row.get("name") or row.get("title") or row.get("service_name"),
        "project_id": _plain_id(_nested_id(project) or row.get("project_id")),
        "use_in_resource_planner": row.get("use_in_resource_planner"),
        "hour_types": [dict(item) for item in raw_hour_types if isinstance(item, dict)],
    }


def _normalize_hour_type(row: dict[str, Any]) -> dict[str, Any]:
    service = row.get("projectservice") or row.get("service") or {}
    return {"id": _plain_id(row.get("id")), "name": row.get("name") or row.get("title") or row.get("label"), "service_id": _plain_id(_nested_id(service) or row.get("projectservice_id") or row.get("service_id")), "source": "masterdata"}


def _nested_id(value: Any) -> Any:
    return value.get("id") if isinstance(value, dict) else value


def _nested_name(value: Any) -> str | None:
    return (value.get("name") or value.get("title") or value.get("label")) if isinstance(value, dict) else None


def _plain_id(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return text.split(":", 1)[1] if ":" in text else text


def _sort_name(value: Any) -> str:
    return str(value or "").casefold()
