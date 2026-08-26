from copy import deepcopy

import timesheet_clerk.orchestration as orchestration
from timesheet_clerk.contracts import validate_plan
from timesheet_clerk.review import apply_review
from timesheet_clerk.scheduling import reflow_plan_days
from timesheet_clerk.storage import PlanRepository


def _entry(eid, start, duration, *, billable=True, ignored=False):
    return {
        "entry_id": eid,
        "clockify_source_ids": [eid],
        "date": "2026-08-24",
        "source": {"id": eid, "description": eid, "start": start, "end": start, "duration_seconds": duration},
        "original_duration_seconds": duration,
        "planned_duration_seconds": duration,
        "planned_start": start,
        "planned_end": start,
        "booking_mode": "direct",
        "direct_mapping": {"project_id": "p", "service_id": "s", "hour_type_id": "h", "billable": billable} if not ignored else {},
        "assignment": {},
        "tier": "AUTO",
        "overall_tier": "AUTO",
        "ignored": ignored,
        "billable": billable and not ignored,
        "mapping_state": "RESOLVED",
    }


def _plan(entries):
    return {
        "schema_version": 1,
        "plan_id": "p1",
        "revision": 1,
        "status": "IN_REVIEW",
        "generated_at": "2026-08-24T00:00:00Z",
        "week": {"monday": "2026-08-24", "sunday": "2026-08-30"},
        "contract_hours_default": 36.0,
        "target_hours": 36.0,
        "entries": entries,
    }


def test_day_reflow_starts_at_0900_and_places_non_billable_first():
    plan = _plan([
        _entry("billable", "2026-08-24T13:00:00+02:00", 7200, billable=True),
        _entry("internal", "2026-08-24T15:00:00+02:00", 1800, billable=False),
    ])
    result = reflow_plan_days(plan)
    rows = [row for row in result["entries"] if not row.get("ignored")]
    assert [row["entry_id"] for row in rows] == ["internal", "billable"]
    assert rows[0]["planned_start"] == "2026-08-24T09:00:00+02:00"
    assert rows[0]["planned_end"] == "2026-08-24T09:30:00+02:00"
    assert rows[1]["planned_start"] == "2026-08-24T09:30:00+02:00"
    assert rows[1]["planned_end"] == "2026-08-24T11:30:00+02:00"


def test_review_duration_change_reflows_whole_day():
    plan = _plan([
        _entry("internal", "2026-08-24T09:00:00+02:00", 1800, billable=False),
        _entry("billable", "2026-08-24T09:30:00+02:00", 3600, billable=True),
    ])
    updated, _, reviewed = apply_review(plan, "internal", {"planned_duration_seconds": 3600})
    rows = {row["entry_id"]: row for row in updated["entries"]}
    assert reviewed["planned_start"] == "2026-08-24T09:00:00+02:00"
    assert rows["billable"]["planned_start"] == "2026-08-24T10:00:00+02:00"


def test_restore_ignored_entry_without_target_reopens_as_ask_pending():
    skipped = _entry("travel", "2026-08-24T07:00:00+02:00", 3600, ignored=True)
    skipped["review_state"] = "skipped"
    skipped["direct_mapping"] = {}
    plan = _plan([skipped, _entry("billable", "2026-08-24T10:00:00+02:00", 3600)])
    updated, _, reviewed = apply_review(plan, "travel", {"ignored": False})
    assert reviewed["ignored"] is False
    assert reviewed["tier"] == "ASK"
    assert reviewed["overall_tier"] == "ASK"
    assert reviewed["mapping_state"] == "PENDING"
    assert reviewed.get("review_state") is None
    validate_plan(updated)


def _source(source_id, description):
    return {
        "id": source_id,
        "description": description,
        "client": None,
        "project": None,
        "tags": [],
        "start": "2026-08-24T12:00:00+02:00",
        "end": "2026-08-24T13:30:00+02:00",
        "duration_seconds": 5400,
    }


def test_unclassified_source_cannot_be_silently_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestration, "read_config", lambda: {"contract_hours_default": 36.0})
    repo = PlanRepository(tmp_path)
    decision = {
        "source_id": "unknown",
        "tier": "AUTO",
        "ignored": True,
        "why": "unknown so ignore",
    }
    result = orchestration.apply_mapping_decisions(
        repo,
        [_source("unknown", "?? -- ??")],
        monday="2026-08-24",
        sunday="2026-08-30",
        decisions=[decision],
    )["plan"]
    entry = result["entries"][0]
    assert entry["ignored"] is False
    assert entry["tier"] == "ASK"
    assert entry["mapping_state"] == "PENDING"
    assert entry["planned_start"] == "2026-08-24T09:00:00+02:00"
