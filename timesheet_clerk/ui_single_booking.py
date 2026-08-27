"""Human-readable single-task booking UI for Streamlit.

The review editor itself is already a Streamlit dialog. Streamlit forbids nested
``st.dialog`` calls, so task-booking confirmation is deliberately rendered inline
inside that existing review surface.
"""
from __future__ import annotations

import json
from typing import Any

import streamlit as st

from .http import IntegrationError
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


def _confirmation_key(plan_id: str, entry_id: str) -> str:
    return f"show-book-confirm-{plan_id}-{entry_id}"


def _preflight_key(plan_id: str, revision: Any, entry_id: str) -> str:
    return f"book-preflight-{plan_id}-{revision}-{entry_id}"


def _clear_booking_state(plan_id: str, entry_id: str) -> None:
    st.session_state.pop(_confirmation_key(plan_id, entry_id), None)
    prefix = f"book-preflight-{plan_id}-"
    suffix = f"-{entry_id}"
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith(prefix) and key.endswith(suffix):
            st.session_state.pop(key, None)


def _safe_error_text(exc: Exception) -> str:
    if not isinstance(exc, IntegrationError):
        return str(exc)
    head = exc.message
    if exc.status_code is not None:
        head = f"{head} · HTTP {exc.status_code}"
    details = exc.details
    if details in (None, "", {}, []):
        return head
    try:
        detail_text = json.dumps(details, ensure_ascii=False, indent=2, sort_keys=True)
    except TypeError:
        detail_text = str(details)
    detail_text = detail_text[:4000]
    return f"{head}\n\n{detail_text}"


def _show_error(exc: Exception) -> None:
    st.error(_safe_error_text(exc))


def _render_booking_confirmation(repo: PlanRepository, plan_id: str, revision: Any, entry_id: str) -> None:
    """Render one cached preflight and confirmation inline in the review dialog."""
    cache_key = _preflight_key(plan_id, revision, entry_id)
    preview = st.session_state.get(cache_key)
    if preview is None:
        try:
            with st.spinner("Checking Simplicate for an existing registration…", show_time=True):
                preview = preview_single_entry(repo, plan_id, entry_id)
            st.session_state[cache_key] = preview
        except Exception as exc:
            _show_error(exc)
            return

    entry = preview["entry"]
    st.markdown(f"#### Book to Simplicate · {_description(entry)}")
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

    st.warning("This creates one real time registration in Simplicate. Only this task will be written.")
    confirmed = st.checkbox(
        "I checked this task and want to book it",
        key=f"confirm-book-{plan_id}-{entry_id}",
    )
    actions = st.columns([1, 1])
    with actions[0]:
        if st.button(
            "Confirm booking",
            type="primary",
            disabled=not confirmed,
            use_container_width=True,
            key=f"execute-book-{plan_id}-{entry_id}",
        ):
            try:
                with st.spinner("Booking and verifying in Simplicate…", show_time=True):
                    result = execute_single_entry_booking(repo, plan_id, entry_id, prepared_preview=preview)
                if result.get("verified"):
                    _clear_booking_state(plan_id, entry_id)
                    st.session_state["booking_flash"] = "Task booked and verified in Simplicate"
                    st.rerun()
                else:
                    st.error(result.get("message") or "Booking was sent but could not be verified. Retry is blocked by the receipt.")
            except Exception as exc:
                _show_error(exc)
    with actions[1]:
        if st.button("Cancel", use_container_width=True, key=f"cancel-book-{plan_id}-{entry_id}"):
            _clear_booking_state(plan_id, entry_id)
            st.rerun()


def render_task_booking(repo: PlanRepository, plan: dict[str, Any], entry: dict[str, Any]) -> None:
    ready, reason = task_booking_ready(entry)
    plan_id = str(plan["plan_id"])
    revision = plan.get("revision")
    entry_id = str(entry["entry_id"])
    panel_key = _confirmation_key(plan_id, entry_id)

    st.divider()
    if entry.get("reconciliation_state") == "BOOKED":
        _clear_booking_state(plan_id, entry_id)
        st.success("Booked in Simplicate")
        return

    if not st.session_state.get(panel_key):
        if st.button(
            "Book task",
            type="secondary",
            disabled=not ready,
            use_container_width=True,
            key=f"book-task-{entry_id}",
        ):
            st.session_state[panel_key] = True
    if not ready:
        st.caption(reason)
        return

    if st.session_state.get(panel_key):
        _render_booking_confirmation(repo, plan_id, revision, entry_id)
