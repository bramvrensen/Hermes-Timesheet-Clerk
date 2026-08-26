"""Streamlit-facing planner actions for the 0.6 mapping-decision workflow."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .runtime import read_config
from .ui_sync import clear_sync_status, launch_sync


def planner_prompt(monday: str, sunday: str, *, rebuild: bool) -> str:
    mode = "safe full rebuild" if rebuild else "incremental refresh"
    return (
        f"Run Timesheet Clerk {mode} for week {monday} through {sunday}. "
        f"FIRST call timesheet_mapping_prepare with monday='{monday}', sunday='{sunday}', rebuild={str(rebuild).lower()}. "
        "This tool owns Clockify source comparison and returns the exact work_items. Do not construct, edit, infer or serialize a booking plan. "
        "If no_op is true, stop and report its deterministic summary. Otherwise load timesheet_config_get, timesheet_learning_context and only the Simplicate context needed to decide those work_items. "
        "For every work_item return exactly one mapping decision keyed by source_id with tier AUTO/PROPOSE/ASK, booking_mode assignment/direct, the selected assignment or direct_mapping when available, ignored flag when appropriate, why, why_not_auto, confidence and mapping_source. "
        f"Then call timesheet_mapping_apply exactly once with the same week, rebuild={str(rebuild).lower()}, and the complete decisions array. "
        "The rebuild flag is immutable for this planner run. In particular, a refresh started with rebuild=false must NEVER retry or escalate to rebuild=true after an error; an explicit user action is required to start a rebuild. "
        "Python owns plan IDs, week metadata, Clockify source facts, durations, revisioning, merge behaviour, human-review preservation and persistence. "
        "Never call terminal, execute_code, filesystem tools or generic file tools for Timesheet Clerk state. Never delete/reset a plan and never book hours to Simplicate. "
        "If a Timesheet Clerk tool fails, stop immediately and report the exact error; do not invent a recovery strategy."
    )


def start_planner(root: Path, monday: str, sunday: str, *, rebuild: bool) -> dict[str, Any]:
    cfg = read_config()
    profile = str(cfg.get("planner_profile") or "atlas")
    clear_sync_status(root)
    return launch_sync(root=root, profile=profile, prompt=planner_prompt(monday, sunday, rebuild=rebuild))
