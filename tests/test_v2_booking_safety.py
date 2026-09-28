import pytest

from timesheet_clerk.booking_attempts import guarded_post
from timesheet_clerk.http import IntegrationError
from timesheet_clerk.single_booking import execute_single_entry_booking
from timesheet_clerk.storage import PlanRepository, StateConflict


def test_standalone_write_switch_blocks_booking_before_network(tmp_path, monkeypatch):
    monkeypatch.setenv("TIMESHEET_CLERK_MODE", "standalone")
    monkeypatch.setenv("TIMESHEET_CLERK_SIMPLICATE_WRITE_ENABLED", "false")
    with pytest.raises(StateConflict, match="disabled"):
        execute_single_entry_booking(PlanRepository(tmp_path), "p", "e")


def test_uncertain_post_cannot_be_automatically_retried_after_restart(tmp_path):
    repo = PlanRepository(tmp_path)
    def timeout():
        raise IntegrationError("network_error", "Timeout", retryable=True)
    with pytest.raises(IntegrationError):
        guarded_post(repo, "p", "e", {"hours": 1}, timeout)
    restarted = PlanRepository(tmp_path)
    with pytest.raises(StateConflict, match="earlier"):
        guarded_post(restarted, "p", "e", {"hours": 1}, lambda: pytest.fail("Duplicate POST"))
    assert len(list((tmp_path / "booking_attempts").glob("*.json"))) == 1


def test_explicit_validation_rejection_can_be_corrected_and_retried(tmp_path):
    repo = PlanRepository(tmp_path)
    def reject():
        raise IntegrationError("validation_error", "Invalid hour type", status_code=422)
    with pytest.raises(IntegrationError):
        guarded_post(repo, "p", "e", {"hours": 1}, reject)
    result = guarded_post(repo, "p", "e", {"hours": 1, "type_id": "corrected"}, lambda: {"id": "hours:1"})
    assert result["id"] == "hours:1"


def test_rebuilt_plan_does_not_bypass_uncertain_source_attempt(tmp_path):
    repo = PlanRepository(tmp_path)
    def timeout():
        raise IntegrationError("network_error", "Timeout", retryable=True)
    with pytest.raises(IntegrationError):
        guarded_post(repo, "old-plan", "old-entry", {"hours": 1}, timeout, source_ids=["clockify-1"])
    with pytest.raises(StateConflict, match="Clockify sources"):
        guarded_post(repo, "rebuilt-plan", "new-entry", {"hours": 1}, lambda: pytest.fail("Duplicate POST"), source_ids=["clockify-1"])


def test_receipts_from_previous_plan_block_the_same_clockify_source(tmp_path, monkeypatch):
    import timesheet_clerk.single_booking as booking
    from timesheet_clerk.contracts import new_plan_skeleton
    monkeypatch.setenv("TIMESHEET_CLERK_MODE", "standalone")
    monkeypatch.setenv("TIMESHEET_CLERK_SIMPLICATE_WRITE_ENABLED", "true")
    for key, value in {"SIMPLICATE_BASE_URL": "https://example.invalid/api/v2", "SIMPLICATE_API_KEY": "test-key", "SIMPLICATE_API_SECRET": "test-secret", "SIMPLICATE_EMPLOYEE_ID": "employee"}.items():
        monkeypatch.setenv(key, value)
    repo = PlanRepository(tmp_path)
    repo.write_receipt({"plan_id": "old-plan", "entry_id": "old-entry", "timestamp": "2026-08-24T12:00:00Z", "clockify_source_ids": ["clockify-1", "clockify-2"]})
    plan = new_plan_skeleton(plan_id="rebuilt-plan", monday="2026-08-24", sunday="2026-08-30")
    plan["entries"] = [{"entry_id": "new-entry", "clockify_source_ids": ["clockify-1"], "date": "2026-08-24",
                        "source": {"description": "Same source, rebuilt with a different planned time"},
                        "original_duration_seconds": 3600, "planned_duration_seconds": 3600,
                        "planned_start": "2026-08-24T11:00:00+02:00", "planned_end": "2026-08-24T12:00:00+02:00",
                        "tier": "AUTO", "booking_mode": "direct", "ignored": False,
                        "direct_mapping": {"project_id": "p1", "service_id": "s1", "hour_type_id": "h1"}}]
    repo.create(plan)
    class NoExistingHours:
        def __init__(self, config): self.config = config
        def get_booked_hours(self, *args): return []
    monkeypatch.setattr(booking, "SimplicateClient", NoExistingHours)
    monkeypatch.setattr(booking, "_post_hours", lambda *args: pytest.fail("Duplicate POST"))
    assert booking.preview_single_entry(repo, "rebuilt-plan", "new-entry")["status"] == "already_booked"
    with pytest.raises(StateConflict, match="already"):
        execute_single_entry_booking(repo, "rebuilt-plan", "new-entry")
