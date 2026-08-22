from timesheet_clerk.sync import plan_summary, source_delta


def plan():
    return {
        "plan_id": "p",
        "revision": 3,
        "status": "IN_REVIEW",
        "source_sync_at": "2026-08-22T12:00:00Z",
        "entries": [
            {
                "entry_id": "e1",
                "clockify_source_ids": ["c1"],
                "source": {"description": "Meeting", "client": {"name": "Client"}, "project": {"name": "Project"}, "start": "2026-08-22T09:00:00Z", "end": "2026-08-22T10:00:00Z"},
                "original_duration_seconds": 3600,
                "planned_duration_seconds": 3600,
                "tier": "PROPOSE",
            },
            {
                "entry_id": "e2",
                "clockify_source_ids": ["c2"],
                "source": {"description": "Lunch"},
                "original_duration_seconds": 1800,
                "planned_duration_seconds": 1800,
                "ignored": True,
                "tier": "ASK",
                "review_state": "skipped",
            },
        ],
    }


def source(id="c1", duration=3600):
    return {"id": id, "description": "Meeting", "client": {"name": "Client"}, "project": {"name": "Project"}, "start": "2026-08-22T09:00:00Z", "end": "2026-08-22T10:00:00Z", "duration_seconds": duration}


def test_source_delta_detects_noop_and_missing():
    delta = source_delta(plan(), [source(), {"id": "c2", "description": "Lunch", "duration_seconds": 1800}])
    assert delta["has_changes"] is False
    assert delta["unchanged_count"] == 2


def test_source_delta_returns_only_changed_and_new_rows():
    delta = source_delta(plan(), [source(duration=1800), {"id": "c3", "description": "New", "duration_seconds": 900}])
    assert delta["has_changes"] is True
    assert delta["changed_count"] == 1
    assert delta["new_count"] == 1
    assert delta["missing_source_ids"] == ["c2"]


def test_plan_summary_is_deterministic():
    summary = plan_summary(plan())
    assert summary["clocked_hours"] == 1.5
    assert summary["workable_hours"] == 1.0
    assert summary["ignored_count"] == 1
    assert summary["pending_review_count"] == 1
