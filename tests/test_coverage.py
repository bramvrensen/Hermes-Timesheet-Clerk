from timesheet_clerk.coverage import ensure_source_coverage
from timesheet_clerk.sync import attach_source_snapshots, source_delta


def _plan():
    return {
        "schema_version": 1,
        "plan_id": "p",
        "revision": 2,
        "status": "IN_REVIEW",
        "generated_at": "2026-08-25T00:00:00Z",
        "week": {"monday": "2026-08-24", "sunday": "2026-08-30"},
        "contract_hours_default": 36.0,
        "target_hours": 36.0,
        "entries": [{
            "entry_id": "monday",
            "clockify_source_ids": ["c1"],
            "date": "2026-08-24",
            "source": {"description": "Monday"},
            "original_duration_seconds": 3600,
            "planned_duration_seconds": 3600,
            "planned_start": "2026-08-24T09:00:00+02:00",
            "planned_end": "2026-08-24T10:00:00+02:00",
            "booking_mode": "assignment",
            "assignment": {"id": "a"},
            "tier": "AUTO",
            "review_state": "corrected",
        }],
    }


def _source(source_id, start):
    return {
        "id": source_id,
        "description": source_id,
        "client": {"id": "client", "name": "Client"},
        "project": {"id": "project", "name": "Project"},
        "tags": [],
        "start": start,
        "end": start.replace("09:00:00", "10:00:00"),
        "duration_seconds": 3600,
    }


def test_coverage_repair_adds_unprocessed_sources_as_ask_and_preserves_review():
    rows = [
        _source("c1", "2026-08-24T09:00:00Z"),
        _source("c2", "2026-08-25T09:00:00Z"),
        _source("c3", "2026-08-25T09:00:00Z"),
    ]
    plan = attach_source_snapshots(_plan(), rows)
    before = source_delta(plan, rows)
    assert before["covered_count"] == 1
    assert before["unprocessed_count"] == 2

    repaired, added = ensure_source_coverage(plan, rows)
    assert added == ["c2", "c3"]
    assert repaired["status"] == "IN_REVIEW"
    assert repaired["entries"][0]["review_state"] == "corrected"
    added_rows = [row for row in repaired["entries"] if row["entry_id"].startswith("clockify-")]
    assert len(added_rows) == 2
    assert all(row["tier"] == "ASK" for row in added_rows)
    assert all(row["direct_mapping"] == {} for row in added_rows)

    after = source_delta(repaired, rows)
    assert after["unprocessed_count"] == 0
    assert after["covered_count"] == 3


def test_coverage_repair_is_idempotent():
    rows = [_source("c1", "2026-08-24T09:00:00Z"), _source("c2", "2026-08-25T09:00:00Z")]
    plan = attach_source_snapshots(_plan(), rows)
    repaired, first = ensure_source_coverage(plan, rows)
    repaired_again, second = ensure_source_coverage(repaired, rows)
    assert first == ["c2"]
    assert second == []
    assert len(repaired_again["entries"]) == len(repaired["entries"])
