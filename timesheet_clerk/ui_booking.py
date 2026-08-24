"""Inline Booking tab for the Timesheet Clerk Streamlit frontend."""
from __future__ import annotations

from typing import Any

import streamlit as st

from .booking import latest_approved_snapshot, preview_booking, write_enabled
from .config import SimplicateConfig
from .simplicate import SimplicateClient
from .storage import PlanRepository, StateConflict


def _status_label(value: str) -> str:
    return {
        "ready": "READY",
        "already_booked": "RECEIPT EXISTS",
        "possible_duplicate": "POSSIBLE DUPLICATE",
    }.get(value, value.upper())


def _render_payload(row: dict[str, Any]) -> None:
    payload = row.get("payload") or {}
    status = str(row.get("preflight_status") or "unknown")
    title = f"{_status_label(status)} · {payload.get('start_date', '')} · {payload.get('hours', 0)}h · {row.get('description') or row.get('entry_id')}"
    with st.expander(title):
        st.caption(f"Entry {row.get('entry_id')} · Clockify sources: {', '.join(row.get('clockify_source_ids') or [])}")
        st.json(payload, expanded=True)
        matches = row.get("possible_existing_matches") or []
        if matches:
            st.warning(f"{len(matches)} possible existing Simplicate registration(s) match this row. Live booking must remain blocked until resolved.")
            st.json(matches, expanded=False)


def render_booking(repo: PlanRepository, plan_id: str) -> None:
    st.subheader("🧾 Booking")
    st.caption("Simplicate booking preflight. This view does not write hours yet.")

    try:
        snapshot = latest_approved_snapshot(repo, plan_id)
    except StateConflict:
        st.info("This week has no approved snapshot yet. Finish review and use Approve week first.")
        return

    week = snapshot.get("week") or {}
    st.caption(f"Approved week {week.get('monday')} → {week.get('sunday')} · revision {snapshot.get('revision')} · approved {snapshot.get('approved_at') or 'unknown'}")

    if write_enabled():
        st.warning("The backend live-write flag is enabled, but this UI still exposes preview only. No POST action is available here.")
    else:
        st.success("Live Simplicate writes are disabled. Preflight is read-only.")

    key = f"booking_preview:{snapshot.get('plan_id')}:{snapshot.get('revision')}"
    if st.button("Run Simplicate preflight", type="primary", use_container_width=True, key="run-booking-preflight"):
        try:
            with st.spinner("Reading existing Simplicate hours and building exact booking payloads…", show_time=True):
                client = SimplicateClient(SimplicateConfig.from_env())
                st.session_state[key] = preview_booking(repo, snapshot, client)
        except Exception as exc:
            st.session_state.pop(key, None)
            st.error(f"Preflight failed: {exc}")

    preview = st.session_state.get(key)
    if not preview:
        st.info("Run preflight to compare this approved snapshot with live Simplicate data. No hours will be created.")
        return

    cols = st.columns(4)
    cols[0].metric("Rows", int(preview.get("entry_count") or 0))
    cols[1].metric("Ready", int(preview.get("ready_count") or 0))
    cols[2].metric("Receipted", int(preview.get("already_booked_count") or 0))
    cols[3].metric("Possible duplicates", int(preview.get("possible_duplicate_count") or 0))

    duplicate_count = int(preview.get("possible_duplicate_count") or 0)
    if duplicate_count:
        st.error(f"Preflight found {duplicate_count} possible duplicate row(s). Live booking would be blocked.")
    else:
        st.success("Preflight found no possible duplicate registrations.")

    st.markdown("#### Exact Simplicate payloads")
    for row in preview.get("rows") or []:
        _render_payload(row)
