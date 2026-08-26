"""Timesheet Clerk Streamlit UI."""
from __future__ import annotations

import html
import json
import sys
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components
from streamlit_cookies_controller import CookieController

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timesheet_clerk.review import apply_review, feedback_event, split_consolidated_entry
from timesheet_clerk.runtime import read_config
from timesheet_clerk.storage import PlanNotFound, PlanRepository, StateConflict
from timesheet_clerk.ui_admin import render_config, render_skill, render_state
from timesheet_clerk.ui_auth import logout, require_login
from timesheet_clerk.ui_context import load_review_context
from timesheet_clerk.ui_sync import clear_sync_status, launch_sync, sync_status

st.set_page_config(page_title="Timesheet Clerk", page_icon="⏱️", layout="wide")
repo = PlanRepository()
repo.compact_all_working_revisions(keep=2)
DEFAULT_SKILL = ROOT / "skills" / "productivity" / "timesheet-clerk" / "SKILL.md"
_THEME_COOKIE = "timesheet_clerk_theme"
_THEME_CONTROLLER = CookieController(key="timesheet-clerk-theme-cookies")


def _hours(seconds: Any) -> float:
    try: return float(seconds or 0) / 3600.0
    except (TypeError, ValueError): return 0.0


def _plain_id(value: Any) -> str:
    if isinstance(value, dict): value = value.get("id")
    text = str(value or "")
    return text.split(":", 1)[1] if ":" in text else text


def _name(row: dict[str, Any] | None) -> str:
    row = row or {}
    return str(row.get("name") or row.get("title") or row.get("label") or row.get("id") or "")


def _format_hm(value: Any) -> str:
    if not value: return "--:--"
    text = str(value)
    try: return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%H:%M")
    except ValueError: return text.split("T", 1)[-1][:5] if "T" in text else text[:5]


def _entry_label(entry: dict[str, Any]) -> str:
    source = entry.get("source") or {}
    desc = source.get("description") or entry.get("description") or "Untitled"
    client = source.get("client") or {}
    client_name = client.get("name") if isinstance(client, dict) else str(client or "")
    return f"{client_name + ' · ' if client_name else ''}{desc}"


def _source_line(entry: dict[str, Any]) -> str:
    source = entry.get("source") or {}; bits = []
    for key in ("client", "project"):
        row = source.get(key) or {}
        if isinstance(row, dict) and row.get("name"): bits.append(str(row["name"]))
    if source.get("description"): bits.append(str(source["description"]))
    return " · ".join(bits)


def _init_theme() -> None:
    if "timesheet_theme" in st.session_state: return
    try: value = str(st.context.cookies.get(_THEME_COOKIE) or "system").lower()
    except Exception: value = "system"
    st.session_state["timesheet_theme"] = value if value in {"system", "light", "dark"} else "system"


def _persist_theme() -> None:
    _THEME_CONTROLLER.set(_THEME_COOKIE, st.session_state["timesheet_theme"], path="/", max_age=365*86400, secure=True, same_site="strict")


def _theme_css(theme: str) -> str:
    light="--card:#fff;--muted:#667085;--border:#d8dee4;--auto:#f2fbf5;--propose:#fff9e8;--ask:#fff1f1;--booked:#f3f4f6;"
    dark="--card:#11161d;--muted:#9aa4b2;--border:#30363d;--auto:#10251a;--propose:#2b2412;--ask:#2b1719;--booked:#1b2028;"
    root=dark if theme=="dark" else light; media="" if theme!="system" else f"@media(prefers-color-scheme:dark){{:root{{{dark}}}}}"
    return f"""<style>:root{{{root}}}{media}.tc-entry{{border:1px solid var(--border);border-left-width:5px;border-radius:10px;padding:.65rem .85rem;margin:.4rem 0 .2rem;background:var(--card)}}.tc-entry.auto{{border-left-color:#2da44e;background:var(--auto)}}.tc-entry.propose{{border-left-color:#d29922;background:var(--propose)}}.tc-entry.ask{{border-left-color:#cf222e;background:var(--ask)}}.tc-entry.booked{{border-left-color:#6e7781;background:var(--booked);opacity:.84}}.tc-entry.skip{{border-left-color:#8c959f;opacity:.52}}.tc-entry.skip .tc-title,.tc-entry.skip .tc-target,.tc-entry.skip .tc-time,.tc-entry.skip .tc-hours{{text-decoration:line-through}}.tc-row{{display:grid;grid-template-columns:110px 75px minmax(250px,1fr) minmax(240px,1.2fr) auto;gap:.8rem;align-items:center}}.tc-time{{font-weight:750}}.tc-hours{{font-weight:700}}.tc-title{{font-weight:650}}.tc-sub{{color:var(--muted);font-size:.78rem}}.tc-target{{font-size:.85rem}}.tc-badge{{display:inline-block;padding:.18rem .5rem;border-radius:999px;font-size:.7rem;font-weight:800}}.tc-badge.auto{{background:#2da44e;color:white}}.tc-badge.propose{{background:#d29922;color:#111}}.tc-badge.ask{{background:#cf222e;color:white}}.tc-badge.booked,.tc-badge.skip{{background:#6e7781;color:white}}.tc-day-title{{font-size:1.15rem;font-weight:700;margin-top:1rem}}.tc-day-meta{{color:var(--muted);font-size:.84rem}}.tc-week-title{{text-align:center;font-weight:700;padding-top:.45rem}}</style>"""


def _theme_picker() -> None:
    _init_theme(); st.radio("Appearance", ["system","light","dark"], format_func=str.capitalize, horizontal=True, label_visibility="collapsed", key="timesheet_theme", on_change=_persist_theme); st.markdown(_theme_css(st.session_state["timesheet_theme"]), unsafe_allow_html=True)


@st.cache_data(ttl=300, show_spinner=False)
def _review_context(start: str, end: str) -> dict[str, Any]: return load_review_context(start, end)


def _with_context(plan: dict[str, Any]) -> dict[str, Any]:
    result=deepcopy(plan); week=result["week"]; result["review_context"]=_review_context(week["monday"],week["sunday"]); return result


def _clean(plan: dict[str, Any]) -> dict[str, Any]:
    result=deepcopy(plan); result.pop("review_context",None); return result


def _assignment_options(plan: dict[str, Any], entry: dict[str, Any]) -> list[dict[str, Any]]:
    rows=[]; seen=set(); day=str(entry.get("date") or "")[:10]; candidates=(plan.get("review_context") or {}).get("booking_assignments") or []
    for item in candidates:
        iid=_plain_id(item)
        if not iid or iid in seen: continue
        start,end=str(item.get("start_date") or "")[:10],str(item.get("end_date") or "")[:10]
        if (start and start>day) or (end and end<day): continue
        seen.add(iid); rows.append(item)
    current=_plain_id(entry.get("assignment"))
    if current and current not in seen:
        found=next((r for r in candidates if _plain_id(r)==current),None); rows.insert(0,deepcopy(found or entry.get("assignment") or {"id":current}))
    return rows


def _assignment_label(row: dict[str, Any]) -> str:
    customer=(row.get("customer") or {}).get("name") if isinstance(row.get("customer"),dict) else None; project=(row.get("project") or {}).get("name") if isinstance(row.get("project"),dict) else None
    return str(row.get("display_label") or " · ".join(str(v) for v in (customer,project,row.get("name")) if v) or _plain_id(row))


def _target_line(entry: dict[str, Any], plan: dict[str, Any]) -> str:
    if entry.get("booking_mode")=="assignment":
        iid=_plain_id(entry.get("assignment")); row=next((r for r in _assignment_options(plan,entry) if _plain_id(r)==iid),None); return _assignment_label(row) if row else iid or "No assignment"
    mapping=entry.get("direct_mapping") or {}; return " · ".join(str(v) for v in (mapping.get("customer_name"),mapping.get("project_name"),mapping.get("service_name"),mapping.get("hour_type_name")) if v) or "Direct mapping incomplete"


def _status(entry: dict[str, Any]) -> str:
    if entry.get("ignored") or entry.get("review_state")=="skipped": return "SKIP"
    if entry.get("reconciliation_state")=="BOOKED": return "BOOKED"
    return str(entry.get("tier") or entry.get("overall_tier") or "ASK")


def _pending(entries: list[dict[str, Any]]) -> int:
    return sum(1 for e in entries if not e.get("ignored") and (e.get("tier") or e.get("overall_tier")) in {"PROPOSE","ASK"} and e.get("review_state") not in {"confirmed","corrected","skipped"})


def _entry_summary(plan: dict[str, Any], entry: dict[str, Any]) -> None:
    status=_status(entry); css=status.lower(); clocked=_hours(entry.get("original_duration_seconds")); planned=_hours(entry.get("planned_duration_seconds")); eid=html.escape(str(entry.get("entry_id") or ""),quote=True); timerange=f"{_format_hm(entry.get('planned_start'))}–{_format_hm(entry.get('planned_end'))}"
    st.markdown(f"<div id='entry-{eid}' class='tc-entry {css}'><div class='tc-row'><div class='tc-time'>{html.escape(timerange)}</div><div class='tc-hours'>{planned:.2f}h</div><div><div class='tc-title'>{html.escape(_entry_label(entry))}</div><div class='tc-sub'>Clockify: {html.escape(_source_line(entry))} · {clocked:.2f}h</div></div><div class='tc-target'>→ {html.escape(_target_line(entry,plan))}</div><div><span class='tc-badge {css}'>{status}</span></div></div></div>",unsafe_allow_html=True)


def _save_review(plan: dict[str, Any], entry: dict[str, Any], values: dict[str, Any], reason: str="") -> None:
    updated,proposal,reviewed=apply_review(_clean(plan),entry["entry_id"],values); saved=repo.save_revision(updated,expected_revision=int(plan["revision"])); repo.append_feedback(feedback_event(plan_id=saved["plan_id"],proposal=proposal,reviewed=reviewed,reason=reason)); st.session_state["scroll_to_entry"]=entry["entry_id"]; st.session_state["review_flash"]="Saved"; st.rerun()


def _select_row(label: str, rows: list[dict[str, Any]], current: Any, key: str) -> dict[str, Any] | None:
    options=[None]+rows; index=next((i for i,row in enumerate(options) if row and _plain_id(row)==_plain_id(current)),0); return st.selectbox(label,options,index=index,format_func=lambda row:"— select —" if row is None else _name(row),key=key)


def _direct_editor(plan: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    mapping=deepcopy(entry.get("direct_mapping") or {}); ctx=plan.get("review_context") or {}; customer=_select_row("Customer",ctx.get("customers") or [],mapping.get("customer_id") or "",f"c-{entry['entry_id']}"); customer_id=_plain_id(customer); projects=[r for r in ctx.get("projects") or [] if not customer_id or _plain_id(r.get("customer_id"))==customer_id]; project=_select_row("Project",projects,mapping.get("project_id") or "",f"p-{entry['entry_id']}"); project_id=_plain_id(project); services=[r for r in ctx.get("services") or [] if not project_id or not r.get("project_id") or _plain_id(r.get("project_id"))==project_id]; service=_select_row("Task / service",services,mapping.get("service_id") or "",f"s-{entry['entry_id']}")
    hour_types=[]; seen=set()
    for row in list(ctx.get("all_hour_types") or ctx.get("hour_types") or []):
        rid=_plain_id(row)
        if rid and rid not in seen: seen.add(rid); hour_types.append(row)
    preferred=str(read_config().get("preferred_hour_type") or "").casefold()
    if preferred: hour_types.sort(key=lambda row:(0 if _name(row).casefold()==preferred else 1,_name(row).casefold()))
    hour_type=_select_row("Hour type",hour_types,mapping.get("hour_type_id") or "",f"h-{entry['entry_id']}")
    return {"customer_id":customer_id or None,"customer_name":_name(customer) if customer else None,"project_id":project_id or None,"project_name":_name(project) if project else None,"service_id":_plain_id(service) or None,"service_name":_name(service) if service else None,"hour_type_id":_plain_id(hour_type) or None,"hour_type_name":_name(hour_type) if hour_type else None,"billable":bool(mapping.get("billable",True))}


def _target_complete(reviewed: dict[str, Any]) -> bool:
    if reviewed.get("booking_mode")=="assignment": return bool(_plain_id(reviewed.get("assignment")))
    mapping=reviewed.get("direct_mapping") or {}; return all(str(mapping.get(k) or "").strip() for k in ("project_id","service_id","hour_type_id"))


def _adjust_duration(duration_key: str, delta: float, absolute: bool=False) -> None:
    """Streamlit callback: runs before the widget is recreated on rerun."""
    current=float(st.session_state.get(duration_key,0.0))
    value=float(delta) if absolute else current+float(delta)
    st.session_state[duration_key]=max(0.0,min(24.0,value))


def _editor(plan: dict[str, Any], entry: dict[str, Any]) -> None:
    """Edit one entry transactionally. Controls stage values; only Save commits."""
    if _status(entry)=="SKIP":
        if st.button("Restore entry",key=f"restore-{entry['entry_id']}"): _save_review(plan,entry,{"ignored":False},"restored in review UI")
        return
    needs_review=_status(entry) in {"PROPOSE","ASK"} and entry.get("review_state") not in {"confirmed","corrected","skipped"}
    if entry.get("why_not_auto"): st.info(str(entry["why_not_auto"]))
    current=_hours(entry.get("planned_duration_seconds")); original=_hours(entry.get("original_duration_seconds")); duration_key=f"dur-{entry['entry_id']}-{plan['revision']}"
    if duration_key not in st.session_state: st.session_state[duration_key]=float(current)
    cols=st.columns([1.35,.72,.72,.72,.72,.72,.9])
    with cols[0]: st.number_input("Hours",min_value=0.0,max_value=24.0,step=.25,format="%.2f",key=duration_key)
    for col,(delta,label) in zip(cols[1:6],[(-1.0,"−1h"),(-.5,"−30"),(-.25,"−15"),(.25,"+15"),(.5,"+30")]):
        with col: st.button(label,key=f"d-{delta}-{entry['entry_id']}",use_container_width=True,on_click=_adjust_duration,args=(duration_key,delta))
    with cols[6]: st.button("Reset",key=f"reset-{entry['entry_id']}",disabled=abs(float(st.session_state[duration_key])-original)<.001,use_container_width=True,on_click=_adjust_duration,args=(duration_key,original,True))
    mode=st.radio("Booking mode",["assignment","direct"],horizontal=True,index=0 if entry.get("booking_mode")=="assignment" else 1,key=f"mode-{entry['entry_id']}"); reviewed={"booking_mode":mode,"planned_duration_seconds":round(float(st.session_state[duration_key])*3600)}
    if mode=="assignment":
        options=_assignment_options(plan,entry); current_id=_plain_id(entry.get("assignment")); selected=st.selectbox("Assignment",options,index=next((i for i,r in enumerate(options) if _plain_id(r)==current_id),0) if options else None,format_func=_assignment_label,key=f"a-{entry['entry_id']}",disabled=not options) if options else None; reviewed["assignment"]=deepcopy(selected) if selected else {}
    else: reviewed["direct_mapping"]=_direct_editor(plan,entry)
    reason=st.text_input("Reason / learning note",key=f"reason-{entry['entry_id']}"); complete=_target_complete(reviewed)
    if not complete: st.caption("Choose a complete booking target before resolving this entry.")
    actions=st.columns([1.2,1.2,1.2,3])
    with actions[0]:
        if st.button("Accept proposal" if needs_review else "Save changes",type="primary",key=f"save-{entry['entry_id']}",disabled=not complete,use_container_width=True): _save_review(plan,entry,reviewed,reason)
    with actions[1]:
        if st.button("Skip entry",key=f"skip-{entry['entry_id']}",use_container_width=True): _save_review(plan,entry,{"ignored":True},"skipped in review UI")
    with actions[2]:
        can_split=len(entry.get("clockify_source_ids") or [])>1
        if st.button("Split sources",key=f"split-{entry['entry_id']}",disabled=not can_split,use_container_width=True):
            updated=split_consolidated_entry(_clean(plan),entry["entry_id"]); repo.save_revision(updated,expected_revision=int(plan["revision"])); st.session_state["review_flash"]="Split into individual Clockify entries"; st.rerun()


@st.dialog("Review time entry",width="large")
def _entry_dialog(plan_id: str, entry_id: str, review_context: dict[str, Any]) -> None:
    plan=deepcopy(repo.get_latest(plan_id)); plan["review_context"]=review_context; entry=next((r for r in plan.get("entries") or [] if r.get("entry_id")==entry_id),None)
    if not entry: st.warning("Entry no longer exists."); return
    _entry_summary(plan,entry); _editor(plan,entry)


def _render_day(plan: dict[str, Any], day: str, entries: list[dict[str, Any]]) -> None:
    clocked=sum(_hours(e.get("original_duration_seconds")) for e in entries); workable=sum(_hours(e.get("planned_duration_seconds")) for e in entries if not e.get("ignored")); booked=sum(_hours(e.get("planned_duration_seconds")) for e in entries if e.get("reconciliation_state")=="BOOKED"); pending=_pending(entries); header,action=st.columns([5,1])
    with header: st.markdown(f"<div class='tc-day-title'>{html.escape(day)}</div><div class='tc-day-meta'>Clocked {clocked:.2f}h · Workable {workable:.2f}h · Booked {booked:.2f}h · {'ready' if not pending else f'{pending} review'}</div>",unsafe_allow_html=True)
    with action: st.button("Book day",key=f"book-{day}",disabled=True,use_container_width=True)
    context=plan.get("review_context") or {}
    for entry in entries:
        _entry_summary(plan,entry)
        if st.button("Review / edit",key=f"edit-{entry['entry_id']}"): _entry_dialog(plan["plan_id"],entry["entry_id"],context)


def _catalog() -> list[dict[str, Any]]:
    rows=repo.list_plans(limit=100); rows.sort(key=lambda r:str((r.get("week") or {}).get("monday") or "")); return rows


def _select_plan() -> dict[str, Any]:
    active=repo.get_active(); catalog=_catalog(); ids=[r["plan_id"] for r in catalog]
    if st.session_state.get("selected_plan_id") not in ids: st.session_state["selected_plan_id"]=active["plan_id"]
    idx=ids.index(st.session_state["selected_plan_id"]); row=catalog[idx]; week=row.get("week") or {}; monday,sunday=str(week.get("monday") or ""),str(week.get("sunday") or ""); title,nav,theme,out=st.columns([4,3.5,2.4,1.1])
    with title: st.markdown("## ⏱️ Timesheet Clerk")
    with nav:
        prev_col,label_col,next_col=st.columns([1,4,1])
        with prev_col:
            if st.button("◀",disabled=idx<=0,use_container_width=True): st.session_state["selected_plan_id"]=ids[idx-1]; st.session_state.pop("timesheet_day_picker",None); st.rerun()
        with label_col:
            try: label=f"Week {datetime.fromisoformat(monday).isocalendar().week} · {monday[5:]} → {sunday[5:]}"
            except ValueError: label=f"{monday} → {sunday}"
            st.markdown(f"<div class='tc-week-title'>{label}</div>",unsafe_allow_html=True)
        with next_col:
            if st.button("▶",disabled=idx>=len(ids)-1,use_container_width=True): st.session_state["selected_plan_id"]=ids[idx+1]; st.session_state.pop("timesheet_day_picker",None); st.rerun()
    with theme: _theme_picker()
    with out:
        if st.button("Log out",use_container_width=True): logout()
    return repo.get_latest(st.session_state["selected_plan_id"])


def _all_catalog_days() -> list[date]:
    days=[]
    for row in _catalog():
        start=date.fromisoformat(row["week"]["monday"]); end=date.fromisoformat(row["week"]["sunday"]); cursor=start
        while cursor<=end:
            if cursor not in days: days.append(cursor)
            cursor+=timedelta(days=1)
    return sorted(days)


def _shift_day(days: list[date], delta: int) -> None:
    current=st.session_state.get("timesheet_day_picker"); current=current if current in days else days[0]; idx=days.index(current); st.session_state["timesheet_day_picker"]=days[max(0,min(len(days)-1,idx+delta))]


def _day_navigator(stored: dict[str, Any]) -> date:
    days=_all_catalog_days(); monday=date.fromisoformat(stored["week"]["monday"]); current=st.session_state.get("timesheet_day_picker")
    if current not in days: st.session_state["timesheet_day_picker"]=monday
    idx=days.index(st.session_state["timesheet_day_picker"]); prev_col,picker_col,next_col=st.columns([1,4,1])
    with prev_col: st.button("◀ Day",disabled=idx<=0,use_container_width=True,on_click=_shift_day,args=(days,-1))
    with picker_col: selected=st.selectbox("Day",days,format_func=lambda d:d.strftime("%a %d-%m-%Y"),key="timesheet_day_picker",label_visibility="collapsed")
    with next_col: st.button("Day ▶",disabled=idx>=len(days)-1,use_container_width=True,on_click=_shift_day,args=(days,1))
    target=next((r for r in _catalog() if date.fromisoformat(r["week"]["monday"])<=selected<=date.fromisoformat(r["week"]["sunday"])),None)
    if target and target["plan_id"]!=stored["plan_id"]: st.session_state["selected_plan_id"]=target["plan_id"]; st.rerun()
    return selected


def _trigger_planner(plan: dict[str, Any]) -> None:
    cfg=read_config(); profile=str(cfg.get("planner_profile") or "atlas"); week=plan.get("week") or {}; prompt=f"Synchronize Timesheet Clerk for {week.get('monday')} through {week.get('sunday')}. FIRST call timesheet_sync_probe with full ISO-8601 week timestamps. If it reports requires_rebaseline, establish a fresh Clockify source baseline while preserving human-reviewed booking state, then call timesheet_plan_sync. If has_changes is false, stop immediately and report only its deterministic summary. Do not load Simplicate, learning context or the full plan in the no-op path. If genuine changes exist, use only source_delta.new_entries and source_delta.changed_entries as Clockify source records, then read only the Simplicate/learning data needed for those deltas. Treat every normalized Clockify record as one immutable source bundle. Preserve canonical Clockify source snapshots in the sync payload. Then call timesheet_plan_sync. Present the deterministic summary returned by the tool; never recalculate counts or totals. Never use filesystem/file-search for Clerk state and never book hours."
    clear_sync_status(repo.root); launch_sync(root=repo.root,profile=profile,prompt=prompt); st.success(f"{profile} sync started.")


@st.fragment(run_every="3s")
def _sync_status_widget() -> None:
    status=sync_status(repo.root)
    if not status: return
    if status.get("status")=="running": st.info(f"Sync running via {status.get('profile','planner')}…")
    else:
        cols=st.columns([5,1]); cols[0].success("Sync finished. Refresh the view to load the latest plan state.")
        if cols[1].button("Dismiss",key="dismiss-sync",use_container_width=True): clear_sync_status(repo.root); st.rerun(scope="fragment")


def _restore_scroll() -> None:
    entry_id=st.session_state.pop("scroll_to_entry",None)
    if not entry_id: return
    target=json.dumps(f"entry-{entry_id}"); components.html(f"<script>setTimeout(()=>{{const e=window.parent.document.getElementById({target});if(e)e.scrollIntoView({{block:'center',behavior:'instant'}});}},80);</script>",height=0)


def _review_page(stored: dict[str, Any], plan: dict[str, Any]) -> None:
    entries=plan["entries"]; target=float(plan["target_hours"]); clocked=sum(_hours(e.get("original_duration_seconds")) for e in entries); workable=sum(_hours(e.get("planned_duration_seconds")) for e in entries if not e.get("ignored")); booked=sum(_hours(e.get("planned_duration_seconds")) for e in entries if e.get("reconciliation_state")=="BOOKED"); pending=_pending(entries); flash=st.session_state.pop("review_flash",None)
    if flash: st.success(str(flash))
    metrics=st.columns(5); metrics[0].metric("Target",f"{target:.1f}h"); metrics[1].metric("Clocked",f"{clocked:.1f}h"); metrics[2].metric("Workable",f"{workable:.1f}h"); metrics[3].metric("Booked",f"{booked:.1f}h"); metrics[4].metric("Open",f"{max(0,workable-booked):.1f}h")
    c1,c2,c3,c4=st.columns([1.5,2.4,1.4,4.7])
    with c1: view=st.radio("View",["week","day"],format_func=str.capitalize,horizontal=True,label_visibility="collapsed",key="timesheet_view")
    with c2:
        if st.button("↻ Generate / refresh plan",use_container_width=True): _trigger_planner(stored)
    with c3:
        if st.button("Refresh view",use_container_width=True): clear_sync_status(repo.root); _review_context.clear(); st.rerun()
    with c4: st.caption(f"{stored['plan_id']} · revision {stored['revision']} · {stored['status']} · planner: {read_config()['planner_profile']}")
    _sync_status_widget(); selected_day=_day_navigator(stored) if view=="day" else None
    if abs(workable-target)>=.01: st.warning(f"Workable time is {workable-target:+.2f}h versus target.")
    if pending: st.info(f"{pending} PROPOSE/ASK entries still need review.")
    with st.expander("⚙ Week settings",expanded=False):
        value=st.number_input("Target hours",min_value=0.0,step=.5,value=target)
        if st.button("Save target"): updated=deepcopy(stored); updated["target_hours"]=float(value); updated["status"]="IN_REVIEW"; repo.save_revision(updated,expected_revision=int(stored["revision"])); st.rerun()
    days={}
    for entry in entries: days.setdefault(str(entry.get("date") or "Unknown"),[]).append(entry)
    keys=sorted(k for k in days if k!="Unknown")
    if view=="day" and selected_day:
        key=selected_day.isoformat(); _render_day(plan,key,days[key]) if key in days else st.info("No time entries for this date.")
    else:
        for day in keys: _render_day(plan,day,days[day])
    if view=="week":
        st.divider(); approve,book=st.columns(2)
        with approve:
            if st.button("Approve week",disabled=bool(pending),use_container_width=True):
                try: snapshot=repo.approve_snapshot(stored["plan_id"],int(stored["revision"])); st.success(f"Approved revision {snapshot['revision']}")
                except StateConflict as exc: st.error(str(exc))
        with book: st.button("Book approved week",type="primary",disabled=True,use_container_width=True)
    _restore_scroll()


def main() -> None:
    require_login()
    try: stored=_select_plan()
    except PlanNotFound: st.info("No booking plan yet."); return
    try:
        with st.spinner("Loading Timesheet Clerk…",show_time=True): plan=_with_context(stored)
    except Exception as exc: st.error(f"Could not load Simplicate review choices: {exc}"); plan=deepcopy(stored); plan["review_context"]={}
    review_tab,config_tab,skill_tab,state_tab=st.tabs(["Review","Configuration","SKILL","State"])
    with review_tab: _review_page(stored,plan)
    with config_tab: render_config(repo,DEFAULT_SKILL)
    with skill_tab: render_skill(repo,DEFAULT_SKILL)
    with state_tab: render_state(repo,stored,plan.get("review_context") or {})


if __name__=="__main__": main()
