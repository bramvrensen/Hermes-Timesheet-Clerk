import json

import pytest

from timesheet_clerk.fresh_start import fresh_start_week
from timesheet_clerk.storage import PlanRepository, StateConflict


def _plan(plan_id: str, status: str = "IN_REVIEW"):
    return {
        "plan_id": plan_id,
        "revision": 1,
        "status": status,
        "week": {"monday": "2026-08-24", "sunday": "2026-08-30"},
        "target_hours": 36.0,
        "contract_hours_default": 36.0,
        "generated_at": "2026-08-26T12:00:00+00:00",
        "updated_at": "2026-08-26T12:00:00+00:00",
        "entries": [],
    }


def test_fresh_start_removes_only_mutable_week_and_clears_active(tmp_path):
    repo = PlanRepository(tmp_path)
    repo.create(_plan("week-a"), make_active=True)
    other = _plan("week-b")
    other["week"] = {"monday": "2026-08-17", "sunday": "2026-08-23"}
    repo.create(other, make_active=False)

    result = fresh_start_week(repo, monday="2026-08-24", sunday="2026-08-30")

    assert result["removed_plan_ids"] == ["week-a"]
    assert result["fresh_start_required"] is True
    assert "timesheet_plan_create" in result["next_step"]
    assert not repo.active_file.exists()
    assert not (repo.plans_dir / "week-a").exists()
    assert (repo.plans_dir / "week-b").exists()


def test_fresh_start_refuses_non_working_week(tmp_path):
    repo = PlanRepository(tmp_path)
    plan = _plan("approved", status="APPROVED")
    # write directly because repository creation accepts a valid immutable status
    repo.create(plan, make_active=True)

    with pytest.raises(StateConflict, match="fresh start refused"):
        fresh_start_week(repo, monday="2026-08-24", sunday="2026-08-30")
