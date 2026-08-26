"""Deterministically hydrate planner entries from live Clockify source rows.

The planner owns mapping decisions. Clockify source fidelity is owned by the plugin:
source facts are copied from normalized Clockify rows immediately before plan create
or sync so an LLM cannot accidentally drop titles, source durations or source metadata.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .storage import StateConflict
from .sync import covered_source_ids

_SOURCE_KEYS = ("description", "client", "project", "tags", "start", "end", "duration_seconds")


def hydrate_plan_sources(plan: dict[str, Any], clockify_entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a copy whose entries carry canonical Clockify source facts.

    A one-source plan row gets the complete normalized Clockify source bundle.
    Multi-source rows retain their planner-facing aggregate label but receive
    ``source_bundles`` with every canonical source and a summed original duration.
    Every referenced Clockify ID must exist in the supplied live source interval.
    """
    result = deepcopy(plan)
    by_id = {str(row.get("id")): row for row in clockify_entries if row.get("id")}

    for entry in result.get("entries") or []:
        source_ids = [str(value) for value in (entry.get("clockify_source_ids") or []) if value]
        missing = [source_id for source_id in source_ids if source_id not in by_id]
        if missing:
            raise StateConflict(
                f"plan entry {entry.get('entry_id')} references Clockify source(s) outside the live week: "
                + ", ".join(missing)
            )
        bundles = [_canonical_source(by_id[source_id]) for source_id in source_ids]
        if len(bundles) == 1:
            bundle = bundles[0]
            entry["source"] = deepcopy(bundle)
            entry["original_duration_seconds"] = float(bundle.get("duration_seconds") or 0)
            entry.pop("source_bundles", None)
        else:
            entry["source_bundles"] = deepcopy(bundles)
            entry["original_duration_seconds"] = sum(float(row.get("duration_seconds") or 0) for row in bundles)
            # Preserve an aggregate planner label when present. If absent, provide
            # a deterministic source object rather than leaving the UI empty.
            if not isinstance(entry.get("source"), dict):
                entry["source"] = {
                    "description": " + ".join(str(row.get("description") or "") for row in bundles).strip(" +"),
                    "client": None,
                    "project": None,
                    "tags": [],
                    "start": min((str(row.get("start") or "") for row in bundles), default=""),
                    "end": max((str(row.get("end") or "") for row in bundles), default=""),
                    "duration_seconds": entry["original_duration_seconds"],
                }

    incoming_ids = set(by_id)
    covered = covered_source_ids(result)
    omitted = sorted(incoming_ids - covered)
    if omitted:
        raise StateConflict("plan does not cover all Clockify sources in the live week: " + ", ".join(omitted))
    return result


def _canonical_source(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        **{key: deepcopy(row.get(key)) for key in _SOURCE_KEYS},
    }
