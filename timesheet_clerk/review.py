"""Deterministic review helpers used by Streamlit."""
from __future__ import annotations
import hashlib, json, uuid
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any
from .contracts import utc_now, validate_plan

_REVIEW_FIELDS=("planned_duration_seconds","planned_start","planned_end","booking_mode","assignment","direct_mapping","ignored")

def source_fingerprint(entry:dict[str,Any])->str:
    payload={"clockify_source_ids":entry.get("clockify_source_ids") or [],"date":entry.get("date"),"source":entry.get("source") or {},"original_duration_seconds":entry.get("original_duration_seconds")}
    encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"));return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

def changed_fields(proposal:dict[str,Any],reviewed:dict[str,Any])->list[str]:return [f for f in _REVIEW_FIELDS if proposal.get(f)!=reviewed.get(f)]

def feedback_event(*,plan_id:str,proposal:dict[str,Any],reviewed:dict[str,Any],reason:str="",outcome:str|None=None)->dict[str,Any]:
    changes=changed_fields(proposal,reviewed);resolved=outcome or ("corrected" if changes else "confirmed")
    if reviewed.get("ignored"):resolved="skipped"
    return {"event_id":str(uuid.uuid4()),"timestamp":utc_now(),"plan_id":plan_id,"entry_id":reviewed["entry_id"],"source_fingerprint":source_fingerprint(proposal),"agent_proposal":_review_projection(proposal),"reviewed_values":_review_projection(reviewed),"changed_fields":changes,"reason":reason.strip(),"original_mapping_source":deepcopy(proposal.get("mapping_source")),"original_tiers":deepcopy(proposal.get("field_tiers") or {"overall":proposal.get("tier") or proposal.get("overall_tier")}),"outcome":resolved}

def _target_complete(entry:dict[str,Any])->bool:
    if entry.get("booking_mode")=="assignment":return bool(str((entry.get("assignment") or {}).get("id") or "").strip())
    mapping=entry.get("direct_mapping") or {}
    return all(str(mapping.get(key) or "").strip() for key in ("project_id","service_id","hour_type_id"))

def apply_review(plan:dict[str,Any],entry_id:str,reviewed_values:dict[str,Any])->tuple[dict[str,Any],dict[str,Any],dict[str,Any]]:
    updated=deepcopy(plan);index=next((i for i,row in enumerate(updated["entries"]) if row.get("entry_id")==entry_id),None)
    if index is None:raise KeyError(entry_id)
    original=deepcopy(updated["entries"][index]);entry=updated["entries"][index];was_skipped=bool(original.get("ignored")) or original.get("review_state")=="skipped"
    for key in _REVIEW_FIELDS:
        if key in reviewed_values:entry[key]=deepcopy(reviewed_values[key])
    changes=changed_fields(original,entry);tier=entry.get("tier") or entry.get("overall_tier")
    if entry.get("ignored"):entry["review_state"]="skipped"
    elif was_skipped and reviewed_values.get("ignored") is False and changes==["ignored"]:entry["review_state"]=None
    elif tier in {"PROPOSE","ASK"} and not _target_complete(entry):entry["review_state"]=None
    else:entry["review_state"]="corrected" if changes else "confirmed"
    updated["status"]="IN_REVIEW"
    if entry.get("planned_duration_seconds")!=original.get("planned_duration_seconds"):_reflow_day(updated["entries"],index)
    return updated,original,deepcopy(entry)

def split_consolidated_entry(plan:dict[str,Any],entry_id:str)->dict[str,Any]:
    """Split an aggregate entry back into immutable Clockify source rows."""
    updated=deepcopy(plan);index=next((i for i,row in enumerate(updated.get("entries") or []) if row.get("entry_id")==entry_id),None)
    if index is None:raise KeyError(entry_id)
    original=updated["entries"][index];source_ids=[str(v) for v in original.get("clockify_source_ids") or [] if v]
    if len(source_ids)<2:raise ValueError("entry is not consolidated")
    snapshots=updated.get("clockify_source_snapshots") or {};missing=[sid for sid in source_ids if sid not in snapshots]
    if missing:raise ValueError(f"cannot split without Clockify source snapshots: {', '.join(missing)}")
    split=[]
    for position,sid in enumerate(source_ids):
        source=deepcopy(snapshots[sid]);row=deepcopy(original);duration=int(source.get("duration_seconds") or 0)
        row["entry_id"]=entry_id if position==0 else f"{entry_id}-split-{sid}";row["clockify_source_ids"]=[sid];row["source"]={k:deepcopy(source.get(k)) for k in ("description","client","project","start","end")};row["date"]=str(source.get("start") or row.get("date") or "")[:10];row["original_duration_seconds"]=duration;row["planned_duration_seconds"]=duration;row["planned_start"]=source.get("start");row["planned_end"]=source.get("end");row["review_state"]=None;row["tier"]="PROPOSE";row["overall_tier"]="PROPOSE";row["split_from_entry_id"]=entry_id;row["source_fingerprint"]=source_fingerprint(row);split.append(row)
    updated["entries"][index:index+1]=split;updated["entries"].sort(key=lambda r:(str(r.get("date") or ""),str(r.get("planned_start") or ""),str(r.get("entry_id") or "")));updated["status"]="IN_REVIEW";return validate_plan(updated)

def _reflow_day(entries:list[dict[str,Any]],changed_index:int)->None:
    changed=entries[changed_index];day=changed.get("date");changed_start=_parse_datetime(changed.get("planned_start"))
    if not day or changed_start is None:return
    duration=float(changed.get("planned_duration_seconds") or 0);changed_end=changed_start+timedelta(seconds=duration);changed["planned_end"]=_format_like(changed_end,changed.get("planned_start"));cursor=changed_end
    for row in entries[changed_index+1:]:
        if row.get("date")!=day:continue
        old_start=_parse_datetime(row.get("planned_start"));old_end=_parse_datetime(row.get("planned_end"))
        if old_start is None:continue
        row_duration=float(row.get("planned_duration_seconds") or 0)
        if row_duration<=0 and old_end is not None:row_duration=max(0.0,(old_end-old_start).total_seconds())
        row["planned_start"]=_format_like(cursor,row.get("planned_start"));cursor=cursor+timedelta(seconds=row_duration);row["planned_end"]=_format_like(cursor,row.get("planned_end") or row.get("planned_start"))

def _review_projection(entry:dict[str,Any])->dict[str,Any]:
    keys=("entry_id",)+_REVIEW_FIELDS;return {k:deepcopy(entry.get(k)) for k in keys if k in entry}
def _parse_datetime(value:Any)->datetime|None:
    if not value:return None
    try:return datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except ValueError:return None
def _format_like(value:datetime,example:Any)->str:
    result=value.isoformat();return result.replace("+00:00","Z") if str(example or "").endswith("Z") else result
