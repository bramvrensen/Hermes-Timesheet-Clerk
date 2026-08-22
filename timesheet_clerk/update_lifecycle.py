"""Hermes-native Timesheet Clerk update lifecycle."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _disk_version(plugin_root: Path) -> str:
    manifest = plugin_root / "plugin.yaml"
    for raw in manifest.read_text(encoding="utf-8").splitlines():
        if raw.startswith("version:"):
            return raw.split(":", 1)[1].strip()
    return "unknown"


def _frontend_runtime_version(state_root: Path) -> str | None:
    path = state_root / "frontend-runtime.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = str(payload.get("version") or "").strip()
    return value or None


def _request_frontend_restart(state_root: Path) -> None:
    state_root.mkdir(parents=True, exist_ok=True)
    (state_root / "frontend-restart.request").write_text("restart\n", encoding="utf-8")


def build_update_handler(plugin):
    """Return an update handler bound to the currently loaded plugin module."""

    def handle_update(params: dict[str, Any], **kwargs: Any) -> str:
        del params, kwargs

        def run() -> dict[str, Any]:
            if not (plugin.PLUGIN_ROOT / ".git").exists():
                raise RuntimeError("Timesheet Clerk is not installed as a Git checkout; self-update is unavailable")
            dirty = plugin._git("status", "--porcelain").stdout.strip()
            if dirty:
                raise RuntimeError("Timesheet Clerk checkout has local changes; refusing to pull over them")

            before = plugin._git("rev-parse", "HEAD").stdout.strip()
            pull = plugin._git("pull", "--ff-only", timeout=120, check=False)
            if pull.returncode != 0:
                raise RuntimeError(pull.stderr.strip() or pull.stdout.strip() or f"git pull exited {pull.returncode}")
            after = plugin._git("rev-parse", "HEAD").stdout.strip()
            updated = before != after

            repo = plugin.PlanRepository()
            disk_version = _disk_version(plugin.PLUGIN_ROOT)
            frontend_version = _frontend_runtime_version(repo.root)
            frontend_restart_requested = False

            # A no-op update is intentionally cheap. The only work still allowed
            # is healing a frontend/runtime version mismatch, including the first
            # 0.4.4 -> 0.4.5 transition where no heartbeat exists yet.
            if not updated:
                if frontend_version != disk_version:
                    _request_frontend_restart(repo.root)
                    frontend_restart_requested = True
                return {
                    "before_commit": before,
                    "after_commit": after,
                    "updated": False,
                    "version": disk_version,
                    "git_output": pull.stdout.strip(),
                    "smoke_test": "skipped (no code changes)",
                    "gateway_restart_scheduled": False,
                    "frontend_runtime_version": frontend_version,
                    "frontend_restart_requested": frontend_restart_requested,
                    "note": "Already up to date. No gateway restart was scheduled.",
                }

            tests = plugin._self_update_smoke_test()
            cfg = plugin.read_config()
            profile = str(cfg.get("planner_profile") or "atlas")
            plugin.ensure_profile_skill_registration(profile)
            plugin.ensure_runtime_skill(plugin.DEFAULT_TIMESHEET_SKILL)

            # The managed frontend launcher already watches this shared marker.
            # Requesting a child restart keeps frontend deployment independent
            # from Docker while loading the just-pulled Streamlit code/version.
            _request_frontend_restart(repo.root)
            frontend_restart_requested = True

            # Hermes does not expose safe live Python plugin hot-reload. Its
            # supported supervised SIGUSR1 path reloads only the gateway process,
            # not the Docker container.
            plugin._schedule_gateway_restart()
            return {
                "before_commit": before,
                "after_commit": after,
                "updated": True,
                "version": disk_version,
                "git_output": pull.stdout.strip(),
                "smoke_test": tests,
                "planner_profile": profile,
                "gateway_restart_scheduled": True,
                "frontend_runtime_version": frontend_version,
                "frontend_restart_requested": frontend_restart_requested,
                "note": "Update validated. Frontend restart requested and Hermes gateway restart scheduled.",
            }

        return plugin._safe(run)

    return handle_update
