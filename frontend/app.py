"""Timesheet Clerk Streamlit review UI.

The UI is deterministic: it reviews the agent-produced plan, records feedback
and exposes booking controls. Mapping and autonomy remain agent responsibilities.
Live Simplicate context is used only to populate valid review choices.
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timesheet_clerk.review import apply_review, feedback_event
from timesheet_clerk.storage import PlanNotFound, PlanRepository, StateConflict
from timesheet_clerk.ui_auth import logout, require_login
from timesheet_clerk.ui_context import load_review_context

st.set_page_config(page_title="Timesheet Clerk", page_icon="⏱️", layout="wide")
repo = PlanRepository()

WEEKDAYS = {
    0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
    4: "Friday", 5: "Saturday", 6: "Sunday",
}


def _hours(seconds: Any) -> float:
    try:
        return float(seconds or 0) / 3600.0
    except (TypeError, ValueError):
        return 0.0


def _plain_id(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("id")
    text = str(value or "")
    return text.split(":", 1)[1] if ":" in text else text


def _name(row: dict[str, Any] | None) -> str:
    row = row or {}
    return str(row.get("name") or row.get("title") or row.get("label") or row.get("id") or "")


def _entry_label(entry: dict[str, Any]) -> str:
    source = entry.get("source") or {}
    description = source.get("description") or entry.get("description") or "Untitled"
    client = source.get("client") or {}
    client_name = client.get("name") if isinstance(client, dict) else str(client or "")
    return f"{client_name + ' · ' if client_name else ''}{description}"


def _entry_source_line(entry: dict[str, Any]) -> str:
    source = entry.get("source") or {}
    bits = []
    project = source.get("project") or {}
    client = source.get("client") or {}
    if isinstance(client, dict) and client.get("name"):
        bits.append(str(client["name"]))
    if isinstance(project, dict) and project.get("name"):
        bits.append(str(project["name"]))
    description = source.get("description") or entry.get("description")
    if description:
        bits.append(str(description))
    return " · ".join(bits)


@st.cache_data(ttl=300, show_spinner=False)
def _review_context(start_date: str, end_date: str) -> dict[str, list[dict[str, Any]]]:
    return load_review_context(start_date, end_date)


def _with_live_context(plan: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(plan)
    week = result["week"]
    result["review_context"] = _review_context(week["monday"], week["sunday"])
    return result


def _assignment_options(plan: dict[str, Any], entry: dict[str, Any]) -> list[dict[str, Any]]:
    context = plan.get("review_context") or {}
    candidates = context.get("booking_assignments") or []
    day = str(entry.get("date") or "")[:10]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        item_id = _plain_id(item.get("id")) if isinstance(item, dict) else ""
        if not item_id or item_id in seen:
            continue
        start = str(item.get("start_date") or "")[:10]
        end = str(item.get("end_date") or "")[:10]
        if start and day and start > day:
            continue
        if end and day and end < day:
            continue
        seen.add(item_id)
        rows.append(item)

    current = entry.get("assignment") or {}
    current_id = _plain_id(current)
    if current_id and current_id not in seen:
        enriched = next((row for row in candidates if _plain_id(row) == current_id), None)
        rows.insert(0, deepcopy(enriched or current))
    return rows


def _assignment_label(item: dict[str, Any]) -> str:
    base = item.get("display_label") or " · ".join(
        str(value) for value in (
            (item.get("customer") or {}).get("name") if isinstance(item.get("customer"), dict) else None,
            (item.get("project") or {}).get("name") if isinstance(item.get("project"), dict) else None,
            item.get("name"),
        ) if value
    ) or _plain_id(item)
    status = item.get("planning_status")
    return f"{base} · {status}" if status else base


def _target_line(entry: dict[str, Any], plan: dict[str, Any]) -> str:
    if entry.get("booking_mode") == "assignment":
        current_id = _plain_id(entry.get("assignment"))
        row = next((row for row in _assignment_options(plan, entry) if _plain_id(row) == current_id), None)
        return _assignment_label(row) if row else current_id
    mapping = entry.get("direct_mapping") or {}
    return " · ".join(str(value) for value in (
        mapping.get("customer_name"), mapping.get("project_name"), mapping.get("service_name"), mapping.get("hour_type_name")
    ) if value) or "Direct mapping"


def _select_row(label: str, rows: list[dict[str, Any]], current_id: str, key: str) -> dict[str, Any] | None:
    options: list[dict[str, Any] | None] = [None] + rows
    current_id = _plain_id(current_id)
    index = next((i for i, row in enumerate(options) if row and _plain_id(row) == current_id), 0)
    return st.selectbox(
        label,
        options,
        index=index,
        format_func=lambda row: "— select —" if row is None else _name(row),
        key=key,
    )


def _edit_direct(plan: dict[str, Any], entry: dict[str, Any], key_prefix: str) -> dict[str, Any]:
    mapping = deepcopy(entry.get("direct_mapping") or {})
    ctx = plan.get("review_context") or {}

    customer = _select_row("Customer", ctx.get("customers") or [], mapping.get("customer_id") or "", f"{key_prefix}-customer")
    customer_id = _plain_id(customer)

    projects = [
        row for row in (ctx.get("projects") or [])
        if not customer_id or _plain_id(row.get("customer_id")) == customer_id
    ]
    project = _select_row("Project", projects, mapping.get("project_id") or "", f"{key_prefix}-project")
    project_id = _plain_id(project)

    all_services = ctx.get("services") or []
    services = [row for row in all_services if not project_id or not row.get("project_id") or _plain_id(row.get("project_id")) == project_id]
    service = _select_row("Task / service", services, mapping.get("service_id") or "", f"{key_prefix}-service")
    service_id = _plain_id(service)

    all_hour_types = ctx.get("hour_types") or []
    hour_types = [row for row in all_hour_types if not service_id or not row.get("service_id") or _plain_id(row.get("service_id")) == service_id]
    hour_type = _select_row("Hour type", hour_types, mapping.get("hour_type_id") or "", f"{key_prefix}-hourtype")

    return {
        "customer_id": customer_id or None,
        "customer_name": _name(customer) if customer else None,
        "project_id": project_id or None,
        "project_name": _name(project) if project else None,
        "service_id": service_id or None,
        "service_name": _name(service) if service else None,
        "hour_type_id": _plain_id(hour_type) or None,
        "hour_type_name": _name(hour_type) if hour_type else None,
        "billable": bool(mapping.get("billable", True)),
    }


def _save_review(plan: dict[str, Any], entry: dict[str, Any], reviewed: dict[str, Any], reason: str) -> None:
    opened_revision = int(plan["revision"])
    clean_plan = deepcopy(plan)
    clean_plan.pop("review_context", None)
    updated, proposal, reviewed_entry = apply_review(clean_plan, entry["entry_id"], reviewed)
    saved = repo.save_revision(updated, expected_revision=opened_revision)
    repo.append_feedback(feedback_event(
        plan_id=saved["plan_id"], proposal=proposal, reviewed=reviewed_entry, reason=reason,
    ))
    st.success(f"Saved revision {saved['revision']}")
    st.rerun()


def _render_entry(plan: dict[str, Any], entry: dict[str, Any]) -> None:
    entry_id = entry["entry_id"]
    tier = entry.get("tier") or entry.get("overall_tier") or "ASK"
    review_state = entry.get("review_state") or "pending"
    icon = "✓" if review_state in {"confirmed", "corrected"} or tier == "AUTO" else "⚠"
    title = f"{icon} {_entry_label(entry)} · {_hours(entry.get('planned_duration_seconds')):.2f} h · {tier}"

    with st.expander(title, expanded=tier != "AUTO" and review_state not in {"confirmed", "corrected"}):
        source_col, target_col = st.columns(2)
        with source_col:
            st.caption("Clockify")
            st.write(_entry_source_line(entry) or "No source context")
        with target_col:
            st.caption("Proposed Simplicate target")
            st.write(_target_line(entry, plan))

        if entry.get("why_not_auto"):
            st.info(f"Review reason: {entry['why_not_auto']}")
        elif entry.get("why"):
            st.caption(str(entry["why"]))

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
                current_id = _plain_id(entry.get("assignment"))
                selected = st.selectbox(
                    "Assignment",
                    options,
                    index=next((i for i, row in enumerate(options) if _plain_id(row) == current_id), 0) if options else None,
                    format_func=_assignment_label,
                    key=f"{entry_id}-assignment",
                    disabled=not options,
                ) if options else None
                reviewed["assignment"] = deepcopy(selected) if selected else {}
                if selected:
                    task = selected.get("task") or {}
                    hour_type = selected.get("hour_type") or {}
                    st.caption(" · ".join(str(v) for v in (
                        task.get("name") if isinstance(task, dict) else None,
                        hour_type.get("name") if isinstance(hour_type, dict) else None,
                    ) if v))
            else:
                reviewed["direct_mapping"] = _edit_direct(plan, entry, entry_id)

        reason = st.text_input("Correction note (optional)", key=f"{entry_id}-reason")
        label = "Accept proposal" if tier in {"PROPOSE", "ASK"} and review_state == "pending" else "Save changes"
        if st.button(label, key=f"{entry_id}-save", type="primary" if tier != "AUTO" else "secondary"):
            try:
                _save_review(plan, entry, reviewed, reason)
            except Exception as exc:
                st.error(str(exc))


def _pending_reviews(entries: list[dict[str, Any]]) -> int:
    return sum(
        1 for entry in entries
        if not entry.get("ignored")
        and (entry.get("tier") or entry.get("overall_tier")) in {"PROPOSE", "ASK"}
        and entry.get("review_state") not in {"confirmed", "corrected", "skipped"}
    )


def _render_day(plan: dict[str, Any], day: str, entries: list[dict[str, Any]]) -> None:
    day_hours = sum(_hours(row.get("planned_duration_seconds")) for row in entries if not row.get("ignored"))
    pending = _pending_reviews(entries)

    head, action = st.columns([5, 1])
    with head:
        st.subheader(f"{day} · {day_hours:.2f} h")
        if pending:
            st.caption(f"{pending} entr{'y' if pending == 1 else 'ies'} still need review")
        else:
            st.caption("Ready for booking")
    with action:
        st.button(
            "Book day",
            key=f"book-day-{day}",
            disabled=True,
            help="Simplicate writes are not activated yet. The button will unlock after the controlled write validation.",
            use_container_width=True,
        )

    for entry in entries:
        _render_entry(plan, entry)


def main() -> None:
    require_login()

    header_left, header_right = st.columns([5, 1])
    with header_left:
        st.title("Timesheet Clerk")
    with header_right:
        if st.button("Log out", use_container_width=True):
            logout()

    try:
        stored_plan = repo.get_active()
    except PlanNotFound:
        st.info("No active booking plan yet. Ask HERMES to generate one.")
        return

    try:
        plan = _with_live_context(stored_plan)
    except Exception as exc:
        st.error(f"Could not load Simplicate review choices: {exc}")
        plan = deepcopy(stored_plan)
        plan["review_context"] = {}

    week = plan["week"]
    pending_total = _pending_reviews(plan["entries"])
    total_hours = sum(_hours(row.get("planned_duration_seconds")) for row in plan["entries"] if not row.get("ignored"))
    booked_hours = sum(_hours(row.get("planned_duration_seconds")) for row in plan["entries"] if row.get("reconciliation_state") == "BOOKED")

    st.caption(f"{plan['plan_id']} · revision {plan['revision']} · {plan['status']} · {week['monday']} → {week['sunday']}")

    metrics = st.columns(5)
    metrics[0].metric("Target", f"{float(plan['target_hours']):.2f} h")
    metrics[1].metric("Planned", f"{total_hours:.2f} h", f"{total_hours - float(plan['target_hours']):+.2f} h")
    metrics[2].metric("Already booked", f"{booked_hours:.2f} h")
    metrics[3].metric("Needs review", pending_total)
    metrics[4].metric("Entries", len(plan["entries"]))

    with st.expander("Week settings", expanded=False):
        with st.form("week-settings"):
            target = st.number_input("Target hours for this week", min_value=0.0, step=0.5, value=float(plan["target_hours"]))
            if st.form_submit_button("Save target hours"):
                updated = deepcopy(stored_plan)
                updated["target_hours"] = float(target)
                updated["status"] = "IN_REVIEW"
                try:
                    repo.save_revision(updated, expected_revision=int(stored_plan["revision"]))
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    days: dict[str, list[dict[str, Any]]] = {}
    for entry in plan["entries"]:
        days.setdefault(str(entry.get("date") or "Unknown"), []).append(entry)

    for day in sorted(days):
        _render_day(plan, day, days[day])

    st.divider()
    st.subheader("Week booking")
    if pending_total:
        st.warning(f"{pending_total} entries still require review before this week can be approved or booked.")
    else:
        st.success("All PROPOSE/ASK entries are reviewed. The plan is ready for approval.")

    approve_col, book_col = st.columns(2)
    with approve_col:
        if st.button("Approve week", type="secondary", disabled=bool(pending_total), use_container_width=True):
            try:
                snapshot = repo.approve_snapshot(stored_plan["plan_id"], int(stored_plan["revision"]))
                st.success(f"Approved immutable snapshot for {snapshot['plan_id']} revision {snapshot['revision']}")
            except StateConflict as exc:
                st.error(str(exc))
    with book_col:
        st.button(
            "Book approved week",
            type="primary",
            disabled=True,
            help="Simplicate writes are not activated yet. This unlocks after the controlled write validation.",
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
