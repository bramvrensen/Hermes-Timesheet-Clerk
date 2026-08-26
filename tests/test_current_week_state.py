from timesheet_clerk.state_selection import has_working_week
from timesheet_clerk.storage import PlanRepository


def _plan(plan_id: str, monday: str, sunday: str):
    return {
        "schema_version": 1,
        "plan_id": plan_id,
        "revision": 1,
        "status": "IN_REVIEW",
        "generated_at": "2026-08-26T18:00:00Z",
        "week": {"monday": monday, "sunday": sunday},
        "contract_hours_default": 36.0,
        "target_hours": 36.0,
        "entries": [],
    }


def test_historical_plan_does_not_count_as_current_week(tmp_path):
    repo = PlanRepository(tmp_path)
    repo.create(_plan("wk34", "2026-08-17", "2026-08-23"))

    assert has_working_week(repo, "2026-08-24", "2026-08-30") is False


def test_current_week_is_detected_independent_of_active_pointer(tmp_path):
    repo = PlanRepository(tmp_path)
    repo.create(_plan("wk35", "2026-08-24", "2026-08-30"), make_active=False)
    repo.create(_plan("wk34", "2026-08-17", "2026-08-23"), make_active=True)

    assert repo.get_active()["plan_id"] == "wk34"
    assert has_working_week(repo, "2026-08-24", "2026-08-30") is True
