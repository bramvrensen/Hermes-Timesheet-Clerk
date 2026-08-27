"""Confirmation UI for guarded day/week booking."""
from __future__ import annotations

from typing import Any

import streamlit as st

from .single_booking import execute_entry_batch, preview_entry_batch, task_booking_ready
from .storage import PlanRepository
from .ui_single_booking import _show_error
from .ui_time import format_duration


def _bookable_ids(entries: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    ready: list[str] = []
    blocked: list[str] = []
    for entry in entries:
        if entry.get("reconciliation_state") == "BOOKED" or entry.get("ignored") or entry.get("review_state") == "skipped":
            continue
        ok, reason = task_booking_ready(entry)
        if ok:
            ready.append(str(entry["entry_id"]))
        else:
            blocked.append(f"{entry.get('entry_id')}: {reason}")
    return ready, blocked


def _state_key(plan: dict[str, Any], scope: str) -> str:
    return f"batch-book-{plan['plan_id']}-{plan.get('revision')}-{scope}"


def _render_confirmation(repo: PlanRepository, plan: dict[str, Any], entries: list[dict[str, Any]], scope: str, label: str) -> None:
    key = _state_key(plan, scope)
    state = st.session_state.get(key)
    if state is None:
        return
    preview = state.get("preview")
    if preview is None:
        try:
            with st.spinner("Checking Simplicate for existing registrations…", show_time=True):
                preview = preview_entry_batch(repo, str(plan["plan_id"]), state["entry_ids"])
            state["preview"] = preview
            st.session_state[key] = state
        except Exception as exc:
            _show_error(exc)
            return

    if preview.get("possible_duplicate_count"):
        st.error(f"{preview['possible_duplicate_count']} possible duplicate(s) found. Batch booking is blocked; review those entries individually.")
        if st.button("Close", key=f"close-{key}"):
            st.session_state.pop(key, None); st.rerun()
        return

    total_seconds = sum(int((row.get("entry") or {}).get("planned_duration_seconds") or 0) for row in preview.get("rows") or [] if row.get("status") == "ready")
    st.warning(f"{label} will create {preview.get('ready_count', 0)} real Simplicate registration(s), totalling {format_duration(total_seconds)}.")
    confirmed = st.checkbox("I checked these entries and want to book them", key=f"confirm-{key}")
    cols = st.columns(2)
    with cols[0]:
        if st.button(f"Confirm {label.lower()}", type="primary", disabled=not confirmed, use_container_width=True, key=f"execute-{key}"):
            with st.spinner("Booking and verifying in Simplicate…", show_time=True):
                result = execute_entry_batch(repo, str(plan["plan_id"]), preview)
            st.session_state.pop(key, None)
            st.session_state["booking_flash"] = f"{label}: {result['booked_count']} booked, {result['failed_count']} failed"
            if result["failed_count"]:
                st.session_state["booking_failures"] = [row for row in result["results"] if not row.get("success")]
            st.rerun()
    with cols[1]:
        if st.button("Cancel", use_container_width=True, key=f"cancel-{key}"):
            st.session_state.pop(key, None); st.rerun()


def render_day_booking(repo: PlanRepository, plan: dict[str, Any], day: str, entries: list[dict[str, Any]]) -> None:
    ready, blocked = _bookable_ids(entries)
    open_entries = [entry for entry in entries if not entry.get("ignored") and entry.get("review_state") != "skipped" and entry.get("reconciliation_state") != "BOOKED"]
    key = _state_key(plan, f"day-{day}")
    disabled = not open_entries or bool(blocked) or not ready
    if st.button("Book day", key=f"book-{day}", disabled=disabled, use_container_width=True, help="All open entries for this day must be reviewed and bookable."):
        st.session_state[key] = {"entry_ids": ready}
    if blocked:
        st.caption("Book day becomes available when every open entry for this day is reviewed and has a complete booking target.")
    _render_confirmation(repo, plan, entries, f"day-{day}", "Book day")


def render_week_booking(repo: PlanRepository, plan: dict[str, Any]) -> None:
    entries = list(plan.get("entries") or [])
    ready, blocked = _bookable_ids(entries)
    open_entries = [entry for entry in entries if not entry.get("ignored") and entry.get("review_state") != "skipped" and entry.get("reconciliation_state") != "BOOKED"]
    key = _state_key(plan, "week")
    disabled = not open_entries or bool(blocked) or not ready
    if st.button("Book week", type="primary", disabled=disabled, use_container_width=True, help="All open entries in the week must be reviewed and bookable."):
        st.session_state[key] = {"entry_ids": ready}
    if blocked:
        st.caption("Book week becomes available when every open entry in the week is reviewed and has a complete booking target.")
    _render_confirmation(repo, plan, entries, "week", "Book week")
