from timesheet_clerk.simplicate import _normalize_assignment


def test_assignment_normalization_uses_nested_hourstype_not_relation_id():
    raw = {
        "id": "assignment:dc6ddc19510f89fa57d3eca657b9323c",
        "name": "Senior Consultant",
        "project": {
            "id": "project:005b19498332d6b64c13c77ab857ae53",
            "name": "Kruitbosch",
            "organization": {"id": "organization:c1", "name": "Kruitbosch"},
        },
        "projectservice": {
            "id": "019e4a9a-56b8-73f0-96df-1fe506d2aea5",
            "name": "Opleveren omgeving n.a.v. bevindingen-WMS/Logistiek",
            "use_in_resource_planner": True,
        },
        "projecthourstype": {
            "id": "projecthourstype:ef3f619c63b8e6b2b7aae5691f08671e",
            "hourstype": {
                "id": "hourstype:f902fc5514b044a2",
                "label": "Senior Consultant",
            },
        },
        "start_date": "2026-08-10",
        "end_date": "2026-10-31",
        "is_planned": True,
        "status": {"id": "status:todo", "name": "Te doen"},
    }

    result = _normalize_assignment(raw)

    assert result["hour_type"] == {"id": "f902fc5514b044a2", "name": "Senior Consultant"}
    assert result["projecthourstype_id"] == "ef3f619c63b8e6b2b7aae5691f08671e"
    assert result["hour_type"]["id"] != result["projecthourstype_id"]
