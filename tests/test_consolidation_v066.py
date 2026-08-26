from timesheet_clerk.consolidation import consolidate_reviewed_entries
from timesheet_clerk.review import apply_review
from timesheet_clerk.scheduling import reflow_plan_days
from timesheet_clerk.ui_time import format_duration


def _entry(eid, source_id, start, *, review_state=None, service_id="travel", hour_type_id="travel-rate"):
    return {
        "entry_id": eid,
        "clockify_source_ids": [source_id],
        "date": "2026-08-25",
        "source": {
            "id": source_id,
            "description": "Reistijd",
            "client": {"id": "cyclo", "name": "Cyclovriend"},
            "project": {"id": "CYCL1273", "name": "NetSuite Implementatie"},
            "start": start,
            "end": start,
            "duration_seconds": 3600,
        },
        "original_duration_seconds": 3600,
        "planned_duration_seconds": 3600,
        "planned_start": start,
        "planned_end": start,
        "booking_mode": "direct",
        "direct_mapping": {
            "customer_id": "cyclo",
            "project_id": "CYCL1273",
            "service_id": service_id,
            "hour_type_id": hour_type_id,
            "billable": False,
        },
        "assignment": {},
        "tier": "ASK",
        "overall_tier": "ASK",
        "ignored": False,
        "billable": False,
        "mapping_state": "RESOLVED",
        "review_state": review_state,
    }


def _plan(entries):
    return {
        "schema_version": 1,
        "plan_id": "p1",
        "revision": 1,
        "status": "IN_REVIEW",
        "generated_at": "2026-08-25T00:00:00Z",
        "week": {"monday": "2026-08-24", "sunday": "2026-08-30"},
        "contract_hours_default": 36.0,
        "target_hours": 36.0,
        "entries": entries,
    }


def test_two_reviewed_adjacent_travel_rows_consolidate_to_two_hours():
    plan = reflow_plan_days(_plan([
        _entry("travel-1", "c1", "2026-08-25T07:00:00+02:00", review_state="corrected"),
        _entry("travel-2", "c2", "2026-08-25T08:00:00+02:00", review_state="corrected"),
    ]))
    result = consolidate_reviewed_entries(plan)
    assert len(result["entries"]) == 1
    row = result["entries"][0]
    assert row["clockify_source_ids"] == ["c1", "c2"]
    assert row["planned_duration_seconds"] == 7200
    assert row["planned_start"] == "2026-08-25T09:00:00+02:00"
    assert row["planned_end"] == "2026-08-25T11:00:00+02:00"


def test_different_booking_target_does_not_consolidate():
    plan = reflow_plan_days(_plan([
        _entry("travel-1", "c1", "2026-08-25T07:00:00+02:00", review_state="corrected"),
        _entry("travel-2", "c2", "2026-08-25T08:00:00+02:00", review_state="corrected", hour_type_id="other-rate"),
    ]))
    assert len(consolidate_reviewed_entries(plan)["entries"]) == 2


def test_unreviewed_peer_does_not_consolidate():
    plan = reflow_plan_days(_plan([
        _entry("travel-1", "c1", "2026-08-25T07:00:00+02:00", review_state="corrected"),
        _entry("travel-2", "c2", "2026-08-25T08:00:00+02:00", review_state=None),
    ]))
    assert len(consolidate_reviewed_entries(plan)["entries"]) == 2


def test_apply_review_consolidates_after_second_human_mapping():
    first = _entry("travel-1", "c1", "2026-08-25T07:00:00+02:00", review_state="corrected")
    second = _entry("travel-2", "c2", "2026-08-25T08:00:00+02:00", review_state=None)
    second["mapping_state"] = "PENDING"
    second["direct_mapping"] = {}
    plan = reflow_plan_days(_plan([first, second]))
    mapping = {
        "booking_mode": "direct",
        "direct_mapping": {
            "customer_id": "cyclo",
            "project_id": "CYCL1273",
            "service_id": "travel",
            "hour_type_id": "travel-rate",
            "billable": False,
        },
    }
    updated, _, reviewed = apply_review(plan, "travel-2", mapping)
    assert len(updated["entries"]) == 1
    assert reviewed["entry_id"] == "travel-2"
    assert reviewed["planned_duration_seconds"] == 7200
    assert reviewed["clockify_source_ids"] == ["c1", "c2"]


def test_human_duration_labels():
    assert format_duration(900) == "15 min"
    assert format_duration(1800) == "30 min"
    assert format_duration(3600) == "1u"
    assert format_duration(5400) == "1u 30 min"
    assert format_duration(7200) == "2u"
    assert format_duration(-1800, signed=True) == "−30 min"
    assert format_duration(1800, signed=True) == "+30 min"
