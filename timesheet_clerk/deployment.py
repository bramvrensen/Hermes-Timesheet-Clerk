"""Explicit paths for the independent Timesheet Clerk deployment."""
from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
PROFILE = "timesheet-clerk"


def standalone() -> bool:
    return os.getenv("TIMESHEET_CLERK_MODE", "").lower() == "standalone"


def hermes_root() -> Path:
    configured = os.getenv("TIMESHEET_CLERK_HERMES_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser()
    if standalone():
        return Path("/data/hermes")
    from .storage import default_state_dir
    return default_state_dir().parent


def profile_home(profile: str = PROFILE) -> Path:
    import re
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", profile):
        raise ValueError("Invalid Timesheet Clerk planner profile name")
    return hermes_root() / "profiles" / profile


def hermes_executable() -> str:
    return os.getenv("TIMESHEET_CLERK_HERMES_BIN", "/opt/hermes/.venv/bin/hermes")
