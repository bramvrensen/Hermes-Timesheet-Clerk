from copy import deepcopy

import pytest

from timesheet_clerk.source_hydration import hydrate_plan_sources
from timesheet_clerk.storage import StateConflict


def source(source_id="c1", description="Projectmeeting", duration=3600):
    return {
        "id": source_id,
        "description": description,
        "client": {"id": "customer-1", "name": "Kruitbosch"},
        "project": {"id": "project-1", "name": "Implementation"},
        "tags": [{"id": "tag-1", "name": "work"}],
        "start": "2026-08-24T07:00:00+02:00",
        "end": "2026-08-24T08:00:00+02:00",
        "duration_seconds": duration,
    }


def plan():
    return {
        "schema_version": 1,
        "plan_id": "fresh",
        "revision": 1,
        "status": "DRAFT",
        "generated_at": "2026-08-26T12:00:00Z",
        "week": {"monday": "2026-08-24", "sunday": "2026-08-30"},
        "contract_hours_default": 36.0,
        "target_hours": 36.0,
        "entries": [{
            "entry_id": "entry-1",
            "clockify_source_ids": ["c1"],
            "date": "2026-08-24",
            "source": {},
            "original_duration_seconds": 0,
            "planned_duration_seconds": 7200,
            "planned_start": "2026-08-24T07:00:00+02:00",
            "planned_end": "2026-08-24T09:00:00+02:00",
            "booking_mode": "assignment",
            "assignment": {"id": "assignment-1"},
            "tier": "AUTO",
        }],
    }


def test_hydration_restores_title_metadata_and_original_duration():
    hydrated = hydrate_plan_sources(plan(), [source()])
    entry = hydrated["entries"][0]

    assert entry["source"]["id"] == "c1"
    assert entry["source"]["description"] == "Projectmeeting"
    assert entry["source"]["client"]["name"] == "Kruitbosch"
    assert entry["source"]["project"]["name"] == "Implementation"
    assert entry["source"]["tags"][0]["name"] == "work"
    assert entry["source"]["start"] == "2026-08-24T07:00:00+02:00"
    assert entry["source"]["end"] == "2026-08-24T08:00:00+02:00"
    assert entry["original_duration_seconds"] == 3600
    # Planner-adjusted working duration remains a mapping/planning concern.
    assert entry["planned_duration_seconds"] == 7200


def test_hydration_replaces_stale_planner_source_facts():
    incoming = plan()
    incoming["entries"][0]["source"] = {"description": "Untitled"}
    incoming["entries"][0]["original_duration_seconds"] = 0

    hydrated = hydrate_plan_sources(incoming, [source(description="Correct title", duration=5400)])

    assert hydrated["entries"][0]["source"]["description"] == "Correct title"
    assert hydrated["entries"][0]["original_duration_seconds"] == 5400


def test_hydration_rejects_missing_live_source():
    with pytest.raises(StateConflict, match="outside the live week"):
        hydrate_plan_sources(plan(), [])


def test_hydration_rejects_incomplete_week_coverage():
    with pytest.raises(StateConflict, match="does not cover all Clockify sources"):
        hydrate_plan_sources(plan(), [source(), source("c2", "Second")])


def test_multi_source_entry_keeps_all_canonical_bundles():
    incoming = plan()
    incoming["entries"][0]["clockify_source_ids"] = ["c1", "c2"]
    incoming["entries"][0]["source"] = {"description": "Aggregated work"}

    hydrated = hydrate_plan_sources(incoming, [source(), source("c2", "Second", 1800)])
    entry = hydrated["entries"][0]

    assert entry["source"]["description"] == "Aggregated work"
    assert [row["id"] for row in entry["source_bundles"]] == ["c1", "c2"]
    assert entry["original_duration_seconds"] == 5400
