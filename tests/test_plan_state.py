from copy import deepcopy

import pytest

from timesheet_clerk.review import apply_review, feedback_event
from timesheet_clerk.storage import PlanRepository, StateConflict
from timesheet_clerk.working import sync_week_plan


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


def test_partial_edit_keeps_incomplete_direct_entry_unresolved():
    plan = sample_plan()
    entry = plan["entries"][0]
    entry["booking_mode"] = "direct"
    entry["assignment"] = {}
    entry["direct_mapping"] = {"customer_id": "customer-only"}
    updated, _, reviewed = apply_review(plan, "a", {"planned_duration_seconds": 1800})
    assert reviewed.get("review_state") is None
    repo_plan = deepcopy(updated)
    from timesheet_clerk.contracts import validate_plan
    validate_plan(repo_plan)


def test_restore_skipped_incomplete_entry_reopens_review():
    plan = sample_plan()
    entry = plan["entries"][0]
    entry["booking_mode"] = "direct"
    entry["assignment"] = {}
    entry["direct_mapping"] = {}
    entry["ignored"] = True
    entry["review_state"] = "skipped"
    _, _, reviewed = apply_review(plan, "a", {"ignored": False})
    assert reviewed.get("review_state") is None


def test_working_revision_history_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("TIMESHEET_CLERK_REVISION_RETENTION", "3")
    repo = PlanRepository(tmp_path)
    repo.create(sample_plan())
    for expected in range(1, 6):
        plan = repo.get_active()
        plan["target_hours"] = 36.0 + expected
        repo.save_revision(plan, expected_revision=expected)
    paths = repo._revision_paths("2026-W34-test")
    assert len(paths) == 3
    assert paths[-1].name == "revision-0006.json"


def test_approval_requires_review_of_propose(tmp_path):
    repo = PlanRepository(tmp_path)
    repo.create(sample_plan())
    with pytest.raises(StateConflict):
        repo.approve_snapshot("2026-W34-test", 1)

    plan, _, _ = apply_review(repo.get_active(), "a", {})
    saved = repo.save_revision(plan, expected_revision=1)
    snapshot = repo.approve_snapshot(saved["plan_id"], saved["revision"])
    assert snapshot["status"] == "APPROVED"


def test_approved_snapshot_does_not_close_working_week_for_later_clockify_delta(tmp_path):
    """Monday approval stays immutable while a Tuesday delta extends the working plan."""
    repo = PlanRepository(tmp_path)
    monday = sample_plan()
    monday["entries"] = [deepcopy(monday["entries"][0])]
    monday["entries"][0]["date"] = "2026-08-17"
    monday["entries"][0]["planned_start"] = "2026-08-17T09:00:00+02:00"
    monday["entries"][0]["planned_end"] = "2026-08-17T10:00:00+02:00"
    repo.create(monday)

    reviewed, _, _ = apply_review(repo.get_active(), "a", {})
    reviewed["entries"][0]["planned_duration_seconds"] = 5400
    reviewed["entries"][0]["review_state"] = "corrected"
    saved = repo.save_revision(reviewed, expected_revision=1)
    approval = repo.approve_snapshot(saved["plan_id"], saved["revision"])

    # The planner gets only Tuesday's source delta, not the full Monday+Tuesday week.
    delta = deepcopy(monday)
    delta["revision"] = 1
    delta["entries"] = [{
        "entry_id": "tuesday-new",
        "clockify_source_ids": ["clock-tuesday"],
        "date": "2026-08-18",
        "source": {"description": "Tuesday work"},
        "original_duration_seconds": 7200,
        "planned_duration_seconds": 7200,
        "planned_start": "2026-08-18T09:00:00+02:00",
        "planned_end": "2026-08-18T11:00:00+02:00",
        "booking_mode": "assignment",
        "assignment": {"id": "assign-tuesday", "display_label": "Client · Tuesday"},
        "tier": "AUTO",
    }]

    synced = sync_week_plan(repo, delta)
    assert synced["revision"] == saved["revision"] + 1
    assert synced["status"] == "IN_REVIEW"
    assert {row["entry_id"] for row in synced["entries"]} == {"a", "tuesday-new"}
    preserved = next(row for row in synced["entries"] if row["entry_id"] == "a")
    assert preserved["planned_duration_seconds"] == 5400
    assert preserved["review_state"] == "corrected"
    assert not preserved.get("source_missing")

    # Approval is a separate immutable snapshot and must still contain Monday only.
    assert approval["status"] == "APPROVED"
    assert len(approval["entries"]) == 1
    assert approval["entries"][0]["planned_duration_seconds"] == 5400
