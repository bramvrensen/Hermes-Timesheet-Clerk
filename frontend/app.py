"""Timesheet Clerk Streamlit review UI.

Run with: streamlit run frontend/app.py --server.address 127.0.0.1
The UI is deliberately deterministic: it edits the agent-produced plan,
records feedback and creates approval snapshots. It never performs mapping or
LLM work itself.
"""

from __future__ import annotations

import hmac
import os
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timesheet_clerk.review import apply_review, feedback_event
from timesheet_clerk.storage import PlanNotFound, PlanRepository, StateConflict

st.set_page_config(page_title="Timesheet Clerk", page_icon="⏱️", layout="wide")
repo = PlanRepository()


def _login() -> None:
    expected = str(os.environ.get("TIMESHEET_CLERK_UI_PASSWORD") or "").strip()
    if not expected:
        st.error("TIMESHEET_CLERK_UI_PASSWORD is not configured.")
        st.stop()
    if st.session_state.get("timesheet_authenticated"):
        return
    st.title("Timesheet Clerk")
    with st.form("login"):
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Log in")
    if submit:
        if hmac.compare_digest(password, expected):
            st.session_state["timesheet_authenticated"] = True
            st.rerun()
        st.error("Incorrect password")
    st.stop()


def _hours(seconds: Any) -> float:
    try:
        return float(seconds or 0) / 3600.0
    except (TypeError, ValueError):
        return 0.0


def _entry_label(entry: dict[str, Any]) -> str:
    source = entry.get("source") or {}
    description = source.get("description") or entry.get("description") or "Untitled"
    client = (source.get("client") or {}).get("name") if isinstance(source.get("client"), dict) else source.get("client")
    return f"{client + ' · ' if client else ''}{description}"


def _assignment_options(plan: dict[str, Any], entry: dict[str, Any]) -> list[dict[str, Any]]:
    context = plan.get("review_context") or {}
    candidates = context.get("booking_assignments") or []
    day = str(entry.get("date") or "")[:10]
    rows = []
    seen = set()
    for item in candidates:
        if not isinstance(item, dict) or not item.get("id") or item.get("id") in seen:
            continue
        start = str(item.get("start_date") or "")[:10]
        end = str(item.get("end_date") or "")[:10]
        if start and day and start > day:
            continue
        if end and day and end < day:
            continue
        seen.add(item["id"])
        rows.append(item)
    current = entry.get("assignment") or {}
    if current.get("id") and current.get("id") not in seen:
        rows.insert(0, current)
    return rows


def _assignment_label(item: dict[str, Any]) -> str:
    base = item.get("display_label") or " · ".join(
        str(value) for value in (
            (item.get("customer") or {}).get("name") if isinstance(item.get("customer"), dict) else None,
            (item.get("project") or {}).get("name") if isinstance(item.get("project"), dict) else None,
            item.get("name"),
        ) if value
    ) or str(item.get("id"))
    status = item.get("planning_status")
    return f"{base} [{status}]" if status else base


def _direct_context(plan: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    context = plan.get("review_context") or {}
    return {
        "customers": context.get("customers") or [],
        "projects": context.get("projects") or [],
        "services": context.get("services") or [],
        "hour_types": context.get("hour_types") or [],
    }


def _id(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("id")
    return str(value or "")


def _name(row: dict[str, Any]) -> str:
    return str(row.get("name") or row.get("title") or row.get("label") or row.get("id") or "")


def _parent_id(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key in row:
            return _id(row.get(key))
    return ""


def _select_row(label: str, rows: list[dict[str, Any]], current_id: str, key: str, *, disabled: bool = False) -> dict[str, Any] | None:
    options = [None] + rows
    index = next((i for i, row in enumerate(options) if row and _id(row) == current_id), 0)
    return st.selectbox(
        label,
        options,
        index=index,
        format_func=lambda row: "— select —" if row is None else _name(row),
        key=key,
        disabled=disabled,
    )


def _edit_direct(plan: dict[str, Any], entry: dict[str, Any], key_prefix: str) -> dict[str, Any]:
    mapping = deepcopy(entry.get("direct_mapping") or {})
    ctx = _direct_context(plan)
    customer = _select_row("Customer", ctx["customers"], _id(mapping.get("customer_id")), f"{key_prefix}-customer")
    customer_id = _id(customer)
    projects = [row for row in ctx["projects"] if not customer_id or _parent_id(row, "customer_id", "organization_id", "organization") == customer_id]
    project = _select_row("Project", projects, _id(mapping.get("project_id")), f"{key_prefix}-project")
    project_id = _id(project)
    services = [row for row in ctx["services"] if not project_id or _parent_id(row, "project_id", "project") == project_id]
    service = _select_row("Task / service", services, _id(mapping.get("service_id")), f"{key_prefix}-service")
    service_id = _id(service)
    hour_types = [row for row in ctx["hour_types"] if not service_id or not _parent_id(row, "service_id", "projectservice_id", "service") or _parent_id(row, "service_id", "projectservice_id", "service") == service_id]
    hour_type = _select_row("Hour type", hour_types, _id(mapping.get("hour_type_id")), f"{key_prefix}-hourtype")
    return {
        "customer_id": customer_id or None,
        "customer_name": _name(customer) if customer else None,
        "project_id": _id(project) or None,
        "project_name": _name(project) if project else None,
        "service_id": _id(service) or None,
        "service_name": _name(service) if service else None,
        "hour_type_id": _id(hour_type) or None,
        "hour_type_name": _name(hour_type) if hour_type else None,
        "billable": bool(mapping.get("billable", True)),
    }


def _render_entry(plan: dict[str, Any], entry: dict[str, Any]) -> None:
    entry_id = entry["entry_id"]
    tier = entry.get("tier") or entry.get("overall_tier") or "ASK"
    title = f"{entry.get('date')} · {_entry_label(entry)} · {_hours(entry.get('planned_duration_seconds')):.2f} h · {tier}"
    with st.expander(title, expanded=tier != "AUTO"):
        if entry.get("why"):
            st.caption(str(entry["why"]))
        if entry.get("why_not_auto"):
            st.info(f"Why not AUTO: {entry['why_not_auto']}")
        left, right = st.columns([1, 2])
        with left:
            duration_hours = st.number_input(
                "Duration (hours)", min_value=0.0, step=0.25,
                value=_hours(entry.get("planned_duration_seconds")),
                key=f"{entry_id}-duration",
            )
            ignored = st.checkbox("Skip / ignore", value=bool(entry.get("ignored")), key=f"{entry_id}-ignored")
            mode = st.radio(
                "Booking mode", ["assignment", "direct"], horizontal=True,
                index=0 if entry.get("booking_mode") == "assignment" else 1,
                key=f"{entry_id}-mode",
            )
        reviewed: dict[str, Any] = {
            "planned_duration_seconds": round(duration_hours * 3600),
            "booking_mode": mode,
            "ignored": ignored,
        }
        with right:
            if mode == "assignment":
                options = _assignment_options(plan, entry)
                current_id = _id(entry.get("assignment"))
                selected = st.selectbox(
                    "Assignment",
                    options,
                    index=next((i for i, row in enumerate(options) if _id(row) == current_id), 0) if options else None,
                    format_func=_assignment_label,
                    key=f"{entry_id}-assignment",
                    disabled=not options,
                ) if options else None
                reviewed["assignment"] = deepcopy(selected) if selected else {}
                if selected:
                    st.caption(
                        " · ".join(str(v) for v in (
                            (selected.get("service") or {}).get("name") if isinstance(selected.get("service"), dict) else None,
                            (selected.get("hour_type") or {}).get("name") if isinstance(selected.get("hour_type"), dict) else None,
                        ) if v)
                    )
            else:
                reviewed["direct_mapping"] = _edit_direct(plan, entry, entry_id)
        reason = st.text_input("Reason for correction (optional)", key=f"{entry_id}-reason")
        if st.button("Save review", key=f"{entry_id}-save", type="primary" if tier != "AUTO" else "secondary"):
            try:
                opened_revision = int(plan["revision"])
                updated, proposal, reviewed_entry = apply_review(plan, entry_id, reviewed)
                saved = repo.save_revision(updated, expected_revision=opened_revision)
                repo.append_feedback(feedback_event(
                    plan_id=saved["plan_id"], proposal=proposal, reviewed=reviewed_entry, reason=reason,
                ))
                st.success(f"Saved as revision {saved['revision']}")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def main() -> None:
    _login()
    header_left, header_right = st.columns([5, 1])
    with header_left:
        st.title("Timesheet Clerk")
    with header_right:
        if st.button("Log out"):
            st.session_state.clear()
            st.rerun()
    try:
        plan = repo.get_active()
    except PlanNotFound:
        st.info("No active booking plan yet. Ask HERMES to generate one.")
        return

    week = plan["week"]
    st.caption(f"{plan['plan_id']} · revision {plan['revision']} · {plan['status']} · {week['monday']} → {week['sunday']}")
    total_hours = sum(_hours(row.get("planned_duration_seconds")) for row in plan["entries"] if not row.get("ignored"))
    booked_hours = sum(_hours(row.get("planned_duration_seconds")) for row in plan["entries"] if row.get("reconciliation_state") == "BOOKED")
    metrics = st.columns(4)
    metrics[0].metric("Target", f"{float(plan['target_hours']):.2f} h")
    metrics[1].metric("Planned", f"{total_hours:.2f} h", f"{total_hours - float(plan['target_hours']):+.2f} h")
    metrics[2].metric("Already booked", f"{booked_hours:.2f} h")
    metrics[3].metric("Entries", len(plan["entries"]))

    with st.form("week-settings"):
        target = st.number_input("Target hours for this week", min_value=0.0, step=0.5, value=float(plan["target_hours"]))
        if st.form_submit_button("Save target hours"):
            updated = deepcopy(plan)
            updated["target_hours"] = float(target)
            updated["status"] = "IN_REVIEW"
            try:
                repo.save_revision(updated, expected_revision=int(plan["revision"]))
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    days: dict[str, list[dict[str, Any]]] = {}
    for entry in plan["entries"]:
        days.setdefault(str(entry.get("date") or "Unknown"), []).append(entry)
    for day, entries in days.items():
        st.subheader(day)
        for entry in entries:
            _render_entry(plan, entry)

    st.divider()
    st.subheader("Approval")
    st.write("Approval creates an immutable snapshot. Simplicate writes remain disabled until the write path has been live-validated.")
    if st.button("Approve week", type="primary"):
        try:
            snapshot = repo.approve_snapshot(plan["plan_id"], int(plan["revision"]))
            st.success(f"Approved immutable snapshot for {snapshot['plan_id']} revision {snapshot['revision']}")
        except StateConflict as exc:
            st.error(str(exc))


if __name__ == "__main__":
    main()
