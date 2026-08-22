"""Managed Streamlit launcher for Timesheet Clerk.

Runs Streamlit as a child process and restarts it when the admin UI writes the
shared-state restart marker. Intended as the command for the Compose service.

Because this launcher is PID 1 in the dedicated frontend container, it also
reaps completed orphaned child processes (for example background planner runs)
so they do not accumulate as zombies.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

PLUGIN_DIR = Path(os.environ.get("TIMESHEET_CLERK_PLUGIN_DIR", "/home/hermes/.hermes/plugins/timesheet-clerk"))
STATE_DIR = Path(os.environ.get("TIMESHEET_CLERK_STATE_DIR", "/home/hermes/.hermes/timesheet-clerk"))
PORT = os.environ.get("TIMESHEET_CLERK_UI_PORT", "8501")
BASE_PATH = os.environ.get("TIMESHEET_CLERK_UI_BASE_PATH", "timesheet")
RESTART_FILE = STATE_DIR / "frontend-restart.request"


def command() -> list[str]:
    return [
        "uv", "run",
        "--with", "streamlit",
        "--with", "requests",
        "--with", "streamlit-cookies-controller",
        "streamlit", "run", "frontend/app.py",
        "--server.address", "0.0.0.0",
        "--server.port", PORT,
        "--server.baseUrlPath", BASE_PATH,
    ]


def _reap_orphans() -> None:
    """Reap any exited children adopted by PID 1 without blocking."""
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return


def main() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        _reap_orphans()
        RESTART_FILE.unlink(missing_ok=True)
        child = subprocess.Popen(command(), cwd=PLUGIN_DIR)
        while child.poll() is None:
            _reap_orphans()
            if RESTART_FILE.exists():
                RESTART_FILE.unlink(missing_ok=True)
                child.terminate()
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                break
            time.sleep(1)
        _reap_orphans()
        time.sleep(1)


if __name__ == "__main__":
    main()
