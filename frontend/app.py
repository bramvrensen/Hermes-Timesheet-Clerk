"""Timesheet Clerk Streamlit shell with fixed in-app navigation."""
from __future__ import annotations

from copy import deepcopy

import streamlit as st

import review_app as review
from timesheet_clerk.storage import PlanNotFound
from timesheet_clerk.ui_booking import render_booking


def main() -> None:
    review.require_login()
    try:
        stored = review._select_plan()
    except PlanNotFound:
        st.info("No booking plan yet.")
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
