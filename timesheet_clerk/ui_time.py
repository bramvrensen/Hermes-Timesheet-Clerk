"""Human-readable Timesheet Clerk duration presentation for Streamlit."""
from __future__ import annotations

import html
from typing import Any

import streamlit as st


def format_duration(seconds: Any, *, signed: bool = False) -> str:
    """Format seconds as human time, avoiding decimal-hour notation."""
    try:
        value = float(seconds or 0)
    except (TypeError, ValueError):
        value = 0.0
    sign = ""
    if value < 0:
        sign = "−"
    elif signed and value > 0:
        sign = "+"
    minutes_total = int(round(abs(value) / 60.0))
    hours, minutes = divmod(minutes_total, 60)
    if hours and minutes:
        text = f"{hours}u {minutes} min"
    elif hours:
        text = f"{hours}u"
    else:
        text = f"{minutes} min"
    return sign + text


def install_review_time_formatting(review: Any) -> None:
    """Patch only entry duration presentation, never review/booking control flow.

    The canonical day/week renderers live in ``frontend/review_app.py`` and are
    extended by ``frontend/app.py``.  This helper must remain presentation-only:
    replacing ``_render_day`` or ``_review_page`` here can silently shadow the
    guarded booking controls installed by those canonical renderers.
    """

    def entry_summary(plan: dict[str, Any], entry: dict[str, Any]) -> None:
        status = review._status(entry)
        css = status.lower()
        clocked = format_duration(entry.get("original_duration_seconds"))
        planned = format_duration(entry.get("planned_duration_seconds"))
        eid = html.escape(str(entry.get("entry_id") or ""), quote=True)
        timerange = f"{review._format_hm(entry.get('planned_start'))}–{review._format_hm(entry.get('planned_end'))}"
        st.markdown(
            f"<div id='entry-{eid}' class='tc-entry {css}'><div class='tc-row'>"
            f"<div class='tc-time'>{html.escape(timerange)}</div>"
            f"<div class='tc-hours'>{html.escape(planned)}</div>"
            f"<div><div class='tc-title'>{html.escape(review._entry_label(entry))}</div>"
            f"<div class='tc-sub'>Clockify: {html.escape(review._source_line(entry))} · {html.escape(clocked)}</div></div>"
            f"<div class='tc-target'>→ {html.escape(review._target_line(entry, plan))}</div>"
            f"<div><span class='tc-badge {css}'>{status}</span></div></div></div>",
            unsafe_allow_html=True,
        )

    review._entry_summary = entry_summary
