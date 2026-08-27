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
                    "id": "assignment:77b0674f1c503fe2b61e8ec4cf9407af",
                    "project": {"id": "project:93b0674f1c503fe2b61e8ec4cf9407af"},
                    "projectservice": {"id": "019b2c90-a472-7252-86dc-be5b658e74d9"},
                    "projecthourstype": {
                        "hourstype": {"id": "hourtype:48d0674f1c503fe2b61e8ec4cf9407af"}
                    },
                    "start_date": "2026-08-01",
                    "end_date": "2026-09-30",
                },
                "billable": True,
                "tier": "AUTO",
            }
        ],
    }


def test_api_id_enforces_write_prefixes_and_projectservice_exception():
    uuid_value = "019b2c90-a472-7252-86dc-be5b658e74d9"
    hex_value = "48d0674f1c503fe2b61e8ec4cf9407af"
    assert _api_id("project", hex_value) == f"project:{hex_value}"
    assert _api_id("project", f"project:{hex_value}") == f"project:{hex_value}"
    assert _api_id("hourstype", f"hourtype:{hex_value}") == f"hourstype:{hex_value}"
    assert _api_id("hourstype", uuid_value) == f"hourstype:{uuid_value}"
    assert _api_id("assignment", hex_value) == f"assignment:{hex_value}"
    assert _api_id("projectservice", uuid_value) == uuid_value
    assert _api_id("projectservice", hex_value) == f"service:{hex_value}"
    assert _api_id("projectservice", f"projectservice:{hex_value}") == f"service:{hex_value}"


def test_assignment_payload_uses_authoritative_simplicate_assignment_shape():
    entry = _snapshot()["entries"][0]
    payload = _entry_payload(entry, "employee:6584321abcdef")
    assert payload["employee_id"] == "employee:6584321abcdef"
    assert payload["project_id"] == "project:93b0674f1c503fe2b61e8ec4cf9407af"
    assert payload["projectservice_id"] == "019b2c90-a472-7252-86dc-be5b658e74d9"
    assert payload["type_id"] == "hourstype:48d0674f1c503fe2b61e8ec4cf9407af"
    assert payload["assignment_id"] == "assignment:77b0674f1c503fe2b61e8ec4cf9407af"
    assert payload["hours"] == 1.5
    assert payload["billable"] is True
    assert payload["start_date"] == "2026-08-24 09:00:00"
    assert payload["end_date"] == "2026-08-24 10:30:00"


def test_direct_payload_matches_simplicate_ad_hoc_contract():
    entry = {
        "entry_id": "direct-a",
        "date": "2026-08-24",
        "source": {"description": "JIRA ticket update"},
        "planned_duration_seconds": 7200,
        "planned_start": "2026-08-24T09:00:00+02:00",
        "planned_end": "2026-08-24T11:00:00+02:00",
        "booking_mode": "direct",
        "billable": True,
        "direct_mapping": {
            "project": {"id": "project:93b0674f1c503fe2b61e8ec4cf9407af", "name": "Kruitbosch"},
            "projectservice": {"id": "019b2c90-a472-7252-86dc-be5b658e74d9", "name": "Senior Consultant"},
            "type": {"id": "hourtype:48d0674f1c503fe2b61e8ec4cf9407af", "name": "Senior Consultant"},
        },
    }
    payload = _entry_payload(entry, "6584321abcdef")
    assert payload["employee_id"] == "employee:6584321abcdef"
    assert payload["project_id"] == "project:93b0674f1c503fe2b61e8ec4cf9407af"
    assert payload["projectservice_id"] == "019b2c90-a472-7252-86dc-be5b658e74d9"
    assert payload["type_id"] == "hourstype:48d0674f1c503fe2b61e8ec4cf9407af"
    assert payload["hours"] == 2.0
    assert payload["billable"] is True
    assert "assignment_id" not in payload


def test_direct_payload_32_hex_service_uses_service_prefix():
    entry = {
        "entry_id": "direct-b",
        "date": "2026-08-24",
        "source": {"description": "Project work"},
        "planned_duration_seconds": 3600,
        "planned_start": "2026-08-24T09:00:00+02:00",
        "planned_end": "2026-08-24T10:00:00+02:00",
        "booking_mode": "direct",
        "direct_mapping": {
            "project_id": "93b0674f1c503fe2b61e8ec4cf9407af",
            "service_id": "1234567890abcdef1234567890abcdef",
            "hour_type_id": "48d0674f1c503fe2b61e8ec4cf9407af",
            "billable": False,
        },
    }
    payload = _entry_payload(entry, "6584321abcdef")
    assert payload["project_id"] == "project:93b0674f1c503fe2b61e8ec4cf9407af"
    assert payload["projectservice_id"] == "service:1234567890abcdef1234567890abcdef"
    assert payload["type_id"] == "hourstype:48d0674f1c503fe2b61e8ec4cf9407af"
    assert payload["billable"] is False


def test_build_booking_rows_uses_only_approved_non_skipped_entries():
    snapshot = _snapshot()
    rows = build_booking_rows(snapshot, "employee-a")
    assert len(rows) == 1
    assert rows[0]["entry_id"] == "entry-a"
