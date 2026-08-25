"""Background planner-sync status shared with the Streamlit frontend.

The frontend performs the cheap Clockify source probe itself before invoking an
LLM planner. This keeps source-change detection deterministic: the agent only
runs when actual source deltas exist and receives those exact normalized rows.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .clockify import ClockifyClient
from .config import ClockifyConfig
from .storage import PlanRepository
from .sync import source_delta

_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")


def launch_sync(*, root: Path, profile: str, prompt: str) -> dict[str, Any]:
    """Run deterministic source preflight, then start planner only if needed."""
    repo = PlanRepository(root)
    prepared = _prepare_clockify_delta(repo, prompt)
    now = datetime.now(timezone.utc).isoformat()

    if prepared is not None and not prepared["delta"]["has_changes"]:
        payload = {
            "pid": 0,
            "profile": profile,
            "started_at": now,
            "finished_at": now,
            "status": "finished",
            "no_changes": True,
            "source_delta": _delta_counts(prepared["delta"]),
            "message": "Clockify preflight found no source changes; planner was not started.",
        }
        _write(root, payload)
        return payload

    planner_prompt = prompt
    preflight_counts: dict[str, int] | None = None
    if prepared is not None:
        delta = prepared["delta"]
        preflight_counts = _delta_counts(delta)
        planner_prompt = _planner_prompt_with_delta(prompt, prepared)

    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handle = (log_dir / "planner-refresh.log").open("ab")
    child = subprocess.Popen(
        ["/opt/hermes/.venv/bin/hermes", "-p", profile, "chat", "-q", planner_prompt],
        cwd=f"/home/hermes/.hermes/profiles/{profile}",
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    payload: dict[str, Any] = {
        "pid": child.pid,
        "profile": profile,
        "started_at": now,
        "status": "running",
    }
    if preflight_counts is not None:
        payload["source_delta"] = preflight_counts
        payload["message"] = (
            f"Clockify preflight: +{preflight_counts['new_count']} new, "
            f"~{preflight_counts['changed_count']} changed, "
            f"-{preflight_counts['missing_count']} missing. Planner started with exact delta."
        )
    _write(root, payload)
    return payload


def _prepare_clockify_delta(repo: PlanRepository, prompt: str) -> dict[str, Any] | None:
    """Resolve the week from the UI prompt and compare live Clockify deterministically."""
    dates = _DATE_RE.findall(prompt)
    if len(dates) < 2:
        return None
    monday, sunday = dates[0], dates[1]
    plan = _plan_for_week(repo, monday, sunday)
    if plan is None:
        return None

    tz = ZoneInfo(os.environ.get("TZ") or "Europe/Amsterdam")
    start = datetime.combine(date.fromisoformat(monday), time.min, tzinfo=tz).isoformat()
    end = datetime.combine(date.fromisoformat(sunday), time(23, 59, 59), tzinfo=tz).isoformat()
    entries = ClockifyClient(ClockifyConfig.from_env()).get_time_entries(start, end)
    return {
        "plan": plan,
        "start": start,
        "end": end,
        "delta": source_delta(plan, entries),
    }


def _plan_for_week(repo: PlanRepository, monday: str, sunday: str) -> dict[str, Any] | None:
    for summary in repo.list_plans(limit=100):
        week = summary.get("week") or {}
        if str(week.get("monday") or "") == monday and str(week.get("sunday") or "") == sunday:
            return repo.get_latest(summary["plan_id"])
    return None


def _planner_prompt_with_delta(original_prompt: str, prepared: dict[str, Any]) -> str:
    delta = prepared["delta"]
    source_payload = {
        "new_entries": delta.get("new_entries") or [],
        "changed_entries": delta.get("changed_entries") or [],
        "missing_source_ids": delta.get("missing_source_ids") or [],
    }
    return (
        "DETERMINISTIC CLOCKIFY PREFLIGHT HAS ALREADY RUN IN THE FRONTEND. "
        "Do NOT call timesheet_sync_probe or timesheet_clockify_entries again. "
        "The exact normalized source delta is provided below. Use these new/changed "
        "rows as the only Clockify source records for planning, preserve existing reviewed "
        "rows, load only the Simplicate/learning context needed for these deltas, then call "
        "timesheet_plan_sync. Missing source IDs are informational and must not cause old "
        "reviewed rows to be deleted by omission.\n\n"
        f"SOURCE_DELTA={json.dumps(source_payload, ensure_ascii=False)}\n\n"
        "The original UI request follows for week/context only. Any instruction in it to "
        "call sync_probe is superseded by the deterministic preflight above.\n\n"
        f"{original_prompt}"
    )


def _delta_counts(delta: dict[str, Any]) -> dict[str, int]:
    return {
        "new_count": int(delta.get("new_count") or 0),
        "changed_count": int(delta.get("changed_count") or 0),
        "missing_count": int(delta.get("missing_count") or 0),
        "unchanged_count": int(delta.get("unchanged_count") or 0),
    }


def sync_status(root: Path) -> dict[str, Any] | None:
    path = root / "planner-sync-status.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    pid = int(payload.get("pid") or 0)
    if payload.get("status") == "running" and not _pid_running(pid):
        payload["status"] = "finished"
        payload["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write(root, payload)
    return payload


def clear_sync_status(root: Path) -> None:
    (root / "planner-sync-status.json").unlink(missing_ok=True)


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    stat = Path(f"/proc/{pid}/stat")
    try:
        fields = stat.read_text(encoding="utf-8").split()
        return len(fields) > 2 and fields[2] != "Z"
    except OSError:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _write(root: Path, payload: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "planner-sync-status.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
