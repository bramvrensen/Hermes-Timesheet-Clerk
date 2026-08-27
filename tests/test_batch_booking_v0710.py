from timesheet_clerk.contracts import new_plan_skeleton
from timesheet_clerk.single_booking import execute_entry_batch, preview_entry_batch
from timesheet_clerk.storage import PlanRepository


def _entry(entry_id, hour, review_state="corrected"):
    return {"entry_id":entry_id,"clockify_source_ids":[entry_id],"date":"2026-08-24","source":{"description":entry_id},"original_duration_seconds":3600,"planned_duration_seconds":3600,"planned_start":f"2026-08-24T{hour:02d}:00:00+02:00","planned_end":f"2026-08-24T{hour+1:02d}:00:00+02:00","tier":"PROPOSE","overall_tier":"PROPOSE","review_state":review_state,"mapping_state":"RESOLVED","booking_mode":"direct","ignored":False,"direct_mapping":{"project_id":"p1","service_id":"s1","hour_type_id":"h1","billable":True}}


def _env(monkeypatch):
    monkeypatch.setenv("SIMPLICATE_BASE_URL","https://example.invalid/api/v2"); monkeypatch.setenv("SIMPLICATE_API_KEY","k"); monkeypatch.setenv("SIMPLICATE_API_SECRET","s"); monkeypatch.setenv("SIMPLICATE_EMPLOYEE_ID","emp1")


def test_batch_preflight_reads_simplicate_once(monkeypatch,tmp_path):
    _env(monkeypatch); repo=PlanRepository(tmp_path); plan=new_plan_skeleton(plan_id="p",monday="2026-08-24",sunday="2026-08-30"); plan["status"]="IN_REVIEW"; plan["entries"]=[_entry("e1",9),_entry("e2",10)]; repo.create(plan)
    import timesheet_clerk.single_booking as sb
    calls={"reads":0}
    class Client:
        def __init__(self,config): self.config=config
        def get_booked_hours(self,start,end): calls["reads"]+=1; return []
    monkeypatch.setattr(sb,"SimplicateClient",Client)
    preview=preview_entry_batch(repo,"p",["e1","e2"])
    assert preview["ready_count"]==2
    assert calls["reads"]==1


def test_batch_continues_after_rejected_row(monkeypatch,tmp_path):
    _env(monkeypatch); repo=PlanRepository(tmp_path); plan=new_plan_skeleton(plan_id="p",monday="2026-08-24",sunday="2026-08-30"); plan["status"]="IN_REVIEW"; plan["entries"]=[_entry("e1",9),_entry("e2",10)]; repo.create(plan)
    import timesheet_clerk.single_booking as sb
    posted=[]
    class Client:
        def __init__(self,config): self.config=config
        def get_booked_hours(self,start,end):
            return [{"id":"hours:2","project":{"id":"project:p1"},"projectservice":{"id":"service:s1"},"type":{"id":"hourstype:h1"},"start_date":"2026-08-24 10:00:00","hours":1.0}] if posted else []
    monkeypatch.setattr(sb,"SimplicateClient",Client)
    preview=preview_entry_batch(repo,"p",["e1","e2"])
    def post(config,payload):
        if payload["start_date"].endswith("09:00:00"): raise RuntimeError("rejected")
        posted.append(payload); return {"id":"hours:2"}
    monkeypatch.setattr(sb,"_post_hours",post)
    result=execute_entry_batch(repo,"p",preview)
    assert result["failed_count"]==1
    assert result["booked_count"]==1
    latest=repo.get_latest("p")
    states={e["entry_id"]:e.get("reconciliation_state") for e in latest["entries"]}
    assert states["e1"] != "BOOKED"
    assert states["e2"] == "BOOKED"
