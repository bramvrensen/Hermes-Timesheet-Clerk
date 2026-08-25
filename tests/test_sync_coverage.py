from copy import deepcopy

import pytest

from timesheet_clerk.storage import PlanRepository, StateConflict
from timesheet_clerk.sync import attach_source_snapshots
from timesheet_clerk.working import sync_week_plan


def _plan():
    return {
        "schema_version": 1,
        "plan_id": "plan-wk35-test",
        "revision": 1,
        "status": "DRAFT",
        "generated_at": "2026-08-25T00:00:00Z",
        "week": {"monday": "2026-08-24", "sunday": "2026-08-30"},
        "contract_hours_default": 36.0,
        "target_hours": 36.0,
        "entries": [{
            "entry_id": "mon",
            "clockify_source_ids": ["c-mon"],
            "date": "2026-08-24",
            "source": {"description": "Monday"},
            "original_duration_seconds": 3600,
            "planned_duration_seconds": 3600,
            "planned_start": "2026-08-24T09:00:00+02:00",
            "planned_end": "2026-08-24T10:00:00+02:00",
            "booking_mode": "assignment",
            "assignment": {"id": "a-mon"},
            "tier": "AUTO",
        }],
    }


def _source(source_id, description):
    return {
        "id": source_id,
        "description": description,
        "client": None,
        "project": None,
        "start": "2026-08-25T09:00:00Z",
        "end": "2026-08-25T10:00:00Z",
        "duration_seconds": 3600,
    }


def _candidate(ids):
    plan = _plan()
    plan["entries"] = []
    for idx, source_id in enumerate(ids):
        plan["entries"].append({
            "entry_id": f"tue-{idx}",
            "clockify_source_ids": [source_id],
            "date": "2026-08-25",
            "source": {"description": source_id},
            "original_duration_seconds": 3600,
            "planned_duration_seconds": 3600,
            "planned_start": f"2026-08-25T{9+idx:02d}:00:00+02:00",
            "planned_end": f"2026-08-25T{10+idx:02d}:00:00+02:00",
            "booking_mode": "assignment",
            "assignment": {"id": f"a-{idx}"},
            "tier": "AUTO",
        })
    return plan


def test_partial_recovery_sync_is_rejected(tmp_path):
    repo = PlanRepository(tmp_path)
    existing = attach_source_snapshots(_plan(), [
        _source("c-mon", "Monday"),
        _source("c-tue-1", "Tuesday 1"),
        _source("c-tue-2", "Tuesday 2"),
    ])
    repo.create(existing)

    with pytest.raises(StateConflict, match="c-tue-2"):
        sync_week_plan(repo, _candidate(["c-tue-1"]))


def test_complete_recovery_sync_succeeds(tmp_path):
    repo = PlanRepository(tmp_path)
    existing = attach_source_snapshots(_plan(), [
        _source("c-mon", "Monday"),
        _source("c-tue-1", "Tuesday 1"),
        _source("c-tue-2", "Tuesday 2"),
    ])
    repo.create(existing)

    saved = sync_week_plan(repo, _candidate(["c-tue-1", "c-tue-2"]))
    covered = {sid for row in saved["entries"] for sid in row.get("clockify_source_ids", [])}
    assert {"c-mon", "c-tue-1", "c-tue-2"}.issubset(covered)
