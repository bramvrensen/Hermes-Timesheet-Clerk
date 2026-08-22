"""HERMES Timesheet Clerk package bootstrap."""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any

__version__ = "0.4.6"

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

    # Streamlit runs in a separate child process. Persist its actually loaded
    # package version so the Hermes-native updater can detect stale frontend
    # code without depending on the frontend to orchestrate deployment.
    argv = " ".join(str(v) for v in sys.argv).lower()
    if "streamlit" in argv or "frontend/app.py" in argv:
        payload = {
            "version": __version__,
            "loaded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }
        try:
            (root / "frontend-runtime.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass


def _install_frontend_runtime_fixes() -> None:
    """Apply narrowly scoped Streamlit behavior fixes for the Clerk frontend."""
    st = sys.modules.get("streamlit")
    if st is None or getattr(st, "_timesheet_clerk_runtime_patched", False):
        return

    original_rerun = st.rerun
    original_dialog = st.dialog
    original_date_input = st.date_input

    @wraps(original_rerun)
    def rerun(*args: Any, **kwargs: Any):
        if kwargs.get("scope") == "fragment":
            # A dialog widget interaction already runs the dialog fragment.
            # Avoid a second immediate redraw after persisting an edit.
            return None
        return original_rerun(*args, **kwargs)

    @wraps(original_dialog)
    def dialog(*args: Any, **kwargs: Any):
        # Refresh the main review state when the modal is dismissed, not on
        # every save. This makes saved values visible without page-jump churn.
        kwargs.setdefault("on_dismiss", "rerun")
        return original_dialog(*args, **kwargs)

    @wraps(original_date_input)
    def date_input(label: str, *args: Any, **kwargs: Any):
        key = kwargs.get("key")
        if key == "timesheet_nav_date":
            current = st.session_state.get(key)
            # Older UI revisions stored a week range in this key. A scalar
            # date_input then looks frozen on the whole week in Day mode.
            if isinstance(current, (tuple, list)):
                if current:
                    st.session_state[key] = current[0]
                else:
                    st.session_state.pop(key, None)
        return original_date_input(label, *args, **kwargs)

    st.rerun = rerun
    st.dialog = dialog
    st.date_input = date_input
    st._timesheet_clerk_runtime_patched = True


_bootstrap_shared_state()
_install_frontend_runtime_fixes()
