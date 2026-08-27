"""Booking status and staged batch controls for Timesheet Clerk."""
from __future__ import annotations

import json

import streamlit as st

from .storage import PlanRepository
from .ui_time import format_duration


def _receipts_for_plan(repo: PlanRepository, plan_id: str) -> list[dict]:
    rows: list[dict] = []
    for path in repo.receipts_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("plan_id") == plan_id:
            rows.append(payload)
    return rows


def render_booking(repo: PlanRepository, plan_id: str) -> None:
    st.subheader("🧾 Booking")
    plan = repo.get_latest(plan_id)
    receipts = _receipts_for_plan(repo, plan_id)
    entries = [row for row in plan.get("entries") or [] if not row.get("ignored")]
    booked = [row for row in entries if row.get("reconciliation_state") == "BOOKED"]
    booked_seconds = sum(int(row.get("planned_duration_seconds") or 0) for row in booked)
    open_seconds = sum(int(row.get("planned_duration_seconds") or 0) for row in entries if row.get("reconciliation_state") != "BOOKED")

    cols = st.columns(4)
    cols[0].metric("Bookable tasks", len(entries))
    cols[1].metric("Booked", len(booked))
    cols[2].metric("Booked time", format_duration(booked_seconds))
    cols[3].metric("Open time", format_duration(open_seconds))

    st.info("0.7.0 validates live Simplicate writes task by task. Open an entry in Review and use Book task. Each successful POST receives an immediate receipt and readback verification.")
    if receipts:
        st.caption(f"{len(receipts)} booking receipt(s) stored for this plan.")

    st.divider()
    st.button(
        "Book week",
        disabled=True,
        use_container_width=True,
        help="Available after single-task and day booking have been validated in production.",
    )
    st.caption("Book day and Book week are intentionally locked during the first live-write validation phase.")
