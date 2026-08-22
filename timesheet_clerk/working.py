"""Working-week synchronization for Timesheet Clerk."""
from __future__ import annotations
from copy import deepcopy
from typing import Any
from .contracts import utc_now, validate_plan
from .review import source_fingerprint
from .storage import PlanRepository, _atomic_write_json
from .sync import attach_source_snapshots

_REVIEW_FIELDS=("planned_duration_seconds","planned_start","planned_end","booking_mode","assignment","direct_mapping","ignored","review_state")

def sync_week_plan(repo:PlanRepository,incoming:dict[str,Any])->dict[str,Any]:
    candidate=validate_plan(incoming); monday=str((candidate.get("week") or {}).get("monday") or ""); sunday=str((candidate.get("week") or {}).get("sunday") or "")
    existing=_find_open_week(repo,monday,sunday)
    if existing is None:
        candidate["revision"]=1;candidate["status"]="DRAFT";candidate["source_sync_at"]=utc_now()
        return repo.create(candidate,make_active=True)
    merged=deepcopy(existing);merged["source_sync_at"]=utc_now();merged["generated_at"]=candidate.get("generated_at") or merged.get("generated_at")
    merged["review_context"]=deepcopy(candidate.get("review_context") or merged.get("review_context") or {});merged["target_hours"]=merged.get("target_hours",candidate.get("target_hours"));merged["contract_hours_default"]=candidate.get("contract_hours_default",merged.get("contract_hours_default"))
    old_by_key={_entry_key(r):r for r in merged.get("entries") or []};new_by_key={_entry_key(r):r for r in candidate.get("entries") or []};output=[]
    for key,fresh in new_by_key.items():
        prior=old_by_key.get(key)
        if prior is None:
            row=deepcopy(fresh);row["last_seen_at"]=merged["source_sync_at"];row["source_fingerprint"]=source_fingerprint(row);output.append(row);continue
        row=deepcopy(fresh);row["entry_id"]=prior.get("entry_id") or fresh.get("entry_id");row["last_seen_at"]=merged["source_sync_at"];row["source_fingerprint"]=source_fingerprint(row)
        if prior.get("review_state") in {"confirmed","corrected","skipped"}:
            for field in _REVIEW_FIELDS:
                if field in prior:row[field]=deepcopy(prior[field])
            row["review_preserved_on_sync"]=True
        output.append(row)
    for key,prior in old_by_key.items():
        if key in new_by_key:continue
        row=deepcopy(prior);row["source_missing"]=True;row["source_missing_since"]=merged["source_sync_at"];output.append(row)
    output.sort(key=lambda r:(str(r.get("date") or ""),str(r.get("planned_start") or ""),str(r.get("entry_id") or "")));merged["entries"]=output;merged["status"]=existing.get("status") if existing.get("status") in {"DRAFT","IN_REVIEW"} else "DRAFT"
    # Planner payloads may include canonical raw Clockify rows in review_context.
    # Persist those independently from aggregate booking entries for future probes.
    raw=(candidate.get("review_context") or {}).get("clockify_entries") or candidate.get("clockify_entries") or []
    if raw: merged=attach_source_snapshots(merged,raw)
    elif isinstance(candidate.get("clockify_source_snapshots"),dict): merged["clockify_source_snapshots"]=deepcopy(candidate["clockify_source_snapshots"])
    validated=validate_plan(merged);path=repo._revision_path(validated["plan_id"],int(validated["revision"]));_atomic_write_json(path,validated);repo._write_active_pointer(validated);return deepcopy(validated)

def _find_open_week(repo:PlanRepository,monday:str,sunday:str)->dict[str,Any]|None:
    for summary in repo.list_plans(limit=100):
        week=summary.get("week") or {}
        if str(week.get("monday") or "")!=monday or str(week.get("sunday") or "")!=sunday:continue
        plan=repo.get_latest(summary["plan_id"])
        if plan.get("status") in {"DRAFT","IN_REVIEW"}:return plan
    return None

def _entry_key(entry:dict[str,Any])->str:
    ids=sorted(str(v) for v in (entry.get("clockify_source_ids") or []) if v)
    return "clockify:"+"|".join(ids) if ids else "fingerprint:"+source_fingerprint(entry)
