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
