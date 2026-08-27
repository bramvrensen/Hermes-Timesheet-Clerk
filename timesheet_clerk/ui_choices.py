"""Deterministic UI choice helpers for Simplicate review mappings."""
from __future__ import annotations

from typing import Any


def plain_id(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("id")
    text = str(value or "")
    return text.split(":", 1)[1] if ":" in text else text


def hour_types_for_service(context: dict[str, Any], service_id: Any) -> list[dict[str, Any]]:
    """Return only hour types explicitly valid for the selected task/service.

    There is deliberately no fallback to global hour types. An unscoped hour type
    may exist in Simplicate masterdata but that does not prove it is valid for the
    selected project service and would make a later booking unsafe.
    """
    selected = plain_id(service_id)
    if not selected:
        return []

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in context.get("hour_types") or []:
        if not isinstance(row, dict):
            continue
        if plain_id(row.get("service_id")) != selected:
            continue
        hour_type_id = plain_id(row)
        if not hour_type_id or hour_type_id in seen:
            continue
        seen.add(hour_type_id)
        rows.append(row)
    return rows


def editor_hour_type_choices(
    context: dict[str, Any],
    selected_service_id: Any,
    *,
    current_service_id: Any = None,
    current_hour_type_id: Any = None,
    current_hour_type_name: str | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Return safe editor choices and whether the current mapping was preserved.

    New choices are always strictly scoped to the selected service. A previously
    persisted hour type may be retained when the user is still on the same
    service but current Simplicate context cannot re-hydrate that relation. This
    prevents a transient context/cache/API problem from destructively clearing a
    complete reviewed mapping merely by opening the editor.
    """
    selected_service = plain_id(selected_service_id)
    rows = hour_types_for_service(context, selected_service)
    current_hour_type = plain_id(current_hour_type_id)
    same_service = bool(selected_service and selected_service == plain_id(current_service_id))

    if not current_hour_type or not same_service:
        return rows, False
    if any(plain_id(row) == current_hour_type for row in rows):
        return rows, False

    preserved = {
        "id": current_hour_type,
        "name": str(current_hour_type_name or current_hour_type),
        "service_id": selected_service,
        "source": "persisted_mapping",
        "scope_verified": False,
    }
    return [preserved, *rows], True
