"""Supervise one background Hermes planner run and persist reliable job status."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_status(root: Path, payload: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "planner-sync-status.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--prompt", required=True)
    args = parser.parse_args()

    root = Path(args.root)
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "planner-refresh.log"
    base = {
        "runner_pid": os.getpid(),
        "profile": args.profile,
        "started_at": now(),
        "status": "RUNNING",
        "message": "Planner job is running.",
        "log_file": str(log_path),
    }
    write_status(root, base)

    command = ["/opt/hermes/.venv/bin/hermes", "-p", args.profile, "chat", "-q", args.prompt]
    try:
        with log_path.open("ab") as handle:
            completed = subprocess.run(
                command,
                cwd=f"/home/hermes/.hermes/profiles/{args.profile}",
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=False,
            )
        status = "SUCCEEDED" if completed.returncode == 0 else "FAILED"
        write_status(root, {
            **base,
            "status": status,
            "finished_at": now(),
            "exit_code": completed.returncode,
            "message": "Planner job completed successfully." if completed.returncode == 0 else f"Planner job failed with exit code {completed.returncode}.",
        })
        return completed.returncode
    except Exception as exc:
        write_status(root, {
            **base,
            "status": "FAILED",
            "finished_at": now(),
            "exit_code": None,
            "message": f"Planner job launcher failed: {exc}",
        })
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
