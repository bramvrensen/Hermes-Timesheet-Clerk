"""Guarded Simplicate booking preview page."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timesheet_clerk.booking import CONFIRMATION_TEXT, execute_booking, latest_approved_snapshot, preview_booking, write_enabled
from timesheet_clerk.config import SimplicateConfig
from timesheet_clerk.simplicate import SimplicateClient
from timesheet_clerk.storage import PlanRepository, StateConflict
from timesheet_clerk.ui_auth import require_login

st.set_page_config(page_title="Timesheet Clerk · Booking", page_icon="🧾", layout="wide")
require_login()
repo = PlanRepository()

st.title("🧾 Simplicate booking")
st.caption("Booking reads an immutable APPROVED snapshot. Preview is read-only; live writes are disabled by default.")

try:
    active = repo.get_active()
    snapshot = latest_approved_snapshot(repo, active["plan_id"])
except Exception as exc:
    st.info(f"No approved snapshot ready for booking: {exc}")
    st.stop()

st.write(f"Approved plan: `{snapshot['plan_id']}` revision {snapshot['revision']} · {snapshot.get('approved_at','')}")
if int(snapshot.get("revision") or 0) != int(active.get("revision") or 0):
    st.warning(f"Active working revision is {active['revision']}, but the latest approved snapshot is revision {snapshot['revision']}. Booking will only use the approved snapshot.")

try:
    client = SimplicateClient(SimplicateConfig.from_env())
    with st.spinner("Running Simplicate preflight…"):
        preview = preview_booking(repo, snapshot, client)
except Exception as exc:
    st.error(f"Booking preflight failed: {exc}")
    st.stop()

m1, m2, m3, m4 = st.columns(4)
m1.metric("Approved rows", preview["entry_count"])
m2.metric("Ready", preview["ready_count"])
m3.metric("Already receipted", preview["already_booked_count"])
m4.metric("Possible duplicates", preview["possible_duplicate_count"])

if preview["possible_duplicate_count"]:
    st.error("Possible existing Simplicate registrations detected. Live booking is blocked until these are resolved.")

for row in preview["rows"]:
    status = row["preflight_status"]
    icon = "✅" if status == "ready" else "⏭️" if status == "already_booked" else "⚠️"
    with st.expander(f"{icon} {row['description'] or row['entry_id']} · {status}", expanded=status != "ready"):
        st.caption(f"Entry {row['entry_id']} · Clockify sources: {', '.join(row['clockify_source_ids'])}")
        st.json(row["payload"], expanded=True)
        if row["possible_existing_matches"]:
            st.write("Possible existing Simplicate matches")
            st.json(row["possible_existing_matches"], expanded=True)

st.divider()
if not write_enabled():
    st.info("Live Simplicate writes are physically disabled. Set TIMESHEET_CLERK_SIMPLICATE_WRITE_ENABLED=true only after this preview has been validated.")
else:
    st.error("LIVE SIMPLICATE WRITES ARE ENABLED")
    confirmation = st.text_input("Type the confirmation phrase", placeholder=CONFIRMATION_TEXT)
    allowed = confirmation == CONFIRMATION_TEXT and preview["possible_duplicate_count"] == 0 and preview["ready_count"] > 0
    if st.button("Book approved hours in Simplicate", type="primary", disabled=not allowed):
        try:
            with st.spinner("Booking approved hours…"):
                result = execute_booking(repo, snapshot, client, confirmation)
            st.success(f"Booked {result['booked_count']} row(s); skipped {result['skipped_count']} row(s).")
            st.json(result, expanded=False)
        except StateConflict as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"Booking stopped: {exc}")

st.caption("Submitting hours for approval in Simplicate is intentionally not part of this first booking phase.")
