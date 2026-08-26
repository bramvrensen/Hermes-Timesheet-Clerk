"""HERMES Timesheet Clerk package bootstrap."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

__version__ = "0.6.6"

# Keep only the latest two mutable working revisions by default. Approval
# snapshots, receipts and feedback are stored separately and remain immutable.
os.environ.setdefault("TIMESHEET_CLERK_REVISION_RETENTION", "2")

_SHARED_STATE = Path("/home/hermes/.hermes/timesheet-clerk")
_LEGACY_STATE = Path("/home/hermes/.hermes/profiles/atlas/timesheet-clerk")


def _bootstrap_shared_state() -> None:
    """Select Hermes shared state only when actually running inside Hermes.

    Importing this package must be side-effect free on developer/CI machines. The
    generic storage layer already falls back to ``$HOME/.hermes/timesheet-clerk``.
    """
    configured = str(os.environ.get("TIMESHEET_CLERK_STATE_DIR") or "").strip()
    hermes_home_exists = Path("/home/hermes").is_dir()

    if configured:
        root = Path(configured).expanduser()
    elif hermes_home_exists:
        if not _SHARED_STATE.exists() and _LEGACY_STATE.exists():
            _SHARED_STATE.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(_LEGACY_STATE), str(_SHARED_STATE))
            except OSError:
                shutil.copytree(_LEGACY_STATE, _SHARED_STATE, dirs_exist_ok=True)
        os.environ["TIMESHEET_CLERK_STATE_DIR"] = str(_SHARED_STATE)
        root = _SHARED_STATE
    else:
        return

    root.mkdir(parents=True, exist_ok=True)

    argv = " ".join(str(v) for v in sys.argv).lower()
    if "streamlit" in argv or "frontend/app.py" in argv:
        try:
            from .storage import PlanRepository
            PlanRepository(root).compact_all_working_revisions()
        except Exception:
            pass


_bootstrap_shared_state()
