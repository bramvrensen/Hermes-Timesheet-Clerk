from copy import deepcopy

from timesheet_clerk.sync_payload import normalize_incremental_plan


def existing_plan():
    return {
        "schema_version": 1,
        "plan_id": "plan-wk35",
        "revision": 7,
        "status": "IN_REVIEW",
        "generated_at": "2026-08-26T12:00:00Z",
        "week": {"monday": "2026-08-24", "sunday": "2026-08-30"},
        "contract_hours_default": 36.0,
        "target_hours": 36.0,
        "entries": [{"entry_id": "old"}],
    }


def test_incremental_sync_repairs_blank_week_from_stored_plan():
    incoming = {
        "plan_id": "plan-wk35",
        "week": {"monday": "", "sunday": ""},
        "entries": [{"entry_id": "changed"}],
    }

    normalized = normalize_incremental_plan(existing_plan(), incoming)

    assert normalized["week"] == {"monday": "2026-08-24", "sunday": "2026-08-30"}
    assert normalized["schema_version"] == 1
    assert normalized["revision"] == 7
    assert normalized["status"] == "IN_REVIEW"
    assert normalized["target_hours"] == 36.0
    assert normalized["entries"] == [{"entry_id": "changed"}]


def test_incremental_sync_preserves_valid_structural_values_and_delta_entries():
    existing = existing_plan()
    incoming = deepcopy(existing)
    incoming["entries"] = [{"entry_id": "changed"}]

    normalized = normalize_incremental_plan(existing, incoming)

    assert normalized["week"] == incoming["week"]
    assert normalized["entries"] == [{"entry_id": "changed"}]
