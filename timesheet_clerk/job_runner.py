"""Supervise one background Hermes planner run and persist a terminal job state."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    if len(sys.argv) != 5:
        raise SystemExit("usage: job_runner STATE_ROOT PROFILE PROMPT RUN_ID")
    root = Path(sys.argv[1])
    profile = sys.argv[2]
    prompt = sys.argv[3]
    run_id = sys.argv[4]
    status_path = root / "planner-sync-status.json"
    log_dir = root / "logs"; log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "planner-refresh.log"

    payload = {
        "run_id": run_id,
        "pid": os.getpid(),
        "profile": profile,
        "started_at": _now(),
        "status": "RUNNING",
        "message": "Planner is mapping Timesheet Clerk work items.",
    }
    _write(status_path, payload)
    try:
        with log_path.open("ab") as handle:
            completed = subprocess.run(
                ["/opt/hermes/.venv/bin/hermes", "-p", profile, "chat", "-q", prompt],
                cwd=f"/home/hermes/.hermes/profiles/{profile}",
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=False,
            )
        payload.update({
            "finished_at": _now(),
            "exit_code": completed.returncode,
            "status": "SUCCEEDED" if completed.returncode == 0 else "FAILED",
            "message": "Planner finished successfully." if completed.returncode == 0 else f"Planner exited with code {completed.returncode}.",
        })
    except Exception as exc:
        payload.update({
            "finished_at": _now(),
            "exit_code": None,
            "status": "FAILED",
            "message": f"Planner runner failed: {exc}",
        })
    _write(status_path, payload)
    return 0 if payload["status"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
