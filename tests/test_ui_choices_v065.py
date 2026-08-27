from timesheet_clerk.ui_choices import editor_hour_type_choices, hour_types_for_service


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


def test_editor_preserves_persisted_hour_type_when_same_service_scope_is_missing():
    rows, preserved = editor_hour_type_choices(
        {"hour_types": [], "all_hour_types": [{"id": "other", "name": "Other"}]},
        "service-travel",
        current_service_id="service-travel",
        current_hour_type_id="travel-hour-type",
        current_hour_type_name="Reistijd",
    )
    assert preserved is True
    assert rows == [{
        "id": "travel-hour-type",
        "name": "Reistijd",
        "service_id": "service-travel",
        "source": "persisted_mapping",
        "scope_verified": False,
    }]


def test_editor_does_not_carry_old_hour_type_to_different_service():
    rows, preserved = editor_hour_type_choices(
        {"hour_types": [{"id": "new", "name": "Senior", "service_id": "service-new"}]},
        "service-new",
        current_service_id="service-old",
        current_hour_type_id="old",
        current_hour_type_name="Old",
    )
    assert preserved is False
    assert [row["id"] for row in rows] == ["new"]
