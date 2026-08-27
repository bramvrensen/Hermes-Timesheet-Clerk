from copy import deepcopy

from timesheet_clerk.contracts import new_plan_skeleton
from timesheet_clerk.single_booking import execute_single_entry_booking, task_booking_ready
from timesheet_clerk.storage import PlanRepository


def _entry():
    return {
        "entry_id": "e1",
        "clockify_source_ids": ["c1"],
        "date": "2026-08-24",
        "source": {"description": "Test task", "client": {"name": "Client"}, "project": {"name": "Project"}},
        "original_duration_seconds": 3600,
        "planned_duration_seconds": 3600,
        "planned_start": "2026-08-24T09:00:00+02:00",
        "planned_end": "2026-08-24T10:00:00+02:00",
        "tier": "PROPOSE",
        "overall_tier": "PROPOSE",
        "review_state": "corrected",
        "mapping_state": "RESOLVED",
        "booking_mode": "direct",
        "ignored": False,
        "direct_mapping": {
            "project_id": "p1",
            "project_name": "Project",
            "service_id": "s1",
            "service_name": "Task",
            "hour_type_id": "h1",
            "hour_type_name": "Senior Consultant",
            "billable": True,
        },
    }


def test_task_booking_ready_requires_review_for_propose(monkeypatch):
    monkeypatch.setenv("SIMPLICATE_BASE_URL", "https://example.invalid/api/v2")
    monkeypatch.setenv("SIMPLICATE_API_KEY", "k")
    monkeypatch.setenv("SIMPLICATE_API_SECRET", "s")
    monkeypatch.setenv("SIMPLICATE_EMPLOYEE_ID", "emp1")
    entry = _entry()
    entry["review_state"] = None
    ready, _ = task_booking_ready(entry)
    assert ready is False


def test_single_booking_writes_receipt_then_marks_verified(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICATE_BASE_URL", "https://example.invalid/api/v2")
    monkeypatch.setenv("SIMPLICATE_API_KEY", "k")
    monkeypatch.setenv("SIMPLICATE_API_SECRET", "s")
    monkeypatch.setenv("SIMPLICATE_EMPLOYEE_ID", "emp1")

    repo = PlanRepository(tmp_path)
    plan = new_plan_skeleton(plan_id="p", monday="2026-08-24", sunday="2026-08-30")
    plan["status"] = "IN_REVIEW"
    plan["entries"] = [_entry()]
    repo.create(plan)

    import timesheet_clerk.single_booking as sb

    class FakeClient:
        def __init__(self, config):
            self.config = config
        def get_booked_hours(self, start, end):
            if getattr(self, "after_post", False):
                return []
            return []

    posted = {"done": False}

    class StatefulClient:
        def __init__(self, config):
            self.config = config
        def get_booked_hours(self, start, end):
            if not posted["done"]:
                return []
            return [{
                "id": "hours:1",
                "project": {"id": "project:p1"},
                "projectservice": {"id": "projectservice:s1"},
                "type": {"id": "hourstype:h1"},
                "start_date": "2026-08-24 09:00:00",
                "hours": 1.0,
            }]

    monkeypatch.setattr(sb, "SimplicateClient", StatefulClient)
    monkeypatch.setattr(sb, "_post_hours", lambda config, payload: posted.update(done=True) or {"id": "hours:1"})

    result = execute_single_entry_booking(repo, "p", "e1")
    assert result["verified"] is True
    latest = repo.get_latest("p")
    assert latest["entries"][0]["reconciliation_state"] == "BOOKED"
    assert len(list(repo.receipts_dir.glob("*.json"))) == 1

    try:
        execute_single_entry_booking(repo, "p", "e1")
    except Exception as exc:
        assert "already" in str(exc).lower()
    else:
        raise AssertionError("second booking should be blocked")
