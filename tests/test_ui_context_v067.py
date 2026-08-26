from timesheet_clerk import ui_context
from timesheet_clerk.ui_choices import hour_types_for_service


def test_review_context_uses_nested_project_service_hour_types(tmp_path, monkeypatch):
    monkeypatch.setenv("TIMESHEET_CLERK_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("SIMPLICATE_BASE_URL", "https://example.invalid/api/v2")
    monkeypatch.setenv("SIMPLICATE_API_KEY", "key")
    monkeypatch.setenv("SIMPLICATE_API_SECRET", "secret")
    monkeypatch.setenv("SIMPLICATE_EMPLOYEE_ID", "employee:1")

    class FakeClient:
        def __init__(self, config):
            self.config = config

        def get_projects(self):
            return [{
                "id": "project:p1",
                "name": "NetSuite Implementatie",
                "organization": {"id": "organization:c1", "name": "Cyclovriend B.V."},
            }]

        def get_services(self):
            return [{
                "id": "service:s-travel",
                "name": "Reistijd",
                "project": {"id": "project:p1"},
                "hour_types": [
                    {"id": "hourtype:h-travel", "label": "Reistijd", "billable": False},
                    {"hourtype_id": "hourtype:h-alt", "label": "Reistijd alternatief", "billable": False},
                ],
            }]

        def get_hour_types(self):
            return [
                {"id": "hourtype:h-travel", "label": "Reistijd"},
                {"id": "hourtype:h-alt", "label": "Reistijd alternatief"},
                {"id": "hourtype:h-unrelated", "label": "Senior Consultant"},
            ]

        def get_booking_assignments(self, start_date, end_date):
            return []

    monkeypatch.setattr(ui_context, "SimplicateClient", FakeClient)

    context = ui_context.load_review_context("2026-08-24", "2026-08-30")
    rows = hour_types_for_service(context, "s-travel")

    assert [row["id"] for row in rows] == ["h-travel", "h-alt"]
    assert all(row["source"] == "project_service" for row in rows)
    assert "h-unrelated" not in {row["id"] for row in rows}


def test_review_context_cache_is_versioned_for_067(tmp_path, monkeypatch):
    monkeypatch.setenv("TIMESHEET_CLERK_STATE_DIR", str(tmp_path))
    path = ui_context._cache_path("2026-08-24", "2026-08-30")
    assert "review-context-v067-" in path.name
