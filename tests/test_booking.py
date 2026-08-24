from timesheet_clerk.booking import _api_id, _entry_payload, build_booking_rows


def _snapshot():
    return {
        "plan_id": "2026-W35-live",
        "revision": 7,
        "status": "APPROVED",
        "week": {"monday": "2026-08-24", "sunday": "2026-08-30"},
        "entries": [
            {
                "entry_id": "entry-a",
                "clockify_source_ids": ["clock-a"],
                "date": "2026-08-24",
                "source": {"description": "Project work"},
                "planned_duration_seconds": 5400,
                "planned_start": "2026-08-24T09:00:00+02:00",
                "planned_end": "2026-08-24T10:30:00+02:00",
                "booking_mode": "assignment",
                "assignment": {
                    "id": "assign-a",
                    "project": {"id": "project-a"},
                    "task": {"id": "service-a"},
                    "hour_type": {"id": "type-a"},
                    "start_date": "2026-08-01",
                    "end_date": "2026-09-30",
                },
                "tier": "AUTO",
            }
        ],
    }


def test_api_id_keeps_uuid_and_prefixes_legacy_ids():
    assert _api_id("project", "abc") == "project:abc"
    assert _api_id("project", "project:abc") == "project:abc"
    assert _api_id("projectservice", "01930bb6-87aa-779b-9561-fcb44ac3121d") == "01930bb6-87aa-779b-9561-fcb44ac3121d"


def test_assignment_payload_is_deterministic():
    entry = _snapshot()["entries"][0]
    payload = _entry_payload(entry, "employee-a")
    assert payload["employee_id"] == "employee:employee-a"
    assert payload["project_id"] == "project:project-a"
    assert payload["projectservice_id"] == "projectservice:service-a"
    assert payload["type_id"] == "hourstype:type-a"
    assert payload["assignment_id"] == "assignment:assign-a"
    assert payload["hours"] == 1.5
    assert payload["start_date"] == "2026-08-24 09:00:00"


def test_build_booking_rows_uses_only_approved_non_skipped_entries():
    snapshot = _snapshot()
    rows = build_booking_rows(snapshot, "employee-a")
    assert len(rows) == 1
    assert rows[0]["entry_id"] == "entry-a"
