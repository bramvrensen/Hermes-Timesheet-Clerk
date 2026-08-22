"""Timesheet Clerk Streamlit review UI.

The UI is deterministic: it reviews the agent-produced plan, records feedback
and exposes booking controls. Mapping and autonomy remain agent responsibilities.
Live Simplicate context is used only to populate valid review choices.
"""

from __future__ import annotations

import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st
from streamlit_cookies_controller import CookieController

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timesheet_clerk.review import apply_review, feedback_event
from timesheet_clerk.storage import PlanNotFound, PlanRepository, StateConflict
from timesheet_clerk.ui_auth import logout, require_login
from timesheet_clerk.ui_context import load_review_context

st.set_page_config(page_title="Timesheet Clerk", page_icon="⏱️", layout="wide")
repo = PlanRepository()

_THEME_COOKIE = "timesheet_clerk_theme"
_THEME_OPTIONS = ("System", "Light", "Dark")
_THEME_CONTROLLER = CookieController(key="timesheet-clerk-theme-cookies")


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


def _format_hm(value: Any) -> str:
    if not value:
        return "--:--"
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.strftime("%H:%M")
    except ValueError:
        if "T" in text:
            return text.split("T", 1)[1][:5]
        if " " in text:
            return text.split(" ", 1)[1][:5]
        return text[:5]


def _time_range(entry: dict[str, Any]) -> str:
    return f"{_format_hm(entry.get('planned_start'))}–{_format_hm(entry.get('planned_end'))}"


def _entry_label(entry: dict[str, Any]) -> str:
    source = entry.get("source") or {}
    description = source.get("description") or entry.get("description") or "Untitled"
    client = source.get("client") or {}
    client_name = client.get("name") if isinstance(client, dict) else str(client or "")
    return f"{client_name + ' · ' if client_name else ''}{description}"


def _entry_source_line(entry: dict[str, Any]) -> str:
    source = entry.get("source") or {}
    bits: list[str] = []
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


def _current_theme() -> str:
    cookie = ""
    try:
        cookie = str(st.context.cookies.get(_THEME_COOKIE) or "")
    except Exception:
        cookie = ""
    selected = str(st.session_state.get("timesheet_theme") or cookie or "system").lower()
    return selected if selected in {"system", "light", "dark"} else "system"


def _set_theme(theme: str) -> None:
    normalized = theme.lower()
    st.session_state["timesheet_theme"] = normalized
    _THEME_CONTROLLER.set(
        _THEME_COOKIE,
        normalized,
        path="/",
        max_age=365 * 24 * 60 * 60,
        secure=True,
        same_site="strict",
    )


def _theme_css(theme: str) -> str:
    light = """
        --tc-bg: #ffffff; --tc-surface: #f7f8fa; --tc-card: #ffffff;
        --tc-text: #1f2328; --tc-muted: #667085; --tc-border: #d8dee4;
        --tc-auto-bg: #f2fbf5; --tc-propose-bg: #fff9e8; --tc-ask-bg: #fff1f1;
        --tc-booked-bg: #f3f4f6; --tc-accent: #2563eb;
    """
    dark = """
        --tc-bg: #0e1117; --tc-surface: #161b22; --tc-card: #11161d;
        --tc-text: #e6edf3; --tc-muted: #9aa4b2; --tc-border: #30363d;
        --tc-auto-bg: #10251a; --tc-propose-bg: #2b2412; --tc-ask-bg: #2b1719;
        --tc-booked-bg: #1b2028; --tc-accent: #60a5fa;
    """
    if theme == "dark":
        vars_block = dark
        media = ""
    elif theme == "light":
        vars_block = light
        media = ""
    else:
        vars_block = light
        media = f"@media (prefers-color-scheme: dark) {{ :root {{ {dark} }} }}"
    return f"""
    <style>
    :root {{ {vars_block} }}
    {media}
    html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{ background: var(--tc-bg); color: var(--tc-text); }}
    [data-testid="stHeader"] {{ background: color-mix(in srgb, var(--tc-bg) 90%, transparent); }}
    .block-container {{ padding-top: 1.25rem; padding-bottom: 3rem; max-width: 1500px; }}
    .tc-week-title {{ text-align:center; font-weight:700; padding-top:.45rem; color:var(--tc-text); }}
    .tc-day-head {{ display:flex; align-items:center; justify-content:space-between; margin-top:1.3rem; margin-bottom:.4rem; }}
    .tc-day-title {{ font-size:1.15rem; font-weight:700; color:var(--tc-text); }}
    .tc-day-meta {{ color:var(--tc-muted); font-size:.85rem; }}
    .tc-entry {{ border:1px solid var(--tc-border); border-left-width:5px; border-radius:10px; padding:.65rem .85rem; margin:.45rem 0 .25rem 0; background:var(--tc-card); }}
    .tc-entry.auto {{ border-left-color:#2da44e; background:var(--tc-auto-bg); }}
    .tc-entry.propose {{ border-left-color:#d29922; background:var(--tc-propose-bg); }}
    .tc-entry.ask {{ border-left-color:#cf222e; background:var(--tc-ask-bg); }}
    .tc-entry.booked {{ border-left-color:#6e7781; background:var(--tc-booked-bg); opacity:.82; }}
    .tc-entry.skip {{ border-left-color:#8c959f; opacity:.6; }}
    .tc-row {{ display:grid; grid-template-columns:110px 80px minmax(260px,1fr) minmax(260px,1.25fr) auto; gap:.8rem; align-items:center; }}
    .tc-time {{ font-weight:750; font-variant-numeric:tabular-nums; color:var(--tc-text); }}
    .tc-hours {{ font-weight:700; color:var(--tc-text); }}
    .tc-main {{ min-width:0; }}
    .tc-title {{ font-weight:650; color:var(--tc-text); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .tc-sub {{ color:var(--tc-muted); font-size:.78rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .tc-target {{ color:var(--tc-text); font-size:.85rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .tc-badge {{ display:inline-block; padding:.18rem .5rem; border-radius:999px; font-size:.7rem; font-weight:800; letter-spacing:.02em; white-space:nowrap; }}
    .tc-badge.auto {{ background:#2da44e; color:white; }}
    .tc-badge.propose {{ background:#d29922; color:#111; }}
    .tc-badge.ask {{ background:#cf222e; color:white; }}
    .tc-badge.booked {{ background:#6e7781; color:white; }}
    .tc-badge.skip {{ background:#8c959f; color:white; }}
    .tc-review-note {{ border-left:3px solid #d29922; padding:.4rem .65rem; margin:.25rem 0 .65rem; color:var(--tc-muted); font-size:.88rem; }}
    [data-testid="stMetric"] {{ background:var(--tc-surface); border:1px solid var(--tc-border); padding:.55rem .7rem; border-radius:10px; }}
    [data-testid="stExpander"] {{ border-color:var(--tc-border); background:var(--tc-card); }}
    @media (max-width: 900px) {{ .tc-row {{ grid-template-columns:90px 65px 1fr auto; }} .tc-target {{ grid-column:3 / 5; }} }}
    </style>
    """


def _render_theme_picker() -> None:
    current = _current_theme()
    labels = {"system": "System", "light": "Light", "dark": "Dark"}
    chosen = st.radio(
        "Appearance",
        _THEME_OPTIONS,
        index=_THEME_OPTIONS.index(labels[current]),
        horizontal=True,
        label_visibility="collapsed",
        key="theme-selector",
    )
    if chosen.lower() != current:
        _set_theme(chosen)
    st.markdown(_theme_css(chosen.lower()), unsafe_allow_html=True)


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
        return _assignment_label(row) if row else current_id or "No assignment"
    mapping = entry.get("direct_mapping") or {}
    return " · ".join(str(value) for value in (
        mapping.get("customer_name"), mapping.get("project_name"), mapping.get("service_name"), mapping.get("hour_type_name")
    ) if value) or "Direct mapping incomplete"


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
    projects = [row for row in (ctx.get("projects") or []) if not customer_id or _plain_id(row.get("customer_id")) == customer_id]
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


def _clean_plan(plan: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(plan)
    result.pop("review_context", None)
    return result


def _save_review(plan: dict[str, Any], entry: dict[str, Any], reviewed: dict[str, Any], reason: str) -> None:
    opened_revision = int(plan["revision"])
    updated, proposal, reviewed_entry = apply_review(_clean_plan(plan), entry["entry_id"], reviewed)
    saved = repo.save_revision(updated, expected_revision=opened_revision)
    repo.append_feedback(feedback_event(plan_id=saved["plan_id"], proposal=proposal, reviewed=reviewed_entry, reason=reason))
    st.rerun()


def _adjust_duration(plan: dict[str, Any], entry: dict[str, Any], delta_seconds: int | None = None, reset: bool = False) -> None:
    current = int(entry.get("planned_duration_seconds") or 0)
    original = int(entry.get("original_duration_seconds") or current)
    target = original if reset else max(900, current + int(delta_seconds or 0))
    if target == current:
        return
    _save_review(plan, entry, {"planned_duration_seconds": target}, f"duration adjusted to {target / 3600:.2f}h")


def _pending_reviews(entries: list[dict[str, Any]]) -> int:
    return sum(
        1 for entry in entries
        if not entry.get("ignored")
        and (entry.get("tier") or entry.get("overall_tier")) in {"PROPOSE", "ASK"}
        and entry.get("review_state") not in {"confirmed", "corrected", "skipped"}
    )


def _status(entry: dict[str, Any]) -> str:
    if entry.get("ignored") or entry.get("review_state") == "skipped":
        return "SKIP"
    if entry.get("reconciliation_state") == "BOOKED":
        return "BOOKED"
    return str(entry.get("tier") or entry.get("overall_tier") or "ASK")


def _render_entry_summary(plan: dict[str, Any], entry: dict[str, Any]) -> None:
    status = _status(entry)
    css_status = status.lower()
    clocked = _hours(entry.get("original_duration_seconds"))
    planned = _hours(entry.get("planned_duration_seconds"))
    diff = planned - clocked
    diff_text = f" · {diff:+.2f}h" if abs(diff) >= 0.01 else ""
    target = _target_line(entry, plan)
    source = _entry_source_line(entry) or _entry_label(entry)
    st.markdown(
        f"""
        <div class="tc-entry {css_status}">
          <div class="tc-row">
            <div class="tc-time">{_time_range(entry)}</div>
            <div class="tc-hours">{planned:.2f}h</div>
            <div class="tc-main">
              <div class="tc-title">{_entry_label(entry)}</div>
              <div class="tc-sub">Clockify: {source} · {clocked:.2f}h{diff_text}</div>
            </div>
            <div class="tc-target">→ {target}</div>
            <div><span class="tc-badge {css_status}">{status}</span></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_duration_controls(plan: dict[str, Any], entry: dict[str, Any]) -> None:
    cols = st.columns([1.15, .75, .75, .75, .75, .75, .9, 4])
    current = _hours(entry.get("planned_duration_seconds"))
    original = _hours(entry.get("original_duration_seconds"))
    with cols[0]:
        edited = st.number_input(
            "Hours",
            min_value=0.25,
            max_value=24.0,
            value=float(current),
            step=0.25,
            format="%.2f",
            key=f"duration-{entry['entry_id']}-{plan['revision']}",
            label_visibility="collapsed",
        )
        if abs(edited - current) >= 0.001:
            _save_review(plan, entry, {"planned_duration_seconds": round(edited * 3600)}, "duration edited")
    actions = [(-3600, "−1h"), (-1800, "−30"), (-900, "−15"), (900, "+15"), (1800, "+30")]
    for col, (delta, label) in zip(cols[1:6], actions):
        with col:
            if st.button(label, key=f"duration-{delta}-{entry['entry_id']}", use_container_width=True):
                _adjust_duration(plan, entry, delta_seconds=delta)
    with cols[6]:
        if st.button("Reset", key=f"duration-reset-{entry['entry_id']}", disabled=abs(current - original) < .001, use_container_width=True):
            _adjust_duration(plan, entry, reset=True)


def _render_editor(plan: dict[str, Any], entry: dict[str, Any]) -> None:
    status = _status(entry)
    needs_review = status in {"PROPOSE", "ASK"} and entry.get("review_state") not in {"confirmed", "corrected", "skipped"}
    label = "Review / edit" if not needs_review else "Review required"
    with st.expander(label, expanded=needs_review):
        if entry.get("why_not_auto"):
            st.markdown(f"<div class='tc-review-note'><strong>Why review:</strong> {entry['why_not_auto']}</div>", unsafe_allow_html=True)
        elif entry.get("why"):
            st.caption(str(entry["why"]))

        st.caption("Duration")
        _render_duration_controls(plan, entry)

        left, right = st.columns([1, 2])
        with left:
            ignored = st.checkbox("Skip / ignore", value=bool(entry.get("ignored")), key=f"ignored-{entry['entry_id']}")
            mode = st.radio(
                "Booking mode",
                ["assignment", "direct"],
                horizontal=True,
                index=0 if entry.get("booking_mode") == "assignment" else 1,
                key=f"mode-{entry['entry_id']}",
            )

        reviewed: dict[str, Any] = {"booking_mode": mode, "ignored": ignored}
        with right:
            if mode == "assignment":
                options = _assignment_options(plan, entry)
                current_id = _plain_id(entry.get("assignment"))
                selected = st.selectbox(
                    "Assignment",
                    options,
                    index=next((i for i, row in enumerate(options) if _plain_id(row) == current_id), 0) if options else None,
                    format_func=_assignment_label,
                    key=f"assignment-{entry['entry_id']}",
                    disabled=not options,
                ) if options else None
                reviewed["assignment"] = deepcopy(selected) if selected else {}
                if selected:
                    project = selected.get("project") or {}
                    task = selected.get("task") or {}
                    hour_type = selected.get("hour_type") or {}
                    st.caption(" · ".join(str(v) for v in (
                        project.get("name") if isinstance(project, dict) else None,
                        task.get("name") if isinstance(task, dict) else None,
                        hour_type.get("name") if isinstance(hour_type, dict) else None,
                    ) if v))
            else:
                reviewed["direct_mapping"] = _edit_direct(plan, entry, entry["entry_id"])

        reason = st.text_input("Reason / learning note", key=f"reason-{entry['entry_id']}")
        save_label = "Accept proposal" if needs_review else "Save changes"
        if st.button(save_label, type="primary" if needs_review else "secondary", key=f"save-{entry['entry_id']}"):
            try:
                _save_review(plan, entry, reviewed, reason)
            except Exception as exc:
                st.error(str(exc))


def _render_day(plan: dict[str, Any], day: str, entries: list[dict[str, Any]]) -> None:
    clocked = sum(_hours(row.get("original_duration_seconds")) for row in entries)
    workable = sum(_hours(row.get("planned_duration_seconds")) for row in entries if not row.get("ignored"))
    booked = sum(_hours(row.get("planned_duration_seconds")) for row in entries if row.get("reconciliation_state") == "BOOKED")
    pending = _pending_reviews(entries)
    status_text = f"{pending} review" if pending else "ready"

    head, action = st.columns([5, 1])
    with head:
        st.markdown(
            f"<div class='tc-day-head'><div><div class='tc-day-title'>{day}</div><div class='tc-day-meta'>Clocked {clocked:.2f}h · Workable {workable:.2f}h · Booked {booked:.2f}h · {status_text}</div></div></div>",
            unsafe_allow_html=True,
        )
    with action:
        st.button(
            "Book day",
            key=f"book-day-{day}",
            disabled=True,
            help="Visible by design, but Simplicate writes stay locked until the controlled write validation succeeds.",
            use_container_width=True,
        )

    for entry in entries:
        _render_entry_summary(plan, entry)
        _render_editor(plan, entry)


def _plan_catalog() -> list[dict[str, Any]]:
    rows = repo.list_plans(limit=100)
    rows.sort(key=lambda row: str((row.get("week") or {}).get("monday") or ""))
    return rows


def _select_plan() -> dict[str, Any]:
    active = repo.get_active()
    catalog = _plan_catalog()
    ids = [row["plan_id"] for row in catalog]
    if "selected_plan_id" not in st.session_state or st.session_state["selected_plan_id"] not in ids:
        st.session_state["selected_plan_id"] = active["plan_id"]
    selected_id = st.session_state["selected_plan_id"]
    index = ids.index(selected_id) if selected_id in ids else len(ids) - 1

    title_col, nav_col, theme_col, logout_col = st.columns([4.2, 3.3, 2.2, 1.1])
    with title_col:
        st.markdown("## ⏱️ Timesheet Clerk")
    with nav_col:
        prev_col, label_col, next_col = st.columns([1, 4, 1])
        with prev_col:
            if st.button("◀", disabled=index <= 0, use_container_width=True):
                st.session_state["selected_plan_id"] = ids[index - 1]
                st.rerun()
        row = catalog[index]
        week = row.get("week") or {}
        monday = str(week.get("monday") or "")
        sunday = str(week.get("sunday") or "")
        try:
            week_num = datetime.fromisoformat(monday).isocalendar().week
            label = f"Week {week_num} · {monday[5:]} → {sunday[5:]}"
        except ValueError:
            label = f"{monday} → {sunday}"
        with label_col:
            st.markdown(f"<div class='tc-week-title'>{label}</div>", unsafe_allow_html=True)
        with next_col:
            if st.button("▶", disabled=index >= len(ids) - 1, use_container_width=True):
                st.session_state["selected_plan_id"] = ids[index + 1]
                st.rerun()
    with theme_col:
        _render_theme_picker()
    with logout_col:
        if st.button("Log out", use_container_width=True):
            logout()

    return repo.get_latest(selected_id)


def main() -> None:
    require_login()
    try:
        stored_plan = _select_plan()
    except PlanNotFound:
        st.info("No booking plan yet. Ask HERMES to generate one.")
        return

    try:
        plan = _with_live_context(stored_plan)
    except Exception as exc:
        st.error(f"Could not load Simplicate review choices: {exc}")
        plan = deepcopy(stored_plan)
        plan["review_context"] = {}

    entries = plan["entries"]
    total_clocked = sum(_hours(row.get("original_duration_seconds")) for row in entries)
    workable = sum(_hours(row.get("planned_duration_seconds")) for row in entries if not row.get("ignored"))
    booked = sum(_hours(row.get("planned_duration_seconds")) for row in entries if row.get("reconciliation_state") == "BOOKED")
    open_hours = max(0.0, workable - booked)
    target = float(plan["target_hours"])
    pending_total = _pending_reviews(entries)

    st.caption(f"{plan['plan_id']} · revision {plan['revision']} · {plan['status']}")

    metrics = st.columns(5)
    metrics[0].metric("📋 Target", f"{target:.1f}h")
    metrics[1].metric("⏱️ Clocked", f"{total_clocked:.1f}h", f"{total_clocked - target:+.1f}h vs target")
    metrics[2].metric("💼 Workable", f"{workable:.1f}h")
    metrics[3].metric("✅ Booked", f"{booked:.1f}h")
    metrics[4].metric("⏳ Open", f"{open_hours:.1f}h")

    if abs(workable - target) >= .01:
        st.warning(f"Planned/workable time is {workable - target:+.2f}h versus the {target:.2f}h weekly target.")
    if pending_total:
        st.info(f"{pending_total} PROPOSE/ASK entries still need review.")

    with st.expander("Week settings", expanded=False):
        target_value = st.number_input("Target hours", min_value=0.0, step=0.5, value=target)
        if st.button("Save target", key="save-target"):
            updated = deepcopy(stored_plan)
            updated["target_hours"] = float(target_value)
            updated["status"] = "IN_REVIEW"
            repo.save_revision(updated, expected_revision=int(stored_plan["revision"]))
            st.rerun()

    days: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        days.setdefault(str(entry.get("date") or "Unknown"), []).append(entry)
    for day in sorted(days):
        _render_day(plan, day, days[day])

    st.divider()
    st.subheader("Week actions")
    if pending_total:
        st.warning(f"Review the remaining {pending_total} entries before approval.")
    else:
        st.success("All PROPOSE/ASK entries are reviewed. The plan is ready for approval.")

    approve_col, book_col = st.columns(2)
    with approve_col:
        if st.button("Approve week", disabled=bool(pending_total), use_container_width=True):
            try:
                snapshot = repo.approve_snapshot(stored_plan["plan_id"], int(stored_plan["revision"]))
                st.success(f"Approved {snapshot['plan_id']} revision {snapshot['revision']}")
            except StateConflict as exc:
                st.error(str(exc))
    with book_col:
        st.button(
            "Book approved week",
            type="primary",
            disabled=True,
            help="Simplicate writes are locked until the controlled write-path validation succeeds.",
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
