from timesheet_clerk.review import split_consolidated_entry


def test_split_consolidated_entry_uses_canonical_source_snapshots():
    plan={
        "schema_version":1,"plan_id":"p","revision":1,"status":"IN_REVIEW","generated_at":"2026-08-23T00:00:00Z",
        "week":{"monday":"2026-08-17","sunday":"2026-08-23"},"contract_hours_default":36.0,"target_hours":36.0,
        "clockify_source_snapshots":{
            "c1":{"id":"c1","description":"Task A","client":{"id":"x","name":"Client"},"project":{"id":"p","name":"Project"},"start":"2026-08-20T08:00:00Z","end":"2026-08-20T09:00:00Z","duration_seconds":3600},
            "c2":{"id":"c2","description":"Task B","client":{"id":"x","name":"Client"},"project":{"id":"p","name":"Project"},"start":"2026-08-20T09:00:00Z","end":"2026-08-20T10:30:00Z","duration_seconds":5400},
        },
        "entries":[{"entry_id":"agg","clockify_source_ids":["c1","c2"],"date":"2026-08-20","source":{"description":"Combined"},"original_duration_seconds":9000,"planned_duration_seconds":9000,"planned_start":"2026-08-20T08:00:00Z","planned_end":"2026-08-20T10:30:00Z","booking_mode":"assignment","assignment":{"id":"a"},"tier":"PROPOSE","review_state":"corrected"}],
    }
    result=split_consolidated_entry(plan,"agg")
    assert [e["clockify_source_ids"] for e in result["entries"]]==[["c1"],["c2"]]
    assert [e["source"]["description"] for e in result["entries"]]==["Task A","Task B"]
    assert [e["planned_duration_seconds"] for e in result["entries"]]==[3600,5400]
    assert all(e.get("review_state") is None for e in result["entries"])
