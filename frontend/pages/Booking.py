"""Safe Simplicate booking preview page.

0.5.1 deliberately exposes preview/preflight only. Live POST execution remains
behind the backend write guard and is not wired to this page yet.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timesheet_clerk.booking import latest_approved_snapshot, preview_booking, write_enabled
from timesheet_clerk.config import SimplicateConfig
from timesheet_clerk.simplicate import SimplicateClient
from timesheet_clerk.storage import PlanNotFound, PlanRepository, StateConflict
from timesheet_clerk.ui_auth import require_login

st.set_page_config(page_title="Timesheet Clerk · Booking", page_icon="🧾", layout="wide")
repo = PlanRepository()


def _selected_plan_id() -> str | None:
    selected = str(st.session_state.get("selected_plan_id") or "").strip()
    if selected:
        return selected
    try:
        return str(repo.get_active().get("plan_id") or "") or None
    except PlanNotFound:
        return None


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


def main() -> None:
    require_login()
    st.title("🧾 Booking")
    st.caption("Simplicate booking preflight. This page does not write hours in 0.5.1.")

    plan_id = _selected_plan_id()
    if not plan_id:
        st.info("No Timesheet Clerk plan exists yet.")
        return

    try:
        snapshot = latest_approved_snapshot(repo, plan_id)
    except StateConflict:
        st.info("The selected week has no approved snapshot yet. Finish review and use Approve week first.")
        return

    week = snapshot.get("week") or {}
    st.subheader(f"Approved week {week.get('monday')} → {week.get('sunday')}")
    st.caption(f"{snapshot.get('plan_id')} · approved revision {snapshot.get('revision')} · approved {snapshot.get('approved_at') or 'unknown'}")

    if write_enabled():
        st.warning("The backend live-write flag is enabled, but this 0.5.1 page still exposes preview only. No POST action is available here.")
    else:
        st.success("Live Simplicate writes are disabled. Preflight is read-only.")

    key = f"booking_preview:{snapshot.get('plan_id')}:{snapshot.get('revision')}"
    if st.button("Run Simplicate preflight", type="primary", use_container_width=True):
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

    st.subheader("Exact Simplicate payloads")
    for row in preview.get("rows") or []:
        _render_payload(row)

    st.divider()
    st.caption("Next pilot step after validating these payloads: enable live writes deliberately and book exactly one approved row, read it back from Simplicate, persist its receipt, then prove a second attempt is rejected.")


if __name__ == "__main__":
    main()
