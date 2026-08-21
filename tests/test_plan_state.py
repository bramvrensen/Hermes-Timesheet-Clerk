from copy import deepcopy

import pytest

from timesheet_clerk.review import apply_review, feedback_event
from timesheet_clerk.storage import PlanRepository, StateConflict


def sample_plan():
    return {
        "schema_version": 1,
        "plan_id": "2026-W34-test",
        "revision": 1,
        "status": "DRAFT",
        "generated_at": "2026-08-22T00:00:00Z",
        "week": {"monday": "2026-08-17", "sunday": "2026-08-23"},
        "contract_hours_default": 36.0,
        "target_hours": 36.0,
        "entries": [
            {
                "entry_id": "a",
                "clockify_source_ids": ["clock-a"],
                "date": "2026-08-22",
                "source": {"description": "Projectmeeting"},
                "original_duration_seconds": 3600,
                "planned_duration_seconds": 3600,
                "planned_start": "2026-08-22T09:00:00+02:00",
                "planned_end": "2026-08-22T10:00:00+02:00",
                "booking_mode": "assignment",
                "assignment": {"id": "assign-a", "display_label": "Client · Project · Task"},
                "tier": "PROPOSE",
            },
            {
                "entry_id": "b",
                "clockify_source_ids": ["clock-b"],
                "date": "2026-08-22",
                "source": {"description": "Design"},
                "original_duration_seconds": 3600,
                "planned_duration_seconds": 3600,
                "planned_start": "2026-08-22T10:00:00+02:00",
                "planned_end": "2026-08-22T11:00:00+02:00",
                "booking_mode": "assignment",
                "assignment": {"id": "assign-b", "display_label": "Client · Project · Task B"},
                "tier": "AUTO",
            },
        ],
    }


def test_repository_is_immutable_by_revision(tmp_path):
    repo = PlanRepository(tmp_path)
    repo.create(sample_plan())
    plan = repo.get_active()
    plan["target_hours"] = 32.0
    saved = repo.save_revision(plan, expected_revision=1)
    assert saved["revision"] == 2
    assert repo.get_revision(plan["plan_id"], 1)["target_hours"] == 36.0
    assert repo.get_active()["target_hours"] == 32.0


def test_revision_conflict_is_rejected(tmp_path):
    repo = PlanRepository(tmp_path)
    repo.create(sample_plan())
    plan = repo.get_active()
    repo.save_revision(plan, expected_revision=1)
    with pytest.raises(StateConflict):
        repo.save_revision(plan, expected_revision=1)


def test_duration_edit_reflows_only_later_same_day():
    plan = sample_plan()
    updated, original, reviewed = apply_review(plan, "a", {"planned_duration_seconds": 5400})
    assert reviewed["planned_end"] == "2026-08-22T10:30:00+02:00"
    assert updated["entries"][1]["planned_start"] == "2026-08-22T10:30:00+02:00"
    event = feedback_event(plan_id=plan["plan_id"], proposal=original, reviewed=reviewed)
    assert event["outcome"] == "corrected"
    assert "planned_duration_seconds" in event["changed_fields"]


def test_approval_requires_review_of_propose(tmp_path):
    repo = PlanRepository(tmp_path)
    repo.create(sample_plan())
    with pytest.raises(StateConflict):
        repo.approve_snapshot("2026-W34-test", 1)

    plan, _, _ = apply_review(repo.get_active(), "a", {})
    saved = repo.save_revision(plan, expected_revision=1)
    snapshot = repo.approve_snapshot(saved["plan_id"], saved["revision"])
    assert snapshot["status"] == "APPROVED"
