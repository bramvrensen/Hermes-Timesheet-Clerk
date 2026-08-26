from copy import deepcopy

import pytest

import timesheet_clerk.orchestration as orchestration
from timesheet_clerk.storage import PlanRepository, StateConflict


def source(source_id="c1", description="Work", start="2026-08-24T09:00:00+02:00", duration=3600):
    hour = 10 if duration == 3600 else 11
    return {
        "id": source_id,
        "description": description,
        "client": {"id": "client-1", "name": "Client"},
        "project": {"id": "project-clockify", "name": "Clockify Project"},
        "tags": [],
        "start": start,
        "end": f"2026-08-24T{hour:02d}:00:00+02:00",
        "duration_seconds": duration,
    }


def direct_decision(source_id="c1", tier="AUTO"):
    return {
        "source_id": source_id,
        "tier": tier,
        "booking_mode": "direct",
        "direct_mapping": {
            "project_id": "sp1",
            "project_name": "Simplicate Project",
            "service_id": "svc1",
            "service_name": "Consulting",
            "hour_type_id": "ht1",
            "hour_type_name": "Senior Consultant",
            "billable": True,
        },
        "why": "deterministic test mapping",
        "confidence": 0.99,
    }


def _cfg():
    return {"contract_hours_default": 36.0}


def test_create_is_built_from_decisions_not_plan_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestration, "read_config", _cfg)
    repo = PlanRepository(tmp_path)
    work = orchestration.prepare_mapping_work(repo, [source()], monday="2026-08-24", sunday="2026-08-30")
    assert work["mode"] == "CREATE"
    assert work["work_count"] == 1

    result = orchestration.apply_mapping_decisions(
        repo, [source()], monday="2026-08-24", sunday="2026-08-30", decisions=[direct_decision()]
    )
    plan = result["plan"]
    assert plan["week"] == {"monday": "2026-08-24", "sunday": "2026-08-30"}
    assert plan["entries"][0]["source"]["description"] == "Work"
    assert plan["entries"][0]["original_duration_seconds"] == 3600
    assert plan["clockify_source_snapshots"]["c1"]["description"] == "Work"


def test_changed_clockify_text_is_refreshed_by_python(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestration, "read_config", _cfg)
    repo = PlanRepository(tmp_path)
    orchestration.apply_mapping_decisions(
        repo, [source(description="Old")], monday="2026-08-24", sunday="2026-08-30", decisions=[direct_decision()]
    )
    changed = [source(description="New text")]
    work = orchestration.prepare_mapping_work(repo, changed, monday="2026-08-24", sunday="2026-08-30")
    assert work["source_delta"]["changed_count"] == 1
    assert work["work_items"][0]["source"]["description"] == "New text"

    result = orchestration.apply_mapping_decisions(
        repo, changed, monday="2026-08-24", sunday="2026-08-30", decisions=[direct_decision()]
    )
    assert result["plan"]["entries"][0]["source"]["description"] == "New text"


def test_incremental_refresh_preserves_human_reviewed_mapping(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestration, "read_config", _cfg)
    repo = PlanRepository(tmp_path)
    created = orchestration.apply_mapping_decisions(
        repo, [source(description="Old")], monday="2026-08-24", sunday="2026-08-30", decisions=[direct_decision()]
    )["plan"]
    reviewed = deepcopy(created)
    reviewed["entries"][0]["review_state"] = "corrected"
    reviewed["entries"][0]["direct_mapping"]["project_id"] = "human-project"
    reviewed["status"] = "IN_REVIEW"
    repo.save_revision(reviewed, expected_revision=1)

    changed = [source(description="Changed source")]
    decision = direct_decision(); decision["direct_mapping"]["project_id"] = "agent-project"
    result = orchestration.apply_mapping_decisions(
        repo, changed, monday="2026-08-24", sunday="2026-08-30", decisions=[decision]
    )
    entry = result["plan"]["entries"][0]
    assert entry["source"]["description"] == "Changed source"
    assert entry["direct_mapping"]["project_id"] == "human-project"
    assert entry["review_state"] == "corrected"
    assert entry["review_preserved_on_sync"] is True


def test_safe_rebuild_does_not_delete_old_plan_before_replacement(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestration, "read_config", _cfg)
    repo = PlanRepository(tmp_path)
    old = orchestration.apply_mapping_decisions(
        repo, [source()], monday="2026-08-24", sunday="2026-08-30", decisions=[direct_decision()]
    )["plan"]

    with pytest.raises(StateConflict, match="omitted"):
        orchestration.apply_mapping_decisions(
            repo, [source(), source("c2", "Second", "2026-08-24T11:00:00+02:00")],
            monday="2026-08-24", sunday="2026-08-30", decisions=[direct_decision()], rebuild=True,
        )
    assert repo.get_latest(old["plan_id"])["plan_id"] == old["plan_id"]
    assert repo.get_active()["plan_id"] == old["plan_id"]

    decisions = [direct_decision("c1"), direct_decision("c2")]
    rebuilt = orchestration.apply_mapping_decisions(
        repo, [source(), source("c2", "Second", "2026-08-24T11:00:00+02:00")],
        monday="2026-08-24", sunday="2026-08-30", decisions=decisions, rebuild=True,
    )["plan"]
    assert rebuilt["plan_id"] != old["plan_id"]
    assert repo.get_latest(old["plan_id"])["plan_id"] == old["plan_id"]
    assert repo.get_active()["plan_id"] == rebuilt["plan_id"]
