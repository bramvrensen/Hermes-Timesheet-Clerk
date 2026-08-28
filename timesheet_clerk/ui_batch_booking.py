"""Confirmation UI for guarded day/week booking."""
from __future__ import annotations
from typing import Any
import streamlit as st
from .single_booking import execute_entry_batch, preview_entry_batch, task_booking_ready
from .storage import PlanRepository
from .ui_single_booking import _show_error
from .ui_time import format_duration


def _description(entry: dict[str, Any]) -> str:
    return str((entry.get("source") or {}).get("description") or entry.get("description") or entry.get("entry_id") or "Untitled")


def _bookable_ids(entries: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, str]]]:
    ready: list[str] = []; blocked: list[dict[str, str]] = []
    for entry in entries:
        if entry.get("reconciliation_state") == "BOOKED" or entry.get("ignored") or entry.get("review_state") == "skipped": continue
        ok, reason = task_booking_ready(entry)
        if ok: ready.append(str(entry["entry_id"]))
        else: blocked.append({"entry_id":str(entry.get("entry_id") or ""),"description":_description(entry),"reason":reason})
    return ready, blocked


def _state_key(plan: dict[str, Any], scope: str) -> str: return f"batch-book-{plan['plan_id']}-{plan.get('revision')}-{scope}"


def _render_blockers(blocked: list[dict[str, str]], scope: str) -> None:
    if not blocked: return
    noun = "entry stays in review" if len(blocked) == 1 else "entries stay in review"
    with st.expander(f"{len(blocked)} {noun}", expanded=True):
        for row in blocked: st.caption(f"{row['description']} · {row['reason']}")


def _render_confirmation(repo: PlanRepository, plan: dict[str, Any], entries: list[dict[str, Any]], scope: str, label: str) -> None:
    key=_state_key(plan,scope);state=st.session_state.get(key)
    if state is None:return
    preview=state.get("preview")
    blocked=state.get("blocked") or []
    if blocked:
        st.info(f"{len(blocked)} open entr{'y' if len(blocked)==1 else 'ies'} will not be booked and will remain in review.")
        _render_blockers(blocked, label.lower().replace('book ',''))
    if preview is None:
        try:
            with st.spinner("Checking Simplicate for existing registrations…",show_time=True): preview=preview_entry_batch(repo,str(plan["plan_id"]),state["entry_ids"])
            state["preview"]=preview;st.session_state[key]=state
        except Exception as exc:_show_error(exc);return
    if preview.get("possible_duplicate_count"):
        st.error(f"{preview['possible_duplicate_count']} possible duplicate(s) found among the ready entries. Batch booking is blocked to prevent duplicates.")
        if st.button("Close",key=f"close-{key}"):st.session_state.pop(key,None);st.rerun()
        return
    total_seconds=sum(int((row.get("entry") or {}).get("planned_duration_seconds") or 0) for row in preview.get("rows") or [] if row.get("status")=="ready")
    st.warning(f"{label} will create {preview.get('ready_count',0)} real Simplicate registration(s), totalling {format_duration(total_seconds)}.")
    confirmed=st.checkbox("I checked the ready entries and want to book them",key=f"confirm-{key}");cols=st.columns(2)
    with cols[0]:
        if st.button(f"Confirm {label.lower()}",type="primary",disabled=not confirmed,use_container_width=True,key=f"execute-{key}"):
            with st.spinner("Booking and verifying in Simplicate…",show_time=True): result=execute_entry_batch(repo,str(plan["plan_id"]),preview)
            st.session_state.pop(key,None);st.session_state["booking_flash"]=f"{label}: {result['booked_count']} booked, {result['failed_count']} failed"
            if result["failed_count"]:st.session_state["booking_failures"]=[row for row in result["results"] if not row.get("success")]
            st.rerun()
    with cols[1]:
        if st.button("Cancel",use_container_width=True,key=f"cancel-{key}"):st.session_state.pop(key,None);st.rerun()


def render_day_booking(repo: PlanRepository, plan: dict[str, Any], day: str, entries: list[dict[str, Any]]) -> None:
    ready,blocked=_bookable_ids(entries);open_entries=[entry for entry in entries if not entry.get("ignored") and entry.get("review_state")!="skipped" and entry.get("reconciliation_state")!="BOOKED"];key=_state_key(plan,f"day-{day}");disabled=not open_entries or not ready
    if st.button("Book day",key=f"book-{day}",disabled=disabled,use_container_width=True,help="Books all currently ready entries for this day. Entries that still need review remain open."):
        st.session_state[key]={"entry_ids":ready,"blocked":blocked}
    if blocked and not ready: st.caption("No entries on this day are bookable yet.")
    elif blocked: st.caption(f"{len(ready)} ready · {len(blocked)} remain in review")
    _render_confirmation(repo,plan,entries,f"day-{day}","Book day")


def render_week_booking(repo: PlanRepository, plan: dict[str, Any]) -> None:
    entries=list(plan.get("entries") or []);ready,blocked=_bookable_ids(entries);open_entries=[entry for entry in entries if not entry.get("ignored") and entry.get("review_state")!="skipped" and entry.get("reconciliation_state")!="BOOKED"];key=_state_key(plan,"week");disabled=not open_entries or not ready
    if st.button("Book week",type="primary",disabled=disabled,use_container_width=True,help="Books all currently ready entries in the week. Entries that still need review remain open."):
        st.session_state[key]={"entry_ids":ready,"blocked":blocked}
    if blocked and not ready: st.caption("No entries in this week are bookable yet.")
    elif blocked: st.caption(f"{len(ready)} ready · {len(blocked)} remain in review")
    _render_confirmation(repo,plan,entries,"week","Book week")
