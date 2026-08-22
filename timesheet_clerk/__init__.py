"""HERMES Timesheet Clerk package bootstrap."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

__version__ = "0.4.1"

_SHARED_STATE = Path("/home/hermes/.hermes/timesheet-clerk")
_LEGACY_STATE = Path("/home/hermes/.hermes/profiles/atlas/timesheet-clerk")


def _bootstrap_shared_state() -> None:
    """Use agent-independent state and migrate the old Atlas-scoped state once.

    An explicit TIMESHEET_CLERK_STATE_DIR still wins. Without one, all profiles
    and the standalone frontend share /home/hermes/.hermes/timesheet-clerk.
    """
    configured = str(os.environ.get("TIMESHEET_CLERK_STATE_DIR") or "").strip()
    if configured:
        return

    if not _SHARED_STATE.exists() and _LEGACY_STATE.exists():
        _SHARED_STATE.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(_LEGACY_STATE), str(_SHARED_STATE))
        except OSError:
            # Cross-device/container-volume moves can fail. Copy first and leave
            # the legacy directory intact rather than risking state loss.
            shutil.copytree(_LEGACY_STATE, _SHARED_STATE, dirs_exist_ok=True)

    _SHARED_STATE.mkdir(parents=True, exist_ok=True)
    os.environ["TIMESHEET_CLERK_STATE_DIR"] = str(_SHARED_STATE)


_bootstrap_shared_state()
