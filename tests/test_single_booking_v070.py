from timesheet_clerk.contracts import new_plan_skeleton
from timesheet_clerk.single_booking import execute_single_entry_booking, preview_single_entry, task_booking_ready
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
            "project_id": "p1", "project_name": "Project",
            "service_id": "s1", "service_name": "Task",
            "hour_type_id": "h1", "hour_type_name": "Senior Consultant", "billable": True,
        },
    }


def _env(monkeypatch):
    monkeypatch.setenv("SIMPLICATE_BASE_URL", "https://example.invalid/api/v2")
    monkeypatch.setenv("SIMPLICATE_API_KEY", "k")
    monkeypatch.setenv("SIMPLICATE_API_SECRET", "s")
    monkeypatch.setenv("SIMPLICATE_EMPLOYEE_ID", "emp1")


def test_task_booking_ready_requires_review_for_propose(monkeypatch):
    _env(monkeypatch)
    entry = _entry()
    entry["review_state"] = None
    ready, _ = task_booking_ready(entry)
    assert ready is False


def test_single_booking_writes_receipt_then_marks_verified(monkeypatch, tmp_path):
    _env(monkeypatch)
    repo = PlanRepository(tmp_path)
    plan = new_plan_skeleton(plan_id="p", monday="2026-08-24", sunday="2026-08-30")
    plan["status"] = "IN_REVIEW"
    plan["entries"] = [_entry()]
    repo.create(plan)

    import timesheet_clerk.single_booking as sb
    posted = {"done": False}

    class StatefulClient:
        def __init__(self, config): self.config = config
        def get_hour_types(self): return [{"id": "hourstype:h1", "label": "Senior Consultant"}]
        def get_booked_hours(self, start, end):
            if not posted["done"]: return []
            return [{
                "id": "hours:1", "project": {"id": "project:p1"},
                "projectservice": {"id": "service:s1"}, "type": {"id": "hourstype:h1"},
                "start_date": "2026-08-24 09:00:00", "hours": 1.0,
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


def test_assignment_preview_rehydrates_stale_hour_type_before_payload(monkeypatch, tmp_path):
    _env(monkeypatch)
    repo = PlanRepository(tmp_path)
    plan = new_plan_skeleton(plan_id="p", monday="2026-08-24", sunday="2026-08-30")
    plan["status"] = "IN_REVIEW"
    entry = _entry()
    entry["booking_mode"] = "assignment"
    entry["direct_mapping"] = {}
    entry["assignment"] = {
        "id": "assign1",
        "project": {"id": "p1", "name": "Project"},
        "task": {"id": "019e4a9a-56b8-73f0-96df-1fe506d2aea5", "name": "Task"},
        "hour_type": {"id": "WRONG_RELATION_ID", "name": None},
        "start_date": "2026-08-01", "end_date": "2026-08-31",
    }
    plan["entries"] = [entry]
    repo.create(plan)

    import timesheet_clerk.single_booking as sb

    class LiveClient:
        def __init__(self, config): self.config = config
        def get_booking_assignments(self, start, end):
            return [{
                "id": "assign1",
                "project": {"id": "p1", "name": "Project"},
                "task": {"id": "019e4a9a-56b8-73f0-96df-1fe506d2aea5", "name": "Task"},
                "hour_type": {"id": "f902fc5514b044a2", "name": "Senior Consultant"},
                "start_date": "2026-08-01", "end_date": "2026-08-31",
            }]
        def get_hour_types(self):
            return [{"id": "hourstype:f902fc5514b044a2", "label": "Senior Consultant"}]
        def get_booked_hours(self, start, end): return []

    monkeypatch.setattr(sb, "SimplicateClient", LiveClient)
    preview = preview_single_entry(repo, "p", "e1")
    assert preview["payload"]["type_id"] == "hourstype:f902fc5514b044a2"
    assert preview["entry"]["assignment"]["hour_type"]["name"] == "Senior Consultant"


def test_booking_blocks_unknown_hour_type_before_post(monkeypatch, tmp_path):
    _env(monkeypatch)
    repo = PlanRepository(tmp_path)
    plan = new_plan_skeleton(plan_id="p", monday="2026-08-24", sunday="2026-08-30")
    plan["status"] = "IN_REVIEW"
    plan["entries"] = [_entry()]
    repo.create(plan)

    import timesheet_clerk.single_booking as sb

    class BadTypeClient:
        def __init__(self, config): self.config = config
        def get_hour_types(self): return [{"id": "hourstype:other"}]
        def get_booked_hours(self, start, end): return []

    monkeypatch.setattr(sb, "SimplicateClient", BadTypeClient)
    try:
        preview_single_entry(repo, "p", "e1")
    except Exception as exc:
        assert "not a current simplicate hour type" in str(exc).lower()
    else:
        raise AssertionError("unknown hour type must be blocked before POST")
