"""Validate plan mappings against the Simplicate snapshot used for generation."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def plain_id(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("id")
    text = str(value or "")
    return text.split(":", 1)[1] if ":" in text else text


def _snapshot(context: dict[str, Any]) -> dict[str, Any]:
    projects: dict[str, dict[str, Any]] = {}
    services: dict[str, dict[str, Any]] = {}
    service_hour_types: dict[str, dict[str, dict[str, Any]]] = {}
    assignments: dict[str, dict[str, Any]] = {}

    for row in context.get("projects") or []:
        if isinstance(row, dict) and plain_id(row.get("id")):
            projects[plain_id(row.get("id"))] = row

    for row in context.get("services") or []:
        if not isinstance(row, dict):
            continue
        sid = plain_id(row.get("id"))
        if not sid:
            continue
        services[sid] = row
        scoped: dict[str, dict[str, Any]] = {}
        for relation in row.get("hour_types") or []:
            if not isinstance(relation, dict):
                continue
            hourstype = relation.get("hourstype") or relation.get("hour_type") or {}
            hid = plain_id(hourstype.get("id") if isinstance(hourstype, dict) else None)
            if not hid:
                continue
            scoped[hid] = hourstype
        service_hour_types[sid] = scoped

    for key in ("planned_assignments", "booking_assignments", "assignments", "available_assignments"):
        for row in context.get(key) or []:
            if isinstance(row, dict) and plain_id(row.get("id")):
                assignments[plain_id(row.get("id"))] = row

    return {
        "projects": projects,
        "services": services,
        "service_hour_types": service_hour_types,
        "assignments": assignments,
    }


def entry_mapping_invalid_reason(entry: dict[str, Any], context: dict[str, Any] | None) -> str | None:
    if not context or entry.get("ignored") or entry.get("review_state") == "skipped":
        return None
    snap = _snapshot(context)
    mode = str(entry.get("booking_mode") or "")
    if mode == "assignment":
        aid = plain_id(entry.get("assignment") or {})
        if not aid:
            return "Assignment mapping has no assignment ID."
        if aid not in snap["assignments"]:
            return f"Assignment {aid} is not present in the current Simplicate snapshot."
        return None
    if mode != "direct":
        return "Booking mode is not valid."
    mapping = entry.get("direct_mapping") or {}
    return _direct_invalid_reason(mapping, snap)


def normalize_decision_against_snapshot(decision: dict[str, Any], context: dict[str, Any] | None) -> tuple[dict[str, Any], str | None]:
    """Return a canonical decision or the reason it cannot be resolved in this snapshot."""
    result = deepcopy(decision)
    if not context or result.get("ignored"):
        return result, None
    snap = _snapshot(context)
    mode = str(result.get("booking_mode") or "")
    if mode == "assignment":
        aid = plain_id(result.get("assignment") or {})
        live = snap["assignments"].get(aid)
        if not live:
            return result, f"Assignment {aid or '<missing>'} is not present in the current Simplicate snapshot."
        result["assignment"] = deepcopy(live)
        return result, None
    if mode == "direct":
        mapping = result.get("direct_mapping") or {}
        reason = _direct_invalid_reason(mapping, snap)
        if reason:
            return result, reason
        pid, sid, hid = plain_id(mapping.get("project_id")), plain_id(mapping.get("service_id")), plain_id(mapping.get("hour_type_id"))
        project, service = snap["projects"][pid], snap["services"][sid]
        hourstype = snap["service_hour_types"][sid][hid]
        result["direct_mapping"] = {
            **deepcopy(mapping),
            "project_id": pid,
            "project_name": project.get("name") or mapping.get("project_name"),
            "service_id": sid,
            "service_name": service.get("name") or mapping.get("service_name"),
            "hour_type_id": hid,
            "hour_type_name": hourstype.get("name") or hourstype.get("label") or mapping.get("hour_type_name"),
        }
        return result, None
    return result, "Booking mode is not valid."


def downgrade_invalid_decision(decision: dict[str, Any], reason: str) -> dict[str, Any]:
    result = deepcopy(decision)
    result["tier"] = "ASK"
    result["booking_mode"] = "direct"
    result["assignment"] = {}
    result["direct_mapping"] = {}
    result["ignored"] = False
    result["billable"] = True
    result["why_not_auto"] = reason
    return result


def _direct_invalid_reason(mapping: dict[str, Any], snap: dict[str, Any]) -> str | None:
    pid, sid, hid = plain_id(mapping.get("project_id")), plain_id(mapping.get("service_id")), plain_id(mapping.get("hour_type_id"))
    if not pid or pid not in snap["projects"]:
        return f"Project {pid or '<missing>'} is not present in the current Simplicate snapshot."
    service = snap["services"].get(sid)
    if not sid or not service:
        return f"Service {sid or '<missing>'} is not present in the current Simplicate snapshot."
    service_project = plain_id((service.get("project") or {}).get("id") if isinstance(service.get("project"), dict) else service.get("project_id"))
    if service_project and service_project != pid:
        return f"Service {sid} does not belong to project {pid}."
    scoped = snap["service_hour_types"].get(sid) or {}
    if not hid or hid not in scoped:
        return f"Hour type {hid or '<missing>'} is not valid for service {sid} in the current Simplicate snapshot."
    return None
