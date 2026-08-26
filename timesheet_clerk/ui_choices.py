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
