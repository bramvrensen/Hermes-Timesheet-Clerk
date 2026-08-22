"""UI-facing review context built from the shared Simplicate integration layer."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any
from .config import SimplicateConfig
from .simplicate import SimplicateClient

_REQUIRED=("SIMPLICATE_BASE_URL","SIMPLICATE_API_KEY","SIMPLICATE_API_SECRET","SIMPLICATE_EMPLOYEE_ID")

def _load_atlas_profile_env() -> None:
    if all(str(os.environ.get(key) or "").strip() for key in _REQUIRED): return
    profile_env=Path(os.environ.get("HERMES_PROFILE_ENV") or "/home/hermes/.hermes/profiles/atlas/.env")
    if not profile_env.is_file(): return
    for raw in profile_env.read_text(encoding="utf-8").splitlines():
        line=raw.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        key,value=line.split("=",1); key=key.strip()
        if key not in _REQUIRED or os.environ.get(key): continue
        value=value.strip()
        if len(value)>=2 and value[0]==value[-1] and value[0] in {"'",'"'}: value=value[1:-1]
        os.environ[key]=value

def load_review_context(start_date:str,end_date:str)->dict[str,list[dict[str,Any]]]:
    _load_atlas_profile_env(); client=SimplicateClient(SimplicateConfig.from_env())
    projects=[_normalize_project(r) for r in client.get_projects() if isinstance(r,dict)]; projects=[r for r in projects if r.get("id")]
    services=[_normalize_service(r) for r in client.get_services() if isinstance(r,dict)]; services=[r for r in services if r.get("id")]
    hour_types=[_normalize_hour_type(r) for r in client.get_hour_types() if isinstance(r,dict)]; hour_types=[r for r in hour_types if r.get("id")]
    hour_type_names={r["id"]:r.get("name") for r in hour_types if r.get("id") and r.get("name")}
    assignments=client.get_booking_assignments(start_date,end_date)
    customers={}
    for p in projects:
        if p.get("customer_id"): customers.setdefault(p["customer_id"],{"id":p["customer_id"],"name":p.get("customer_name") or p["customer_id"]})
    # Prefer tenant-validated assignment relations. The global hour-type endpoint does
    # not reliably expose service relations, so services without any scoped relation
    # receive the active global hour-type list as a manual-review fallback instead of
    # an unusable empty selector. This fallback is review-only evidence, never AUTO.
    scoped=[]; seen=set(); services_with_scoped_types=set()
    for a in assignments:
        task=a.get("task") or {}; ht=a.get("hour_type") or {}; sid=_plain_id(_nested_id(task)); hid=_plain_id(_nested_id(ht))
        if not sid or not hid: continue
        key=(sid,hid)
        if key in seen: continue
        seen.add(key); services_with_scoped_types.add(sid)
        scoped.append({"id":hid,"name":_nested_name(ht) or hour_type_names.get(hid) or hid,"service_id":sid,"source":"assignment"})
    for ht in hour_types:
        sid=ht.get("service_id")
        if sid and (sid,ht["id"]) not in seen:
            scoped.append(ht); seen.add((sid,ht["id"])); services_with_scoped_types.add(sid)
    global_types=[ht for ht in hour_types if not ht.get("service_id")]
    for service in services:
        sid=service["id"]
        if sid in services_with_scoped_types: continue
        for ht in global_types:
            key=(sid,ht["id"])
            if key in seen: continue
            seen.add(key)
            scoped.append({"id":ht["id"],"name":ht.get("name") or ht["id"],"service_id":sid,"source":"global_fallback"})
    return {"customers":sorted(customers.values(),key=lambda r:_sort_name(r.get("name"))),"projects":sorted(projects,key=lambda r:(_sort_name(r.get("customer_name")),_sort_name(r.get("name")))),"services":sorted(services,key=lambda r:_sort_name(r.get("name"))),"hour_types":sorted(scoped,key=lambda r:(_sort_name(r.get("service_id")),_sort_name(r.get("name")))),"booking_assignments":sorted(assignments,key=lambda r:_sort_name(r.get("display_label") or r.get("name")))}

def _normalize_project(row):
    organization=row.get("organization") or row.get("customer") or {}
    return {"id":_plain_id(row.get("id")),"name":row.get("name") or row.get("title") or row.get("project_name"),"number":row.get("project_number") or row.get("number"),"customer_id":_plain_id(_nested_id(organization) or row.get("organization_id") or row.get("customer_id")),"customer_name":_nested_name(organization) or row.get("organization_name") or row.get("customer_name")}

def _normalize_service(row):
    project=row.get("project") or {}
    return {"id":_plain_id(row.get("id")),"name":row.get("name") or row.get("title") or row.get("service_name"),"project_id":_plain_id(_nested_id(project) or row.get("project_id")),"use_in_resource_planner":row.get("use_in_resource_planner")}

def _normalize_hour_type(row):
    service=row.get("projectservice") or row.get("service") or {}
    return {"id":_plain_id(row.get("id")),"name":row.get("name") or row.get("title") or row.get("label"),"service_id":_plain_id(_nested_id(service) or row.get("projectservice_id") or row.get("service_id")),"source":"masterdata"}

def _nested_id(value): return value.get("id") if isinstance(value,dict) else value
def _nested_name(value): return (value.get("name") or value.get("title") or value.get("label")) if isinstance(value,dict) else None
def _plain_id(value):
    if value is None:return ""
    text=str(value); return text.split(":",1)[1] if ":" in text else text
def _sort_name(value): return str(value or "").casefold()
