from timesheet_clerk.ui_choices import hour_types_for_service


def test_hour_types_are_strictly_scoped_to_selected_service():
    context = {
        "hour_types": [
            {"id": "h1", "name": "Senior", "service_id": "s1"},
            {"id": "h2", "name": "Junior", "service_id": "s1"},
            {"id": "h3", "name": "Senior", "service_id": "s2"},
        ],
        "all_hour_types": [
            {"id": "h1", "name": "Senior"},
            {"id": "h2", "name": "Junior"},
            {"id": "h3", "name": "Senior"},
            {"id": "global-only", "name": "Global only"},
        ],
    }

    rows = hour_types_for_service(context, "s1")
    assert [row["id"] for row in rows] == ["h1", "h2"]


def test_hour_type_choice_has_no_global_fallback():
    context = {
        "hour_types": [{"id": "h1", "name": "Senior", "service_id": "s1"}],
        "all_hour_types": [{"id": "global-only", "name": "Global only"}],
    }

    assert hour_types_for_service(context, "s2") == []
    assert hour_types_for_service(context, "") == []
