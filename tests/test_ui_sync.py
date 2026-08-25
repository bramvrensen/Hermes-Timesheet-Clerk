from timesheet_clerk.storage import PlanRepository
from timesheet_clerk.ui_sync import _delta_counts, _plan_for_week, _planner_prompt_with_delta


def _plan():
    return {
        "schema_version": 1,
        "plan_id": "2026-W35-test",
        "revision": 1,
        "status": "IN_REVIEW",
        "generated_at": "2026-08-24T00:00:00Z",
        "week": {"monday": "2026-08-24", "sunday": "2026-08-30"},
        "contract_hours_default": 36.0,
        "target_hours": 36.0,
        "entries": [],
    }


def test_plan_for_week_finds_mutable_week(tmp_path):
    repo = PlanRepository(tmp_path)
    repo.create(_plan())
    found = _plan_for_week(repo, "2026-08-24", "2026-08-30")
    assert found is not None
    assert found["plan_id"] == "2026-W35-test"


def test_planner_prompt_embeds_exact_delta_and_suppresses_probe():
    prepared = {
        "delta": {
            "new_entries": [{"id": "clock-tue", "description": "Tuesday"}],
            "changed_entries": [],
            "missing_source_ids": [],
        }
    }
    prompt = _planner_prompt_with_delta("FIRST call timesheet_sync_probe", prepared)
    assert "clock-tue" in prompt
    assert "Do NOT call timesheet_sync_probe" in prompt
    assert "superseded" in prompt


def test_delta_counts_is_deterministic():
    assert _delta_counts({"new_count": 2, "changed_count": 1, "missing_count": 3}) == {
        "new_count": 2,
        "changed_count": 1,
        "missing_count": 3,
        "unchanged_count": 0,
    }
