from copy import deepcopy

from timesheet_clerk.review import apply_review
from timesheet_clerk.storage import PlanRepository
from timesheet_clerk.ui_batch_booking import _bookable_ids


def _plan():
    return {
        "schema_version": 1,
        "plan_id": "p",
        "revision": 1,
        "status": "DRAFT",
        "generated_at": "2026-08-28T00:00:00Z",
        "week": {"monday": "2026-08-24", "sunday": "2026-08-30"},
        "contract_hours_default": 36.0,
        "target_hours": 36.0,
        "entries": [{
            "entry_id": "e1",
            "clockify_source_ids": ["c1"],
            "date": "2026-08-24",
            "source": {"description": "Needs review"},
            "original_duration_seconds": 3600,
            "planned_duration_seconds": 3600,
            "planned_start": "2026-08-24T09:00:00+02:00",
            "planned_end": "2026-08-24T10:00:00+02:00",
            "booking_mode": "assignment",
            "assignment": {"id": "a1", "project": {"id": "p1"}, "task": {"id": "s1"}, "hour_type": {"id": "h1"}},
            "tier": "PROPOSE",
        }],
    }


def test_approval_same_revision_is_idempotent(tmp_path):
    repo = PlanRepository(tmp_path)
    repo.create(_plan())
    reviewed, _, _ = apply_review(repo.get_active(), "e1", {})
    saved = repo.save_revision(reviewed, expected_revision=1)
    first = repo.approve_snapshot("p", saved["revision"])
    second = repo.approve_snapshot("p", saved["revision"])
    assert second == first
    assert second["approved_at"] == first["approved_at"]


def test_bookable_ids_exposes_human_reason(monkeypatch):
    import timesheet_clerk.ui_batch_booking as batch
    monkeypatch.setattr(batch, "task_booking_ready", lambda entry: (False, "Review this entry before booking."))
    ready, blocked = _bookable_ids([{"entry_id": "e1", "source": {"description": "Workshop"}}])
    assert ready == []
    assert blocked == [{"entry_id": "e1", "description": "Workshop", "reason": "Review this entry before booking."}]
