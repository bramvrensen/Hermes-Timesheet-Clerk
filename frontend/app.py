"""Timesheet Clerk Streamlit shell for the 0.6 deterministic planner workflow."""
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
from timesheet_clerk.ui_booking import render_booking
from timesheet_clerk.ui_planner import start_planner
from timesheet_clerk.ui_sync import clear_sync_status, sync_status


def _current_week() -> tuple[str, str]:
    tz = ZoneInfo(os.environ.get("TZ") or "Europe/Amsterdam")
    today = datetime.now(tz).date()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def _render_job_status() -> None:
    status = sync_status(review.repo.root)
    if not status:
        return
    state = str(status.get("status") or "").upper()
    message = str(status.get("message") or "")
    if state in {"STARTING", "RUNNING"}:
        st.info(message or "Planner running…")
    elif state == "SUCCEEDED":
        st.success(message or "Planner finished successfully. Refresh the view to load the new plan state.")
    elif state == "FAILED":
        st.error(message or "Planner failed. Existing plan state was preserved.")
    if state in {"SUCCEEDED", "FAILED"} and st.button("Dismiss planner status", use_container_width=False):
        clear_sync_status(review.repo.root)
        st.rerun()


def _trigger_refresh(plan: dict) -> None:
    week = plan.get("week") or {}
    result = start_planner(review.repo.root, str(week["monday"]), str(week["sunday"]), rebuild=False)
    st.success(f"Planner refresh started · run {result['run_id'][:8]}")


def _safe_rebuild_active_week(repo) -> None:
    st.divider()
    st.caption("Rebuild week")
    try:
        active = ensure_active_plan(repo)
    except PlanNotFound:
        st.info("No stored plan is available to rebuild.")
        return
    week = active.get("week") or {}
    monday, sunday = str(week.get("monday") or ""), str(week.get("sunday") or "")
    st.warning(
        f"Rebuild {monday} through {sunday} from live sources. The current plan is NOT deleted first; it remains active unless a complete validated replacement succeeds."
    )
    confirmed = st.checkbox("I want to rebuild this week from scratch", key=f"rebuild-confirm-{active.get('plan_id')}")
    if st.button("Rebuild active week", type="primary", disabled=not confirmed, use_container_width=True):
        result = start_planner(repo.root, monday, sunday, rebuild=True)
        st.success(f"Safe rebuild started · run {result['run_id'][:8]}. Existing state remains available until replacement succeeds.")


def _generate_current_week_action(*, compact: bool = False) -> None:
    monday, sunday = _current_week()
    if has_working_week(review.repo, monday, sunday):
        return

    if compact:
        st.info(f"Current week {monday} → {sunday} has no working plan yet.")
    else:
        st.info(f"No working plan exists for the current week. Build {monday} through {sunday} from live sources.")

    if st.button("Generate current week", type="primary", use_container_width=True, key=f"generate-current-{monday}"):
        # This is a CREATE when the week is absent. rebuild=False is deliberate:
        # historical plans may exist and must not affect or be replaced by this run.
        result = start_planner(review.repo.root, monday, sunday, rebuild=False)
        st.success(f"Current-week generation started · run {result['run_id'][:8]}")


def _bootstrap_current_week() -> None:
    _generate_current_week_action(compact=False)
    _render_job_status()


# review_app still owns the mature review surface. Replace only its orchestration
# hooks; all plan writes now go through the 0.6 deterministic core.
review._trigger_planner = _trigger_refresh
# The legacy widget understands lowercase pre-0.6 status only and would label
# RUNNING as finished. 0.6 renders its supervised job status here instead.
review._sync_status_widget = lambda: None
ui_admin._fresh_start_active_week = _safe_rebuild_active_week


def main() -> None:
    review.require_login()

    try:
        ensure_active_plan(review.repo)
        stored = review._select_plan()
    except PlanNotFound:
        st.markdown("## ⏱️ Timesheet Clerk")
        build_tab, config_tab, skill_tab, state_tab = st.tabs(["Generate", "Configuration", "SKILL", "State"])
        with build_tab:
            _bootstrap_current_week()
        with config_tab:
            review.render_config(review.repo, review.DEFAULT_SKILL)
        with skill_tab:
            review.render_skill(review.repo, review.DEFAULT_SKILL)
        with state_tab:
            review.render_state(review.repo, None, {})
        return

    try:
        with st.spinner("Loading Timesheet Clerk…", show_time=True):
            plan = review._with_context(stored)
    except Exception as exc:
        st.error(f"Could not load Simplicate review choices: {exc}")
        plan = deepcopy(stored)
        plan["review_context"] = {}

    review_tab, booking_tab, config_tab, skill_tab, state_tab = st.tabs(
        ["Review", "Booking", "Configuration", "SKILL", "State"]
    )
    with review_tab:
        _generate_current_week_action(compact=True)
        review._review_page(stored, plan)
        _render_job_status()
    with booking_tab:
        render_booking(review.repo, stored["plan_id"])
    with config_tab:
        review.render_config(review.repo, review.DEFAULT_SKILL)
    with skill_tab:
        review.render_skill(review.repo, review.DEFAULT_SKILL)
    with state_tab:
        review.render_state(review.repo, stored, plan.get("review_context") or {})


if __name__ == "__main__":
    main()
