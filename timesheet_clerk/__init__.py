"""HERMES Timesheet Clerk package bootstrap."""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

__version__ = "0.5.5"

# Keep only the latest two mutable working revisions by default. Approval
# snapshots, receipts and feedback are stored separately and remain immutable.
os.environ.setdefault("TIMESHEET_CLERK_REVISION_RETENTION", "2")

_SHARED_STATE = Path("/home/hermes/.hermes/timesheet-clerk")
_LEGACY_STATE = Path("/home/hermes/.hermes/profiles/atlas/timesheet-clerk")


def _bootstrap_shared_state() -> None:
    """Use agent-independent state and migrate the old Atlas-scoped state once."""
    configured = str(os.environ.get("TIMESHEET_CLERK_STATE_DIR") or "").strip()
    if configured:
        root = Path(configured).expanduser()
    else:
        if not _SHARED_STATE.exists() and _LEGACY_STATE.exists():
            _SHARED_STATE.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(_LEGACY_STATE), str(_SHARED_STATE))
            except OSError:
                shutil.copytree(_LEGACY_STATE, _SHARED_STATE, dirs_exist_ok=True)
        _SHARED_STATE.mkdir(parents=True, exist_ok=True)
        os.environ["TIMESHEET_CLERK_STATE_DIR"] = str(_SHARED_STATE)
        root = _SHARED_STATE
    root.mkdir(parents=True, exist_ok=True)

    argv = " ".join(str(v) for v in sys.argv).lower()
    if "streamlit" in argv or "frontend/app.py" in argv:
        payload = {"version": __version__, "loaded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")}
        try:
            (root / "frontend-runtime.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass


_bootstrap_shared_state()
