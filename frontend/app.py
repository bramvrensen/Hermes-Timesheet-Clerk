"""Timesheet Clerk Streamlit shell with fixed in-app navigation."""
from __future__ import annotations

import os
from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

import review_app as review
from timesheet_clerk.runtime import read_config
from timesheet_clerk.storage import PlanNotFound
from timesheet_clerk.ui_booking import render_booking
from timesheet_clerk.ui_sync import clear_sync_status, launch_sync


def _bootstrap_current_week() -> None:
    tz = ZoneInfo(os.environ.get("TZ") or "Europe/Amsterdam")
    today = datetime.now(tz).date()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    st.info(f"No booking plan exists for the current working state. You can build week {monday} through {sunday} from live sources.")
    if st.button("Generate current week from scratch", type="primary", use_container_width=True):
        cfg = read_config()
        profile = str(cfg.get("planner_profile") or "atlas")
        prompt = (
            f"Create a brand-new Timesheet Clerk plan for week {monday} through {sunday}. No working plan currently exists. "
            "Read timesheet_config_get, timesheet_learning_context, the complete Clockify week, and the Simplicate context/booking assignments required for mapping. "
            "Map every Clockify row using the normal AUTO/PROPOSE/ASK policy and call timesheet_plan_create exactly once with one complete plan covering every Clockify source. "
            "Do not use refresh/rebaseline semantics, do not attempt any reset, never manipulate Clerk filesystem state, and never book hours to Simplicate."
        )
        clear_sync_status(review.repo.root)
        launch_sync(root=review.repo.root, profile=profile, prompt=prompt, apply_refresh_contract=False)
        st.success(f"Full current-week generation started via {profile}. Refresh this page when the run finishes.")


def main() -> None:
    review.require_login()
    try:
        stored = review._select_plan()
    except PlanNotFound:
        st.markdown("## ⏱️ Timesheet Clerk")
        _bootstrap_current_week()
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
        review._review_page(stored, plan)
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
