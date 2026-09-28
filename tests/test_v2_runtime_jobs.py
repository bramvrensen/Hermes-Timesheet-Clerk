from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml

from timesheet_clerk import jobs, orchestration
from timesheet_clerk.bootstrap import bootstrap
from timesheet_clerk.planner_policy import enforce_policy
from timesheet_clerk.runtime import read_config
from timesheet_clerk.storage import PlanRepository, StateConflict

WEEK = {"monday": "2026-08-24", "sunday": "2026-08-30"}
SOURCE = {"id": "c1", "description": "Consulting", "project": {"id": "cp1", "name": "Project"},
          "client": {"id": "cc1", "name": "Customer"}, "start": "2026-08-24T09:00:00+02:00",
          "end": "2026-08-24T10:00:00+02:00", "duration_seconds": 3600}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    root = tmp_path / "state"
    monkeypatch.setenv("TIMESHEET_CLERK_MODE", "standalone")
    monkeypatch.setenv("TIMESHEET_CLERK_STATE_DIR", str(root))
    monkeypatch.setenv("TIMESHEET_CLERK_HERMES_ROOT", str(tmp_path / "private-hermes"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "atlas"))
    class EmptyClient:
        def __init__(self, config): pass
        def get_context(self, start, end): return {}
    monkeypatch.setattr(orchestration, "SimplicateClient", EmptyClient)
    monkeypatch.setattr(jobs, "live_sources", lambda *args: deepcopy([SOURCE]))
    return root


def test_private_profile_does_not_touch_atlas_and_preserves_user_instructions(isolated, tmp_path):
    isolated.mkdir()
    (isolated / "SKILL.md").write_text("My own Timesheet Clerk policy\n")
    home = bootstrap()
    cfg = yaml.safe_load((home / "config.yaml").read_text())
    assert home == tmp_path / "private-hermes/profiles/timesheet-clerk"
    assert not (tmp_path / "atlas").exists()
    assert cfg["plugins"]["enabled"] == ["timesheet-clerk-planner"]
    assert cfg["platform_toolsets"]["cli"] == ["timesheet_clerk_planner"]
    assert (home / ".no-bundled-skills").exists()
    assert (home / "plugins/timesheet-clerk-planner").is_symlink()
    assert read_config()["planner_profile"] == "timesheet-clerk"
    bootstrap()
    assert "My own Timesheet Clerk policy" in (isolated / "SKILL.md").read_text()


def test_manual_import_and_unchanged_refresh_never_call_model(isolated, monkeypatch):
    monkeypatch.setattr(jobs, "_mapping_decisions", lambda *args: pytest.fail("Unexpected model call"))
    job = {"week": WEEK, "rebuild": False, "manual": True}
    jobs.generate(isolated, "a" * 32, job)
    repo = PlanRepository(isolated)
    plan = repo.get_active()
    entry = plan["entries"][0]
    assert entry["tier"] == "ASK"
    assert entry["source"]["description"] == SOURCE["description"]
    # Review provides a complete target; the following unchanged sync is a no-op.
    entry.update(booking_mode="direct", mapping_state="RESOLVED", review_state="corrected",
                 direct_mapping={"project_id": "p", "service_id": "s", "hour_type_id": "h"})
    repo.save_revision(plan, expected_revision=plan["revision"])
    before = repo.get_active()["revision"]
    result = jobs.generate(isolated, "b" * 32, {**job, "manual": False})
    assert result["no_op"] is True
    assert repo.get_active()["revision"] == before


def test_clockify_change_during_generation_preserves_existing_state(isolated, monkeypatch):
    original = deepcopy(SOURCE)
    changed = {**original, "description": "Changed while mapping"}
    reads = iter([[original], [changed]])
    monkeypatch.setattr(jobs, "live_sources", lambda *args: next(reads))
    with pytest.raises(StateConflict, match="Clockify changed"):
        jobs.generate(isolated, "c" * 32, {"week": WEEK, "rebuild": False, "manual": True})
    assert PlanRepository(isolated).list_plans() == []


def test_concurrent_review_is_not_overwritten(isolated, monkeypatch):
    repo = PlanRepository(isolated)
    initial = jobs.generate(isolated, "d" * 32, {"week": WEEK, "rebuild": False, "manual": True})
    def decisions(*args):
        plan = repo.get_active()
        plan["notes"] = "Human changed this while the model was running"
        repo.save_revision(plan, expected_revision=plan["revision"])
        return [{"source_id": "c1", "tier": "ASK", "booking_mode": "direct"}]
    monkeypatch.setattr(jobs, "_mapping_decisions", decisions)
    with pytest.raises(StateConflict, match="edited during generation"):
        jobs.generate(isolated, "e" * 32, {"week": WEEK, "rebuild": False, "manual": False})
    assert repo.get_active()["notes"].startswith("Human changed")


def test_job_recovery_is_terminal_and_does_not_change_plan(isolated):
    run_id = "f" * 32
    jobs.write_status(isolated, {"run_id": run_id, "status": "RUNNING", "pid": 999999})
    jobs.recover_jobs(isolated)
    assert jobs.read_job(isolated, run_id)["status"] == "FAILED"
    assert json.loads((isolated / "planner-sync-status.json").read_text())["status"] == "FAILED"
    assert PlanRepository(isolated).list_plans() == []


def test_second_generation_cannot_acquire_running_job_lease(isolated):
    import fcntl
    isolated.mkdir()
    with (isolated / ".planner.lock").open("a") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(StateConflict, match="already running"):
            jobs.launch_job(isolated, **WEEK)


@pytest.mark.parametrize("confidence,expected", [(0.95, "PROPOSE"), (0.8, "PROPOSE"), (0.4, "ASK"), (float("nan"), "ASK")])
def test_numeric_policy_and_evidence_override_model_claims(confidence, expected):
    row = {"source_id": "c", "tier": "AUTO", "confidence": confidence}
    result = enforce_policy([row], {})[0]
    assert result["tier"] == expected
    assert row["tier"] == "AUTO"


def test_jobs_require_a_complete_calendar_week():
    with pytest.raises(ValueError, match="complete"):
        jobs.validate_week("2026-08-24", "2026-09-06")
