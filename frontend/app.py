"""Timesheet Clerk Streamlit shell for the deterministic planner workflow."""
from __future__ import annotations

import os
from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

import review_app as review
import timesheet_clerk.ui_admin as ui_admin
from timesheet_clerk.state_selection import ensure_active_plan, has_working_week
from timesheet_clerk.storage import PlanNotFound
from timesheet_clerk.ui_batch_booking import render_day_booking
from timesheet_clerk.ui_booking import render_booking
from timesheet_clerk.ui_choices import editor_hour_type_choices
from timesheet_clerk.ui_planner import start_planner
from timesheet_clerk.ui_single_booking import render_task_booking
from timesheet_clerk.ui_sync import clear_sync_status, sync_status
from timesheet_clerk.ui_time import install_review_time_formatting

_REVIEWED_STATES = {"confirmed", "corrected"}


def _current_week() -> tuple[str, str]:
    tz = ZoneInfo(os.environ.get("TZ") or "Europe/Amsterdam")
    today = datetime.now(tz).date()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def _pending_review_entries(entries: list[dict]) -> list[dict]:
    return [entry for entry in entries if not entry.get("ignored") and entry.get("review_state") != "skipped" and str(entry.get("tier") or entry.get("overall_tier") or "ASK").upper() in {"PROPOSE", "ASK"} and entry.get("review_state") not in _REVIEWED_STATES]


def _display_status(entry: dict) -> str:
    if entry.get("ignored") or entry.get("review_state") == "skipped": return "SKIP"
    if entry.get("reconciliation_state") == "BOOKED": return "BOOKED"
    tier = str(entry.get("tier") or entry.get("overall_tier") or "ASK").upper()
    if tier in {"PROPOSE", "ASK"} and entry.get("review_state") in _REVIEWED_STATES: return "READY"
    return tier


def _install_reviewed_css() -> None:
    st.markdown("""<style>
    .tc-entry.ready{border-left-color:#2f81f7;background:color-mix(in srgb,var(--card) 88%,#2f81f7 12%)}
    .tc-badge.ready{background:#2f81f7;color:white}
    </style>""", unsafe_allow_html=True)


def _render_review_queue(plan: dict) -> None:
    pending = _pending_review_entries(list(plan.get("entries") or []))
    if not pending: return
    noun = "entry" if len(pending) == 1 else "entries"; context = plan.get("review_context") or {}
    with st.expander(f"🔎 {len(pending)} {noun} still need review", expanded=True):
        for entry in pending:
            tier = str(entry.get("tier") or entry.get("overall_tier") or "ASK").upper(); when = f"{entry.get('date') or ''} · {review._format_hm(entry.get('planned_start'))}–{review._format_hm(entry.get('planned_end'))}"; label = review._entry_label(entry)
            cols = st.columns([1.4,4.8,.8,1]); cols[0].caption(when); cols[1].write(label); cols[2].write(tier)
            if cols[3].button("Review", key=f"queue-review-{entry['entry_id']}", use_container_width=True): st.session_state["scroll_to_entry"] = entry["entry_id"]; review._entry_dialog(plan["plan_id"], entry["entry_id"], context)


def _render_job_status() -> None:
    status=sync_status(review.repo.root)
    if not status:return
    state=str(status.get("status") or "").upper();message=str(status.get("message") or "")
    if state in {"STARTING","RUNNING"}:st.info(message or "Planner running…")
    elif state=="SUCCEEDED":st.success(message or "Planner finished successfully. Refresh the view to load the new plan state.")
    elif state=="FAILED":st.error(message or "Planner failed. Existing plan state was preserved.")
    if state in {"SUCCEEDED","FAILED"} and st.button("Dismiss planner status",use_container_width=False):clear_sync_status(review.repo.root);st.rerun()


def _trigger_refresh(plan:dict)->None:
    week=plan.get("week") or {};result=start_planner(review.repo.root,str(week["monday"]),str(week["sunday"]),rebuild=False);st.success(f"Planner refresh started · run {result['run_id'][:8]}")


def _safe_rebuild_active_week(repo)->None:
    st.divider();st.caption("Rebuild week")
    try:active=ensure_active_plan(repo)
    except PlanNotFound:st.info("No stored plan is available to rebuild.");return
    week=active.get("week") or {};monday,sunday=str(week.get("monday") or ""),str(week.get("sunday") or "");st.warning(f"Rebuild {monday} through {sunday} from live sources. The current plan is NOT deleted first; it remains active unless a complete validated replacement succeeds.")
    confirmed=st.checkbox("I want to rebuild this week from scratch",key=f"rebuild-confirm-{active.get('plan_id')}")
    if st.button("Rebuild active week",type="primary",disabled=not confirmed,use_container_width=True):result=start_planner(repo.root,monday,sunday,rebuild=True);st.success(f"Safe rebuild started · run {result['run_id'][:8]}. Existing state remains available until replacement succeeds.")


def _generate_current_week_action(*,compact:bool=False)->None:
    monday,sunday=_current_week()
    if has_working_week(review.repo,monday,sunday):return
    st.info(f"Current week {monday} → {sunday} has no working plan yet." if compact else f"No working plan exists for the current week. Build {monday} through {sunday} from live sources.")
    if st.button("Generate current week",type="primary",use_container_width=True,key=f"generate-current-{monday}"):result=start_planner(review.repo.root,monday,sunday,rebuild=False);st.success(f"Current-week generation started · run {result['run_id'][:8]}")


def _bootstrap_current_week()->None:_generate_current_week_action(compact=False);_render_job_status()


def _direct_editor_scoped(plan:dict,entry:dict)->dict:
    mapping=deepcopy(entry.get("direct_mapping") or {});ctx=plan.get("review_context") or {};customer=review._select_row("Customer",ctx.get("customers") or [],mapping.get("customer_id") or "",f"c-{entry['entry_id']}");customer_id=review._plain_id(customer);projects=[row for row in ctx.get("projects") or [] if not customer_id or review._plain_id(row.get("customer_id"))==customer_id];project=review._select_row("Project",projects,mapping.get("project_id") or "",f"p-{entry['entry_id']}");project_id=review._plain_id(project);services=[row for row in ctx.get("services") or [] if not project_id or not row.get("project_id") or review._plain_id(row.get("project_id"))==project_id];service=review._select_row("Task / service",services,mapping.get("service_id") or "",f"s-{entry['entry_id']}");service_id=review._plain_id(service)
    hour_types,preserved_current=editor_hour_type_choices(ctx,service_id,current_service_id=mapping.get("service_id"),current_hour_type_id=mapping.get("hour_type_id"),current_hour_type_name=mapping.get("hour_type_name"));preferred=str(review.read_config().get("preferred_hour_type") or "").casefold()
    if preferred:hour_types.sort(key=lambda row:(0 if review._name(row).casefold()==preferred else 1,review._name(row).casefold()))
    current_hour_type=mapping.get("hour_type_id") or ""
    if preserved_current:st.warning("The saved Hour type could not be re-verified from the current Simplicate service context. It is preserved so opening the editor does not erase an existing mapping. Choose another value only if you want to change it.")
    elif service_id and not hour_types:st.warning("No valid hour types are available for the selected Task / service.")
    hour_type=review._select_row("Hour type",hour_types,current_hour_type,f"h-{entry['entry_id']}") if hour_types else None
    return {"customer_id":customer_id or None,"customer_name":review._name(customer) if customer else None,"project_id":project_id or None,"project_name":review._name(project) if project else None,"service_id":service_id or None,"service_name":review._name(service) if service else None,"hour_type_id":review._plain_id(hour_type) or None,"hour_type_name":review._name(hour_type) if hour_type else None,"billable":bool(mapping.get("billable",True))}


if not hasattr(review,"_timesheet_clerk_base_editor"):review._timesheet_clerk_base_editor=review._editor

def _editor_with_task_booking(plan:dict,entry:dict)->None:review._timesheet_clerk_base_editor(plan,entry);render_task_booking(review.repo,plan,entry)

def _entry_dialog_with_scroll(plan_id:str,entry_id:str,review_context:dict)->None:st.session_state["scroll_to_entry"]=entry_id;review._timesheet_clerk_base_entry_dialog(plan_id,entry_id,review_context)

def _render_day_with_booking(plan:dict,day:str,entries:list[dict])->None:
    clocked=sum(review._hours(e.get("original_duration_seconds")) for e in entries);workable=sum(review._hours(e.get("planned_duration_seconds")) for e in entries if not e.get("ignored"));booked=sum(review._hours(e.get("planned_duration_seconds")) for e in entries if e.get("reconciliation_state")=="BOOKED");pending=len(_pending_review_entries(entries));header,action=st.columns([5,1])
    with header:st.markdown(f"<div class='tc-day-title'>{review.html.escape(day)}</div><div class='tc-day-meta'>Clocked {clocked:.2f}h · Workable {workable:.2f}h · Booked {booked:.2f}h · {'ready' if not pending else f'{pending} review'}</div>",unsafe_allow_html=True)
    with action:render_day_booking(review.repo,plan,day,entries)
    context=plan.get("review_context") or {}
    for entry in entries:
        review._entry_summary(plan,entry)
        if st.button("Review / edit",key=f"edit-{entry['entry_id']}"):st.session_state["scroll_to_entry"]=entry["entry_id"];review._entry_dialog(plan["plan_id"],entry["entry_id"],context)


def _review_page_with_queue(stored:dict,plan:dict)->None:
    _render_review_queue(plan);review._timesheet_clerk_base_review_page(stored,plan)


if not hasattr(review,"_timesheet_clerk_base_entry_dialog"):review._timesheet_clerk_base_entry_dialog=review._entry_dialog
if not hasattr(review,"_timesheet_clerk_base_review_page"):review._timesheet_clerk_base_review_page=review._review_page
review._trigger_planner=_trigger_refresh;review._sync_status_widget=lambda:None;review._direct_editor=_direct_editor_scoped;review._status=_display_status;review._editor=_editor_with_task_booking;review._render_day=_render_day_with_booking;review._review_page=_review_page_with_queue
install_review_time_formatting(review);ui_admin._fresh_start_active_week=_safe_rebuild_active_week


def main()->None:
    review.require_login();_install_reviewed_css();flash=st.session_state.pop("booking_flash",None)
    if flash:st.success(str(flash))
    failures=st.session_state.pop("booking_failures",None)
    if failures:st.error("Some registrations failed and remain open for review: "+"; ".join(f"{row.get('entry_id')}: {row.get('message')}" for row in failures))
    try:ensure_active_plan(review.repo);stored=review._select_plan()
    except PlanNotFound:
        st.markdown("## ⏱️ Timesheet Clerk");build_tab,config_tab,skill_tab,state_tab=st.tabs(["Generate","Configuration","SKILL","State"])
        with build_tab:_bootstrap_current_week()
        with config_tab:review.render_config(review.repo,review.DEFAULT_SKILL)
        with skill_tab:review.render_skill(review.repo,review.DEFAULT_SKILL)
        with state_tab:review.render_state(review.repo,None,{})
        return
    try:
        with st.spinner("Loading Timesheet Clerk…",show_time=True):plan=review._with_context(stored)
    except Exception as exc:st.error(f"Could not load Simplicate review choices: {exc}");plan=deepcopy(stored);plan["review_context"]={}
    review_tab,booking_tab,config_tab,skill_tab,state_tab=st.tabs(["Review","Booking","Configuration","SKILL","State"])
    with review_tab:_generate_current_week_action(compact=True);review._review_page(stored,plan);_render_job_status()
    with booking_tab:render_booking(review.repo,stored["plan_id"])
    with config_tab:review.render_config(review.repo,review.DEFAULT_SKILL)
    with skill_tab:review.render_skill(review.repo,review.DEFAULT_SKILL)
    with state_tab:review.render_state(review.repo,stored,plan.get("review_context") or {})


if __name__=="__main__":main()
