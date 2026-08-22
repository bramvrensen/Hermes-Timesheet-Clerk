"""Mutable Timesheet Clerk runtime settings and skill state.

These files deliberately live outside the plugin checkout so git pulls cannot
overwrite user configuration or the live SKILL.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .storage import default_state_dir

DEFAULT_CONFIG: dict[str, Any] = {
    "planner_profile": "atlas",
    "contract_hours_default": 36.0,
    "auto_confidence_threshold": 0.90,
    "propose_confidence_threshold": 0.65,
    "semantic_similarity_auto_allowed": False,
    "require_strong_evidence_for_auto": True,
    "prefer_planned_assignment": True,
    "booked_artifact_retention_days": 365,
    "purge_after_successful_booking": True,
    "keep_feedback_forever": True,
    "keep_rules_forever": True,
}


def state_root() -> Path:
    root = default_state_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root


def config_path() -> Path:
    return state_root() / "config.json"


def runtime_skill_path() -> Path:
    return state_root() / "SKILL.md"


def read_config() -> dict[str, Any]:
    result = deepcopy(DEFAULT_CONFIG)
    path = config_path()
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {}
        if isinstance(payload, dict):
            result.update(payload)
    return validate_config(result)


def write_config(config: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(DEFAULT_CONFIG)
    merged.update(config or {})
    merged = validate_config(merged)
    _atomic_write_text(config_path(), json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
    return merged


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(config)
    result["planner_profile"] = str(result.get("planner_profile") or "atlas").strip() or "atlas"
    result["contract_hours_default"] = max(0.0, float(result.get("contract_hours_default", 36.0)))
    result["auto_confidence_threshold"] = _fraction(result.get("auto_confidence_threshold"), 0.90)
    result["propose_confidence_threshold"] = _fraction(result.get("propose_confidence_threshold"), 0.65)
    if result["propose_confidence_threshold"] > result["auto_confidence_threshold"]:
        raise ValueError("propose_confidence_threshold cannot exceed auto_confidence_threshold")
    result["semantic_similarity_auto_allowed"] = bool(result.get("semantic_similarity_auto_allowed", False))
    result["require_strong_evidence_for_auto"] = bool(result.get("require_strong_evidence_for_auto", True))
    result["prefer_planned_assignment"] = bool(result.get("prefer_planned_assignment", True))
    result["booked_artifact_retention_days"] = max(1, int(result.get("booked_artifact_retention_days", 365)))
    result["purge_after_successful_booking"] = bool(result.get("purge_after_successful_booking", True))
    result["keep_feedback_forever"] = bool(result.get("keep_feedback_forever", True))
    result["keep_rules_forever"] = bool(result.get("keep_rules_forever", True))
    return result


def ensure_runtime_skill(default_skill: Path) -> Path:
    target = runtime_skill_path()
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(default_skill, target)
    return target


def read_runtime_skill(default_skill: Path) -> str:
    return ensure_runtime_skill(default_skill).read_text(encoding="utf-8")


def write_runtime_skill(text: str, default_skill: Path) -> Path:
    if not str(text or "").strip():
        raise ValueError("SKILL.md cannot be empty")
    target = ensure_runtime_skill(default_skill)
    _atomic_write_text(target, text.rstrip() + "\n")
    return target


def purge_expired_artifacts(root: Path | None = None, *, now: datetime | None = None) -> dict[str, int]:
    """Remove booked snapshots/receipts older than configured retention.

    Working plans are not age-purged here. They are compacted explicitly after a
    successful booking, leaving only the approved snapshot and booking receipts.
    """
    base = Path(root) if root is not None else state_root()
    config = read_config()
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=config["booked_artifact_retention_days"])
    removed = {"approvals": 0, "receipts": 0}
    for key, directory_name in (("approvals", "approvals"), ("receipts", "receipts")):
        directory = base / directory_name
        if not directory.exists():
            continue
        for path in directory.glob("*.json"):
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if modified < cutoff:
                try:
                    path.unlink()
                    removed[key] += 1
                except OSError:
                    pass
    return removed


def _fraction(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number > 1.0:
        number = number / 100.0
    return min(1.0, max(0.0, number))


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
