"""Human-readable single-task booking UI for Streamlit."""
from __future__ import annotations

from typing import Any

import streamlit as st

from .single_booking import execute_single_entry_booking, preview_single_entry, task_booking_ready
from .storage import PlanRepository
from .ui_time import format_duration


def _name(value: Any) -> str:
    if not isinstance(value, dict):
        return str(value or "")
    return str(value.get("name") or value.get("title") or value.get("label") or value.get("id") or "")


def _target(entry: dict[str, Any]) -> str:
    if entry.get("booking_mode") == "assignment":
        assignment = entry.get("assignment") or {}
        return " · ".join(filter(None, [
            _name(assignment.get("customer")),
            _name(assignment.get("project")),
            _name(assignment.get("task")),
            _name(assignment.get("hour_type")),
        ])) or _name(assignment)
    mapping = entry.get("direct_mapping") or {}
    return " · ".join(str(v) for v in (
        mapping.get("customer_name"), mapping.get("project_name"),
        mapping.get("service_name"), mapping.get("hour_type_name"),
    ) if v)


def _description(entry: dict[str, Any]) -> str:
    return str((entry.get("source") or {}).get("description") or entry.get("description") or "Untitled")


@st.dialog("Book task to Simplicate", width="large")
def _book_dialog(repo: PlanRepository, plan_id: str, entry_id: str) -> None:
    try:
        with st.spinner("Checking Simplicate for an existing registration…", show_time=True):
            preview = preview_single_entry(repo, plan_id, entry_id)
    except Exception as exc:
        st.error(str(exc))
        return

    entry = preview["entry"]
    st.markdown(f"### {_description(entry)}")
    st.write(_target(entry))
    start = str(entry.get("planned_start") or "")
    end = str(entry.get("planned_end") or "")
    start_hm = start[11:16] if "T" in start else start[-8:-3] if start else ""
    end_hm = end[11:16] if "T" in end else end[-8:-3] if end else ""
    st.caption(
        f"{entry.get('date')} · {start_hm}–{end_hm} · {format_duration(entry.get('planned_duration_seconds'))}"
    )

    if preview["status"] == "already_booked":
        st.success("Timesheet Clerk already has a booking receipt for this task. No second booking will be sent.")
        return
    if preview["status"] == "possible_duplicate":
        st.error("A matching registration already exists in Simplicate. Booking is blocked to prevent a duplicate.")
        return

    st.warning("This action creates one real time registration in Simplicate. Only this task will be written.")
    confirmed = st.checkbox("I checked this task and want to book it", key=f"confirm-book-{plan_id}-{entry_id}")
    if st.button("Book task", type="primary", disabled=not confirmed, use_container_width=True, key=f"execute-book-{plan_id}-{entry_id}"):
        try:
            with st.spinner("Booking and verifying in Simplicate…", show_time=True):
                result = execute_single_entry_booking(repo, plan_id, entry_id)
            if result.get("verified"):
                st.session_state["booking_flash"] = "Task booked and verified in Simplicate"
                st.rerun()
            else:
                st.error(result.get("message") or "Booking was sent but could not be verified. Retry is blocked by the receipt.")
        except Exception as exc:
            st.error(str(exc))


def render_task_booking(repo: PlanRepository, plan: dict[str, Any], entry: dict[str, Any]) -> None:
    ready, reason = task_booking_ready(entry)
    st.divider()
    if entry.get("reconciliation_state") == "BOOKED":
        st.success("Booked in Simplicate")
        return
    if st.button("Book task", type="secondary", disabled=not ready, use_container_width=True, key=f"book-task-{entry.get('entry_id')}"):
        _book_dialog(repo, plan["plan_id"], entry["entry_id"])
    if not ready:
        st.caption(reason)
