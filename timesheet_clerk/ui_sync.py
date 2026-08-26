"""Background planner job transport shared with Streamlit.

0.6 runs a supervised helper process. The helper writes RUNNING -> SUCCEEDED/FAILED
with an exit code, so the frontend never relies on a stale fire-and-forget PID as
its source of truth.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def launch_sync(*, root: Path, profile: str, prompt: str, apply_refresh_contract: bool = False) -> dict[str, Any]:
    del apply_refresh_contract  # retained only for compatibility with older frontend calls
    run_id = uuid.uuid4().hex
    payload = {
        "run_id": run_id,
        "pid": None,
        "profile": profile,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "STARTING",
        "message": "Starting Timesheet Clerk planner…",
    }
    _write(root, payload)
    child = subprocess.Popen(
        [sys.executable, "-m", "timesheet_clerk.job_runner", str(root), profile, prompt, run_id],
        cwd=str(Path(__file__).resolve().parents[1]),
        start_new_session=True,
    )
    payload["pid"] = child.pid
    payload["status"] = "RUNNING"
    payload["message"] = "Planner is mapping Timesheet Clerk work items."
    _write(root, payload)
    return payload


def sync_status(root: Path) -> dict[str, Any] | None:
    path = root / "planner-sync-status.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("status") in {"STARTING", "RUNNING"}:
        pid = int(payload.get("pid") or 0)
        if pid and not _pid_running(pid):
            # Normally job_runner writes a terminal state itself. If it died before
            # doing so, fail closed instead of leaving an eternal RUNNING status.
            payload.update({
                "status": "FAILED",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "message": "Planner runner disappeared before reporting completion.",
            })
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
