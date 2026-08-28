from timesheet_clerk.scheduling import reflow_plan_days


def _assignment_entry(eid, source_id, start, assignment_id, description):
    return {
        "entry_id": eid,
        "clockify_source_ids": [source_id],
        "date": "2026-08-28",
        "source": {
            "id": source_id,
            "description": description,
            "client": {"id": "kruit", "name": "Kruitbosch"},
            "project": {"id": "KRUI1057", "name": "Implementatie"},
            "start": start,
            "duration_seconds": 1800,
        },
        "original_duration_seconds": 1800,
        "planned_duration_seconds": 1800,
        "planned_start": start,
        "planned_end": start,
        "booking_mode": "assignment",
        "assignment": {"id": assignment_id, "display_label": assignment_id},
        "direct_mapping": {},
        "tier": "AUTO",
        "overall_tier": "AUTO",
        "ignored": False,
        "billable": True,
        "mapping_state": "RESOLVED",
        "review_state": None,
    }


def _plan(entries):
    return {
        "schema_version": 1,
        "plan_id": "p-v0714",
        "revision": 1,
        "status": "IN_REVIEW",
        "generated_at": "2026-08-28T00:00:00Z",
        "week": {"monday": "2026-08-24", "sunday": "2026-08-30"},
        "contract_hours_default": 36.0,
        "target_hours": 36.0,
        "entries": entries,
    }


def test_auto_rows_same_assignment_consolidate_across_intervening_other_target():
    first = _assignment_entry("k1", "c1", "2026-08-28T10:00:00+02:00", "assignment:kruit", "Overleg Wilmer")
    middle = _assignment_entry("cyclo", "c2", "2026-08-28T10:30:00+02:00", "assignment:cyclo", "Projectmeeting Cyclovriend")
    last = _assignment_entry("k2", "c3", "2026-08-28T11:00:00+02:00", "assignment:kruit", "KRUIT-1194 + KRUIT-1250")
    last["original_duration_seconds"] = last["planned_duration_seconds"] = 3600

    result = reflow_plan_days(_plan([first, middle, last]))
    assert len(result["entries"]) == 2
    kruit = next(row for row in result["entries"] if (row.get("assignment") or {}).get("id") == "assignment:kruit")
    assert kruit["clockify_source_ids"] == ["c1", "c3"]
    assert kruit["planned_duration_seconds"] == 5400
    assert kruit["source"]["description"] == "Overleg Wilmer + KRUIT-1194 + KRUIT-1250"
    assert kruit["planned_start"] == "2026-08-28T09:00:00+02:00"
    assert kruit["planned_end"] == "2026-08-28T10:30:00+02:00"


def test_different_assignment_stays_separate():
    first = _assignment_entry("a", "c1", "2026-08-28T10:00:00+02:00", "assignment:a", "A")
    second = _assignment_entry("b", "c2", "2026-08-28T10:30:00+02:00", "assignment:b", "B")
    assert len(reflow_plan_days(_plan([first, second]))["entries"]) == 2
