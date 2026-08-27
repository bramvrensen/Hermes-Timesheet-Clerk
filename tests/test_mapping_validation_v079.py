from timesheet_clerk.mapping_validation import entry_mapping_invalid_reason, normalize_decision_against_snapshot


def context():
    assignment = {
        "id": "a1",
        "project": {"id": "p1", "name": "Project"},
        "task": {"id": "s1", "name": "Consulting"},
        "hour_type": {"id": "h1", "name": "Senior Consultant"},
    }
    return {
        "projects": [{"id": "project:p1", "name": "Project"}],
        "services": [{
            "id": "service:s1",
            "name": "Consulting",
            "project": {"id": "project:p1"},
            "hour_types": [{
                "id": "projecthourstype:RELATION",
                "hourstype": {"id": "hourstype:h1", "name": "Senior Consultant"},
            }],
        }],
        "planned_assignments": [assignment],
        "booking_assignments": [assignment],
    }


def test_assignment_decision_is_replaced_with_snapshot_assignment():
    decision = {"source_id": "c1", "tier": "AUTO", "booking_mode": "assignment", "assignment": {"id": "a1", "hour_type": {"id": "STALE"}}}
    normalized, reason = normalize_decision_against_snapshot(decision, context())
    assert reason is None
    assert normalized["assignment"]["hour_type"]["id"] == "h1"


def test_direct_mapping_requires_hour_type_scoped_to_service():
    decision = {
        "source_id": "c1", "tier": "AUTO", "booking_mode": "direct",
        "direct_mapping": {"project_id": "p1", "service_id": "s1", "hour_type_id": "wrong"},
    }
    _, reason = normalize_decision_against_snapshot(decision, context())
    assert "not valid for service" in reason


def test_existing_assignment_missing_from_next_snapshot_is_invalid():
    entry = {"booking_mode": "assignment", "assignment": {"id": "gone"}, "ignored": False}
    assert "not present" in entry_mapping_invalid_reason(entry, context())
