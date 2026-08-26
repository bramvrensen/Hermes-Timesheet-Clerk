"""Human-readable Timesheet Clerk duration presentation for Streamlit."""
from __future__ import annotations

import html
from copy import deepcopy
from typing import Any

import streamlit as st


def format_duration(seconds: Any, *, signed: bool = False) -> str:
    """Format seconds as human time, avoiding decimal-hour notation."""
    try:
        value = float(seconds or 0)
    except (TypeError, ValueError):
        value = 0.0
    sign = ""
    if value < 0:
        sign = "−"
    elif signed and value > 0:
        sign = "+"
    minutes_total = int(round(abs(value) / 60.0))
    hours, minutes = divmod(minutes_total, 60)
    if hours and minutes:
        text = f"{hours}u {minutes} min"
    elif hours:
        text = f"{hours}u"
    else:
        text = f"{minutes} min"
    return sign + text


def install_review_time_formatting(review: Any) -> None:
    """Patch the mature review surface to use human duration labels everywhere."""

    def entry_summary(plan: dict[str, Any], entry: dict[str, Any]) -> None:
        status = review._status(entry)
        css = status.lower()
        clocked = format_duration(entry.get("original_duration_seconds"))
        planned = format_duration(entry.get("planned_duration_seconds"))
        eid = html.escape(str(entry.get("entry_id") or ""), quote=True)
        timerange = f"{review._format_hm(entry.get('planned_start'))}–{review._format_hm(entry.get('planned_end'))}"
        st.markdown(
            f"<div id='entry-{eid}' class='tc-entry {css}'><div class='tc-row'>"
            f"<div class='tc-time'>{html.escape(timerange)}</div>"
            f"<div class='tc-hours'>{html.escape(planned)}</div>"
            f"<div><div class='tc-title'>{html.escape(review._entry_label(entry))}</div>"
            f"<div class='tc-sub'>Clockify: {html.escape(review._source_line(entry))} · {html.escape(clocked)}</div></div>"
            f"<div class='tc-target'>→ {html.escape(review._target_line(entry, plan))}</div>"
            f"<div><span class='tc-badge {css}'>{status}</span></div></div></div>",
            unsafe_allow_html=True,
        )

    def render_day(plan: dict[str, Any], day: str, entries: list[dict[str, Any]]) -> None:
        clocked_seconds = sum(float(e.get("original_duration_seconds") or 0) for e in entries)
        workable_seconds = sum(float(e.get("planned_duration_seconds") or 0) for e in entries if not e.get("ignored"))
        booked_seconds = sum(float(e.get("planned_duration_seconds") or 0) for e in entries if e.get("reconciliation_state") == "BOOKED")
        pending = review._pending(entries)
        header, action = st.columns([5, 1])
        with header:
            st.markdown(
                f"<div class='tc-day-title'>{html.escape(day)}</div>"
                f"<div class='tc-day-meta'>Clocked {format_duration(clocked_seconds)} · "
                f"Workable {format_duration(workable_seconds)} · Booked {format_duration(booked_seconds)} · "
                f"{'ready' if not pending else f'{pending} review'}</div>",
                unsafe_allow_html=True,
            )
        with action:
            st.button("Book day", key=f"book-{day}", disabled=True, use_container_width=True)
        context = plan.get("review_context") or {}
        for entry in entries:
            entry_summary(plan, entry)
            if st.button("Review / edit", key=f"edit-{entry['entry_id']}"):
                review._entry_dialog(plan["plan_id"], entry["entry_id"], context)

    def review_page(stored: dict[str, Any], plan: dict[str, Any]) -> None:
        entries = plan["entries"]
        target_hours = float(plan["target_hours"])
        target_seconds = target_hours * 3600.0
        clocked_seconds = sum(float(e.get("original_duration_seconds") or 0) for e in entries)
        workable_seconds = sum(float(e.get("planned_duration_seconds") or 0) for e in entries if not e.get("ignored"))
        booked_seconds = sum(float(e.get("planned_duration_seconds") or 0) for e in entries if e.get("reconciliation_state") == "BOOKED")
        pending = review._pending(entries)
        flash = st.session_state.pop("review_flash", None)
        if flash:
            st.success(str(flash))

        metrics = st.columns(5)
        metrics[0].metric("Target", format_duration(target_seconds))
        metrics[1].metric("Clocked", format_duration(clocked_seconds))
        metrics[2].metric("Workable", format_duration(workable_seconds))
        metrics[3].metric("Booked", format_duration(booked_seconds))
        metrics[4].metric("Open", format_duration(max(0.0, workable_seconds - booked_seconds)))

        c1, c2, c3, c4 = st.columns([1.5, 2.4, 1.4, 4.7])
        with c1:
            view = st.radio("View", ["week", "day"], format_func=str.capitalize, horizontal=True, label_visibility="collapsed", key="timesheet_view")
        with c2:
            if st.button("↻ Generate / refresh plan", use_container_width=True):
                review._trigger_planner(stored)
        with c3:
            if st.button("Refresh view", use_container_width=True):
                review.clear_sync_status(review.repo.root)
                review._review_context.clear()
                st.rerun()
        with c4:
            st.caption(f"{stored['plan_id']} · revision {stored['revision']} · {stored['status']} · planner: {review.read_config()['planner_profile']}")

        review._sync_status_widget()
        selected_day = review._day_navigator(stored) if view == "day" else None
        delta = workable_seconds - target_seconds
        if abs(delta) >= 30:
            st.warning(f"Workable time is {format_duration(delta, signed=True)} versus target.")
        if pending:
            st.info(f"{pending} PROPOSE/ASK entries still need review.")

        with st.expander("⚙ Week settings", expanded=False):
            value = st.number_input("Target hours", min_value=0.0, step=.5, value=target_hours)
            if st.button("Save target"):
                updated = deepcopy(stored)
                updated["target_hours"] = float(value)
                updated["status"] = "IN_REVIEW"
                review.repo.save_revision(updated, expected_revision=int(stored["revision"]))
                st.rerun()

        days: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            days.setdefault(str(entry.get("date") or "Unknown"), []).append(entry)
        keys = sorted(key for key in days if key != "Unknown")
        if view == "day" and selected_day:
            key = selected_day.isoformat()
            render_day(plan, key, days[key]) if key in days else st.info("No time entries for this date.")
        else:
            for day in keys:
                render_day(plan, day, days[day])

        if view == "week":
            st.divider()
            approve, book = st.columns(2)
            with approve:
                if st.button("Approve week", disabled=bool(pending), use_container_width=True):
                    try:
                        snapshot = review.repo.approve_snapshot(stored["plan_id"], int(stored["revision"]))
                        st.success(f"Approved revision {snapshot['revision']}")
                    except review.StateConflict as exc:
                        st.error(str(exc))
            with book:
                st.button("Book approved week", type="primary", disabled=True, use_container_width=True)
        review._restore_scroll()

    review._entry_summary = entry_summary
    review._render_day = render_day
    review._review_page = review_page
