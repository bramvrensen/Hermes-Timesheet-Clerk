from timesheet_clerk.sync import attach_source_snapshots, plan_summary, source_delta


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
                "source": {"description": "Meeting", "client": {"name": "Client"}, "project": {"name": "Project"}},
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


def source(id="c1", duration=3600, description="Meeting", project="Project"):
    return {
        "id": id,
        "description": description,
        "client": {"id": "client-1", "name": "Client"},
        "project": {"id": "project-1", "name": project},
        "start": "2026-08-22T09:00:00Z",
        "end": "2026-08-22T10:00:00Z",
        "duration_seconds": duration,
    }


def baseline_plan():
    rows = [source(), source("c2", 1800, "Lunch", "Internal")]
    return attach_source_snapshots(plan(), rows), rows


def test_legacy_plan_requires_rebaseline_instead_of_guessing_changes():
    delta = source_delta(plan(), [source(), source("c2", 1800, "Lunch", "Internal")])
    assert delta["has_changes"] is True
    assert delta["requires_rebaseline"] is True
    assert delta["changed_count"] == 0
    assert delta["new_count"] == 0


def test_source_delta_detects_noop_after_baseline():
    stored, rows = baseline_plan()
    delta = source_delta(stored, rows)
    assert delta["has_changes"] is False
    assert delta["requires_rebaseline"] is False
    assert delta["unchanged_count"] == 2
    assert delta["unprocessed_count"] == 0
    assert delta["new_count"] == 0
    assert delta["changed_count"] == 0
    assert delta["missing_count"] == 0


def test_source_delta_returns_only_changed_new_and_missing_rows():
    stored, _ = baseline_plan()
    delta = source_delta(stored, [source(duration=1800), source("c3", 900, "New", "New project")])
    assert delta["has_changes"] is True
    assert delta["changed_count"] == 1
    assert delta["new_count"] == 1
    assert delta["missing_source_ids"] == ["c2"]


def test_baseline_sources_missing_from_plan_are_unprocessed():
    p = plan()
    p["entries"] = [p["entries"][0]]
    rows = [source(), source("c2", 1800, "Lunch", "Internal"), source("c3", 900, "Tuesday", "Client work")]
    stored = attach_source_snapshots(p, rows)

    delta = source_delta(stored, rows)

    assert delta["new_count"] == 0
    assert delta["changed_count"] == 0
    assert delta["missing_count"] == 0
    assert delta["unchanged_count"] == 3
    assert delta["covered_count"] == 1
    assert delta["unprocessed_count"] == 2
    assert [row["id"] for row in delta["unprocessed_entries"]] == ["c2", "c3"]
    assert delta["has_changes"] is True


def test_multi_source_aggregate_does_not_create_false_changes():
    p = plan()
    p["entries"] = [{
        "entry_id": "aggregate",
        "clockify_source_ids": ["c1", "c2"],
        "source": {"description": "Aggregated planner label"},
        "original_duration_seconds": 5400,
        "planned_duration_seconds": 5400,
        "booking_mode": "assignment",
        "assignment": {"id": "a"},
        "tier": "AUTO",
        "date": "2026-08-22",
    }]
    rows = [source(), source("c2", 1800, "Lunch", "Internal")]
    p = attach_source_snapshots(p, rows)
    delta = source_delta(p, rows)
    assert delta["has_changes"] is False
    assert delta["unchanged_count"] == 2
    assert delta["unprocessed_count"] == 0


def test_simplicate_or_review_fields_do_not_change_source_snapshot():
    stored, rows = baseline_plan()
    stored["entries"][0]["planned_duration_seconds"] = 7200
    stored["entries"][0]["assignment"] = {"id": "different-target"}
    stored["entries"][0]["review_state"] = "corrected"
    delta = source_delta(stored, rows)
    assert delta["has_changes"] is False


def test_plan_summary_is_deterministic():
    summary = plan_summary(plan())
    assert summary["clocked_hours"] == 1.5
    assert summary["workable_hours"] == 1.0
    assert summary["ignored_count"] == 1
    assert summary["pending_review_count"] == 1
