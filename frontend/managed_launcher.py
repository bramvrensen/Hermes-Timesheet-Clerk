"""Managed Streamlit launcher for Timesheet Clerk.

Runs Streamlit as a child process and restarts it when the admin UI writes the
shared-state restart marker. Intended as the command for the Compose service.
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


def main() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        RESTART_FILE.unlink(missing_ok=True)
        child = subprocess.Popen(command(), cwd=PLUGIN_DIR)
        while child.poll() is None:
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
        time.sleep(1)


if __name__ == "__main__":
    main()
